"""Regression tests for ReferenceAttr.__set__ dirty-field tracking.

Issue: assigning to a ``ReferenceAttr`` field on an already-saved document
did not mark the field dirty — ``_changed_fields`` stayed empty, so the
next ``save()`` excluded the field from the ``$set`` payload and the
assignment was silently dropped.

These tests pin the contract without a live MongoDB connection:
  1. ``_changed_fields`` is populated after assignment on an initialised doc.
  2. The field is marked dirty regardless of what the prior ``_data`` value
     was (None, raw ``{_cls, _ref}`` dict, or a previously-dereferenced
     Document object).
  3. Assigning ``None`` also marks the field dirty when the prior value was
     non-None.
"""

import bson
import pytest
from bson import DBRef

from autonomous.model.autoattr import ReferenceAttr, StringAttr


# ---------------------------------------------------------------------------
# Minimal document-like stub — avoids any MongoDB I/O
# ---------------------------------------------------------------------------

def _make_doc(ref_data=None, extra_data=None):
    """Return a minimal document stub that mimics an already-saved AutoModel.

    ``_initialised=True`` and ``_changed_fields=[]`` mirror the state that
    ``Document._from_son`` leaves behind.
    """
    # Use a plain dict for _data (StrictDict-compatible interface)
    data = {"ref": ref_data}
    if extra_data:
        data.update(extra_data)

    # Build a simple namespace with the minimum MongoEngine attributes
    class _Stub:
        _initialised = True
        _created = False
        _dynamic_fields = {}
        _db_field_map = {"ref": "ref"}
        _data = data
        _changed_fields = []

        def _mark_as_changed(self, key):
            key = self._db_field_map.get(key, key)
            if key not in self._changed_fields:
                self._changed_fields.append(key)

    return _Stub()


def _make_target_doc(pk=None):
    """Return a minimal target document stub."""
    pk = pk or bson.ObjectId()

    class _Target:
        id = pk
        _class_name = "Target"
        _meta = {"id_field": "id"}
        _fields = {}

        @classmethod
        def _get_collection_name(cls):
            return "target"

        def __eq__(self, other):
            if not other or not hasattr(other, "id"):
                return False
            return str(self.id) == str(other.id)

        def __ne__(self, other):
            return not self == other

        def __bool__(self):
            return True

    t = _Target()
    t.pk = pk
    return t


# ---------------------------------------------------------------------------
# Tests: _changed_fields after assignment
# ---------------------------------------------------------------------------

class TestReferenceAttrDirtyTracking:
    """ReferenceAttr.__set__ must always populate _changed_fields."""

    @pytest.fixture
    def field(self):
        """A standalone ReferenceAttr descriptor configured with name='ref'."""
        f = ReferenceAttr()
        f.name = "ref"
        f.db_field = "ref"
        f.null = True
        f.default = None
        return f

    # --- prior value is None -------------------------------------------------

    def test_assign_document_when_ref_is_none_marks_dirty(self, field):
        doc = _make_doc(ref_data=None)
        target = _make_target_doc()

        field.__set__(doc, target)

        assert "ref" in doc._changed_fields

    # --- prior value is a raw {_cls, _ref} dict (pre-dereference) -----------

    def test_assign_document_when_ref_is_raw_dict_marks_dirty(self, field):
        raw_ref = {"_cls": "Target", "_ref": DBRef("target", bson.ObjectId())}
        doc = _make_doc(ref_data=raw_ref)
        target = _make_target_doc()

        field.__set__(doc, target)

        assert "ref" in doc._changed_fields

    # --- prior value is a Document (already dereferenced) -------------------

    def test_assign_new_document_when_ref_is_document_marks_dirty(self, field):
        old_target = _make_target_doc()
        new_target = _make_target_doc()  # different pk
        doc = _make_doc(ref_data=old_target)

        field.__set__(doc, new_target)

        assert "ref" in doc._changed_fields

    # --- assigning None to a non-None field ----------------------------------

    def test_assign_none_when_ref_is_document_marks_dirty(self, field):
        old_target = _make_target_doc()
        doc = _make_doc(ref_data=old_target)

        field.__set__(doc, None)

        assert "ref" in doc._changed_fields

    # --- _changed_fields must NOT be polluted before _initialised is True ---

    def test_assignment_during_init_does_not_mark_dirty(self, field):
        """Before __init__ completes, _initialised=False; no dirty marking."""
        doc = _make_doc(ref_data=None)
        doc._initialised = False  # simulate mid-__init__ state
        doc._changed_fields = []
        target = _make_target_doc()

        field.__set__(doc, target)

        assert doc._changed_fields == []

    # --- _data is updated to the new value ----------------------------------

    def test_data_stores_the_new_value(self, field):
        doc = _make_doc(ref_data=None)
        target = _make_target_doc()

        field.__set__(doc, target)

        assert doc._data["ref"] is target


# ---------------------------------------------------------------------------
# Tests: ReferenceAttr.__get__ DoesNotExist -> None swallow (TEST-5 in #141)
# ---------------------------------------------------------------------------
#
# The companion to the __set__ dirty-mark contract above. autoattr.py:88-92
# overrides ``__get__`` to return ``None`` when the upstream
# ``GenericReferenceField.__get__`` raises ``DoesNotExist`` — half of the
# headline divergence documented in src/autonomous/db/DIVERGENCE.md
# §`ReferenceAttr`. Without this, a de-fork or a refactor of
# GenericReferenceField interaction would re-expose the raise, and every
# consumer relying on "deleted ref reads as None" breaks with no test signal.


class TestReferenceAttrGetSwallowsDoesNotExist:
    """``ReferenceAttr.__get__`` returns None on ``DoesNotExist``."""

    @pytest.fixture
    def field(self):
        f = ReferenceAttr()
        f.name = "ref"
        f.db_field = "ref"
        f.null = True
        f.default = None
        return f

    def test_doesnotexist_in_super_get_returns_none(self, field, monkeypatch):
        from autonomous.db import DoesNotExist
        from autonomous.db.fields import GenericReferenceField

        doc = _make_doc(ref_data=None)

        def _raises_doesnotexist(self, instance, owner):
            raise DoesNotExist

        monkeypatch.setattr(GenericReferenceField, "__get__", _raises_doesnotexist)

        result = field.__get__(doc, type(doc))

        assert result is None

    def test_normal_value_from_super_get_is_returned(self, field, monkeypatch):
        from autonomous.db.fields import GenericReferenceField

        doc = _make_doc(ref_data=None)
        target = _make_target_doc()

        def _returns_target(self, instance, owner):
            return target

        monkeypatch.setattr(GenericReferenceField, "__get__", _returns_target)

        result = field.__get__(doc, type(doc))

        assert result is target
