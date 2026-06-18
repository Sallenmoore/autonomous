"""Pinning tests for ``ListAttr.__set__`` string→list splitting (TEST-2 in #141).

Documents the contract in ``src/autonomous/db/DIVERGENCE.md`` §`ListAttr.__set__`:

- Semicolon precedence: ``"a;b,c"`` splits on ``;`` only → ``["a", "b,c"]``.
- Comma fallback with ``.strip()``: ``"x, y, z"`` → ``["x", "y", "z"]``.
- Single non-empty string → one-element list.
- Empty string → empty list.
- Non-string inputs pass through to ``ListField.__set__`` unchanged.

Hermetic — uses the ``_make_doc`` stub pattern from
``test_unit_referenceattr_dirty.py``.
"""

import pytest

from autonomous.model.autoattr import ListAttr, StringAttr


def _make_doc():
    class _Stub:
        _initialised = True
        _created = False
        _dynamic_fields = {}
        _db_field_map = {"tags": "tags"}
        _data = {"tags": None}
        _changed_fields: list[str] = []

        def _mark_as_changed(self, key):
            key = self._db_field_map.get(key, key)
            if key not in self._changed_fields:
                self._changed_fields.append(key)

    return _Stub()


@pytest.fixture
def field():
    f = ListAttr(StringAttr())
    f.name = "tags"
    f.db_field = "tags"
    f.null = True
    f.default = list
    return f


class TestListAttrStringSplit:
    """Pins ``ListAttr.__set__`` behavior at ``autoattr.py:146-157``."""

    def test_semicolon_splits_into_trimmed_list(self, field):
        doc = _make_doc()
        field.__set__(doc, "a;b;c")
        assert doc._data["tags"] == ["a", "b", "c"]

    def test_semicolon_strips_whitespace(self, field):
        doc = _make_doc()
        field.__set__(doc, "a ; b ; c")
        assert doc._data["tags"] == ["a", "b", "c"]

    def test_comma_splits_into_trimmed_list(self, field):
        doc = _make_doc()
        field.__set__(doc, "x, y, z")
        assert doc._data["tags"] == ["x", "y", "z"]

    def test_semicolon_precedence_over_comma(self, field):
        # Documented precedence: ``;`` wins when both are present;
        # comma stays embedded in the resulting element.
        doc = _make_doc()
        field.__set__(doc, "a;b,c")
        assert doc._data["tags"] == ["a", "b,c"]

    def test_empty_string_becomes_empty_list(self, field):
        doc = _make_doc()
        field.__set__(doc, "")
        assert doc._data["tags"] == []

    def test_single_non_empty_string_becomes_one_element_list(self, field):
        doc = _make_doc()
        field.__set__(doc, "solo")
        assert doc._data["tags"] == ["solo"]

    def test_already_a_list_passes_through(self, field):
        # Non-string input bypasses the split ladder entirely.
        doc = _make_doc()
        field.__set__(doc, ["x", "y"])
        assert doc._data["tags"] == ["x", "y"]
