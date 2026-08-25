"""Regression tests for ``DictAttr.__get__`` on legacy non-dict data (#225).

A field that became a ``DictAttr`` in a schema change leaves every
pre-change row storing the OLD shape — usually a list. ``__get__``
walked straight into ``results.items()``, so merely *reading* the
attribute raised ``AttributeError: 'BaseList' object has no attribute
'items'`` and every request touching it 500'd (consumer report:
Sallenmoore/storyteller#2358, ~12 rows took down a whole facet).

Contract pinned here:

- Non-dict stored value → return the field default, warn once naming
  model/field/pk. **The stored value is left untouched** so a consumer
  can still read ``_data`` and run its own lazy migration — unlike
  ``ListAttr``, which rewrites ``_data`` in place.
- Class-level access (``Model.field``) still returns the field object,
  per the mongoengine descriptor protocol.
"""

from unittest.mock import patch

import pytest

from autonomous.model.autoattr import DictAttr


def _make_doc(stored, field):
    """Stub document — same shape as the eager-deref pinning tests."""
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


@pytest.fixture
def field():
    f = DictAttr(default=dict)
    f.name = "props"
    f.db_field = "props"
    f.null = True
    return f


class TestLegacyNonDictShape:
    @pytest.mark.parametrize(
        "stored", [[], ["AC +2"], ["a", "b"], "a-string", 7]
    )
    def test_non_dict_value_does_not_raise(self, field, stored):
        # The bug: any of these reached ``.items()`` and raised.
        doc = _make_doc(field=field, stored=stored)
        assert field.__get__(doc, type(doc)) == {}

    def test_legacy_value_is_left_in_data_for_lazy_migration(self, field):
        # Distinct from ``ListAttr``'s self-heal: rewriting ``_data`` here
        # would destroy the very bytes a consumer needs to migrate from,
        # and a later ``save()`` would persist the loss.
        doc = _make_doc(field=field, stored=["AC +2"])
        field.__get__(doc, type(doc))
        assert doc._data["props"] == ["AC +2"]

    def test_warns_with_field_and_pk(self, field):
        doc = _make_doc(field=field, stored=["AC +2"])
        with patch("autonomous.model.autoattr.log") as mock_log:
            field.__get__(doc, type(doc))
        assert mock_log.warning.call_count == 1
        msg = str(mock_log.warning.call_args)
        assert "props" in msg
        # mongoengine wraps the stored list as ``BaseList`` — the exact
        # type name in the consumer traceback on #225.
        assert "list" in msg.lower()

    def test_declared_default_is_honoured(self):
        f = DictAttr(default={"tier": "base"})
        f.name = "props"
        f.db_field = "props"
        f.null = True
        doc = _make_doc(field=f, stored=["legacy"])
        assert f.__get__(doc, type(doc)) == {"tier": "base"}

    def test_returned_default_is_not_shared_between_reads(self):
        # A mutable default handed out by identity would let one caller's
        # mutation leak into every other legacy row's read.
        f = DictAttr(default={"tier": "base"})
        f.name = "props"
        f.db_field = "props"
        f.null = True
        first = f.__get__(_make_doc(field=f, stored=["x"]), object)
        first["tier"] = "MUTATED"
        second = f.__get__(_make_doc(field=f, stored=["x"]), object)
        assert second == {"tier": "base"}


class TestDescriptorProtocolPreserved:
    def test_class_level_access_returns_the_field(self, field):
        # ``Model.field`` must hand back the field object — mongoengine's
        # query machinery relies on it. The non-dict guard must not
        # mistake the field for legacy data and return {}.
        assert field.__get__(None, object) is field

    def test_normal_dict_still_deref_walks(self, field):
        doc = _make_doc(field=field, stored={"a": 1, "b": 2})
        assert field.__get__(doc, type(doc)) == {"a": 1, "b": 2}
