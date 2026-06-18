"""Pinning tests for ``ListAttr.__get__`` self-heal + reference-pruning (TEST-3 in #141).

Documents the contract in ``src/autonomous/db/DIVERGENCE.md`` §`ListAttr`:

- Non-list stored value → rewrites ``_data`` to ``[]`` and returns ``[]``.
- For lists of ``ReferenceAttr`` values, prunes ``None`` entries (deleted
  referents surface as ``None`` via ``ReferenceAttr.__get__`` swallow)
  and entries that raise ``DoesNotExist`` on access, **in place** on the
  returned list.
- Non-reference content is returned unmodified.

The in-place ``pop(i)`` index walk (without incrementing ``i`` on
removal) is exactly the kind of off-by-one a refactor breaks, and the
failure mode is silent data loss — not an exception.
"""

from unittest.mock import patch

import pytest

from autonomous.db import DoesNotExist
from autonomous.model.autoattr import ListAttr, ReferenceAttr, StringAttr


def _make_doc(stored, field):
    """Stub document for ListAttr.__get__ tests.

    ``field`` is forwarded into ``_fields`` so ``BaseField.__get__`` can
    read ``instance._fields[self.name]._auto_dereference`` per the
    upstream mongoengine descriptor protocol.
    """
    class _Stub:
        _initialised = True
        _created = False
        _dynamic_fields = {}
        _db_field_map = {"refs": "refs"}
        _data = {"refs": stored}
        _fields = {"refs": field}
        _changed_fields: list[str] = []

        def _mark_as_changed(self, key):
            key = self._db_field_map.get(key, key)
            if key not in self._changed_fields:
                self._changed_fields.append(key)

    return _Stub()


# -- Non-list rewrite path ----------------------------------------------------


class TestListAttrSelfHealRewrite:
    """The non-list-stored-value branch at ``autoattr.py:130-132``."""

    @pytest.fixture
    def field(self):
        f = ListAttr(StringAttr())
        f.name = "refs"
        f.db_field = "refs"
        f.null = True
        f.default = list
        return f

    def test_non_list_value_is_rewritten_to_empty_list(self, field):
        # Out-of-band write left a non-list under the key; __get__ should
        # rewrite and return [].
        doc = _make_doc(field=field, stored="not-a-list")
        result = field.__get__(doc, type(doc))
        assert result == []
        assert doc._data["refs"] == []

    def test_list_value_is_returned_unmodified(self, field):
        doc = _make_doc(field=field, stored=["a", "b", "c"])
        result = field.__get__(doc, type(doc))
        assert result == ["a", "b", "c"]


# -- Reference-pruning path ---------------------------------------------------


class _TruthyRef:
    """Stand-in for a resolved reference — always truthy."""

    def __init__(self, label):
        self.label = label

    def __bool__(self):
        return True


class _RaisesOnTruthy:
    """Stand-in for a stale reference whose access raises ``DoesNotExist``."""

    def __bool__(self):
        raise DoesNotExist


class TestListAttrReferencePruning:
    """The ``ReferenceAttr`` branch at ``autoattr.py:134-143``."""

    @pytest.fixture
    def field(self):
        f = ListAttr(ReferenceAttr())
        f.name = "refs"
        f.db_field = "refs"
        f.null = True
        f.default = list
        # ``self.field`` is the per-element field used in the isinstance
        # check at autoattr.py:134.
        return f

    def test_prunes_none_entries_in_place(self, field):
        # ``None`` represents a deleted referent (ReferenceAttr.__get__
        # returns None when the upstream raises DoesNotExist).
        a, b = _TruthyRef("a"), _TruthyRef("b")
        stored = [a, None, b, None]
        doc = _make_doc(field=field, stored=stored)
        result = field.__get__(doc, type(doc))
        assert result == [a, b]

    def test_prunes_entries_that_raise_doesnotexist_on_truthiness(self, field):
        # A stale reference whose access raises during the ``if not
        # results[i]`` check at autoattr.py:138 should be popped.
        a = _TruthyRef("a")
        stale = _RaisesOnTruthy()
        b = _TruthyRef("b")
        stored = [a, stale, b]
        doc = _make_doc(field=field, stored=stored)
        result = field.__get__(doc, type(doc))
        assert result == [a, b]

    def test_consecutive_falsy_entries_all_pruned(self, field):
        # The off-by-one risk: pop(i) without incrementing i so the
        # next-shifted element is also checked. Two adjacent Nones
        # must both disappear.
        a = _TruthyRef("a")
        doc = _make_doc(field=field, stored=[a, None, None])
        result = field.__get__(doc, type(doc))
        assert result == [a]
