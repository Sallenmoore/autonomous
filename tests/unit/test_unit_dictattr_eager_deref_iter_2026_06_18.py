"""Pinning tests for ``DictAttr.__get__`` eager-deref behavior (TEST-4 in #141).

Documents the contract in ``src/autonomous/db/DIVERGENCE.md`` §`DictAttr`:

- Values with a ``.fetch()`` method AND a truthy ``.pk`` are eagerly
  dereferenced (the lazy ``GenericReferenceField`` proxy is replaced
  by the resolved Document).
- Values whose ``.fetch()`` raises ``DoesNotExist`` are **left in
  place** with a log line — asymmetric with ``ListAttr`` (which prunes).
  Keys are usually meaningful in dicts so the placeholder stays.
- Values without ``.fetch()`` are returned unchanged.
- Missing / ``None`` stored value becomes an empty dict.
"""

from unittest.mock import patch

import pytest

from autonomous.db import DoesNotExist
from autonomous.model.autoattr import DictAttr


def _make_doc(stored, field):
    """Stub document for DictAttr.__get__ tests.

    ``field`` is forwarded into ``_fields`` so ``BaseField.__get__`` can
    read ``instance._fields[self.name]._auto_dereference`` per the
    upstream mongoengine descriptor protocol.
    """
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


class _LazyRef:
    """Stub for a lazy reference: has ``.fetch()`` and ``.pk``."""

    def __init__(self, pk, resolved):
        self.pk = pk
        self._resolved = resolved

    def fetch(self):
        return self._resolved


class _MissingRef:
    """Stub for a stale reference whose ``.fetch()`` raises ``DoesNotExist``."""

    pk = "stale-pk"

    def fetch(self):
        raise DoesNotExist


@pytest.fixture
def field():
    f = DictAttr()
    f.name = "props"
    f.db_field = "props"
    f.null = True
    f.default = dict
    return f


class TestDictAttrEagerDeref:
    """Pins ``DictAttr.__get__`` behavior at ``autoattr.py:169-180``."""

    def test_lazy_value_with_pk_is_dereferenced(self, field):
        resolved = object()
        lazy = _LazyRef(pk="x", resolved=resolved)
        doc = _make_doc(field=field, stored={"key": lazy})

        result = field.__get__(doc, type(doc))

        assert result["key"] is resolved

    def test_plain_value_is_returned_unchanged(self, field):
        doc = _make_doc(field=field, stored={"key": "plain-string-value"})

        result = field.__get__(doc, type(doc))

        assert result["key"] == "plain-string-value"

    def test_doesnotexist_leaves_placeholder_in_place(self, field):
        # Asymmetric with ListAttr: dict keys are meaningful, so the
        # placeholder survives and the missing referent is logged.
        stale = _MissingRef()
        doc = _make_doc(field=field, stored={"key": stale})

        with patch("autonomous.model.autoattr.log") as mock_log:
            result = field.__get__(doc, type(doc))

        # Key still present with the original placeholder.
        assert "key" in result
        assert result["key"] is stale
        # Log fired so prod-watch / debugging can see the miss.
        mock_log.assert_called()

    def test_none_stored_becomes_empty_dict(self, field):
        # The ``or {}`` at autoattr.py:170 covers a None stored value.
        doc = _make_doc(field=field, stored=None)

        result = field.__get__(doc, type(doc))

        assert result == {}

    def test_lazy_value_without_pk_is_left_unchanged(self, field):
        # ``lazy_obj.pk`` is the gate for the ``.fetch()`` call at
        # autoattr.py:175 (``if lazy_obj and lazy_obj.pk``). When ``pk``
        # is falsy the placeholder stays as-is.
        no_pk = _LazyRef(pk=None, resolved=object())
        doc = _make_doc(field=field, stored={"key": no_pk})

        result = field.__get__(doc, type(doc))

        assert result["key"] is no_pk
