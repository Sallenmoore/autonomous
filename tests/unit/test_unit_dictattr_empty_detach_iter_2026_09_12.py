"""Independent coverage for PR #251 (closes #249): ``DictAttr.__get__``
keeps the BOUND ``BaseDict`` on an empty read.

Written from the PR diff alone (two-perspective rule).

The defect: ``super().__get__(...) or {}`` swapped an empty — and
therefore falsy — bound ``BaseDict`` for a fresh, detached plain dict, so
``obj.foo[k] = v; obj.save()`` persisted nothing and every re-read
re-detached. The fix returns the bound container and self-heals a stored
``None`` (``null=True`` fields) by assigning through the descriptor, so
the substitute is bound AND the whole field is marked changed.

Pinned at two altitudes:

- **Descriptor level** (stub document, no ORM): an empty read is the very
  object stored in ``_data``; a stored ``None`` leaves the field name in
  ``_changed_fields`` after a bare read.
- **Model level** (hermetic ``AutoModel`` subclass built through
  ``_from_son`` — the query path, where the loss was silent): in-place
  writes on an empty dict are change-tracked; the nullable case is
  whole-field-marked; ``ListAttr`` is the unaffected control.

The save → reload round trip lives in
``tests/integration/test_int_dictattr_empty_roundtrip_iter_2026_09_12.py``.
"""

import bson

from autonomous.db.base.datastructures import BaseDict, BaseList
from autonomous.model.autoattr import DictAttr, ListAttr, StringAttr
from autonomous.model.automodel import AutoModel


class _Bag(AutoModel):
    # Hermetic on its own terms: no construction path can reach
    # ``_get_collection`` whatever ``auto_pre_init`` does with ``created``
    # (that is #250's PR, not this one).
    auto_load_on_init = False
    label = StringAttr(default="")
    props = DictAttr()
    nullable = DictAttr(default=None, null=True)
    tags = ListAttr()


_OID = bson.ObjectId("507f1f77bcf86cd799439011")


def _loaded(**stored):
    """A document as the query path builds it: ``_from_son`` with
    ``created=False`` and an EMPTY ``_changed_fields`` — the state in
    which the detached-dict loss was invisible."""
    return _Bag._from_son({"_id": _OID, **stored})


# ---------------------------------------------------------------------------
# Descriptor level — the stub shape the committed DictAttr suites use.
# ---------------------------------------------------------------------------


def _stub_doc(stored, field):
    class _Stub:
        _initialised = True
        _created = False
        _dynamic_fields = {}
        _db_field_map = {"props": "props"}
        _data = {"props": stored}
        _fields = {"props": field}
        _changed_fields: list[str] = []

        def _mark_as_changed(self, key):
            key = self._db_field_map.get(key, key)
            if key not in self._changed_fields:
                self._changed_fields.append(key)

    return _Stub()


def _field(**kwargs):
    field = DictAttr(**kwargs)
    field.name = "props"
    field.db_field = "props"
    return field


class TestDescriptorLevel:
    def test_empty_read_is_the_object_stored_in_data(self):
        field = _field()
        doc = _stub_doc({}, field)
        read = field.__get__(doc, type(doc))
        assert isinstance(read, BaseDict)
        assert read is doc._data["props"]

    def test_empty_read_is_stable_across_reads(self):
        field = _field()
        doc = _stub_doc({}, field)
        assert field.__get__(doc, type(doc)) is field.__get__(doc, type(doc))

    def test_stored_none_reads_as_bound_empty_dict_and_marks_the_field(self):
        field = _field(default=None, null=True)
        doc = _stub_doc(None, field)
        read = field.__get__(doc, type(doc))
        assert read == {}
        assert isinstance(read, BaseDict)
        assert read is doc._data["props"]
        assert "props" in doc._changed_fields

    def test_class_level_access_still_returns_the_field(self):
        field = _field(default=None, null=True)
        assert field.__get__(None, object) is field


# ---------------------------------------------------------------------------
# Model level — change tracking through a real (unsaved) AutoModel.
# ---------------------------------------------------------------------------


class TestModelLevel:
    def test_in_place_write_on_empty_dict_is_change_tracked(self):
        doc = _loaded(props={})
        assert doc._changed_fields == []
        doc.props["k"] = "v"
        assert doc._data["props"] == {"k": "v"}
        assert "props.k" in doc._changed_fields

    def test_empty_read_returns_the_same_bound_object_every_time(self):
        doc = _loaded(props={})
        first = doc.props
        assert isinstance(first, BaseDict)
        assert first is doc._data["props"]
        assert doc.props is first

    def test_non_empty_dict_behaves_as_before(self):
        doc = _loaded(props={"a": 1})
        doc.props["b"] = 2
        assert doc._data["props"] == {"a": 1, "b": 2}
        assert "props.b" in doc._changed_fields

    def test_stored_none_self_heals_bound_and_whole_field_marked(self):
        doc = _loaded(nullable=None)
        assert doc._data["nullable"] is None
        read = doc.nullable
        assert read == {}
        assert isinstance(read, BaseDict)
        assert read is doc._data["nullable"]
        # Whole-field mark: save() must write ``{nullable: {...}}``, never
        # ``$set nullable.k`` onto a null parent.
        assert "nullable" in doc._changed_fields
        doc.nullable["k"] = "v"
        assert doc._data["nullable"] == {"k": "v"}

    def test_fresh_document_empty_dict_is_bound_too(self):
        doc = _Bag()
        assert isinstance(doc.props, BaseDict)
        assert doc.props is doc._data["props"]

    def test_listattr_is_the_unaffected_control(self):
        # ``ListAttr`` never had the ``or []``. Forward-looking guard: it
        # passes on the pre-#249 base as well (flagged in the bundle summary).
        doc = _loaded(tags=[])
        doc.tags.append("x")
        assert isinstance(doc.tags, BaseList)
        assert doc._data["tags"] == ["x"]
        assert "tags" in doc._changed_fields
