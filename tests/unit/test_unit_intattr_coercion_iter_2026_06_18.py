"""Pinning tests for ``IntAttr.__set__`` string-coercion ladder (TEST-1 in #141).

Documents the contract in ``src/autonomous/db/DIVERGENCE.md`` §`IntAttr`:

- Comma-strip on numeric strings (``"1,234"`` → ``1234``).
- Regex-substring fallback for non-numeric input (``"$42.50"`` → ``42``).
- Pass-through to ``IntField.__set__`` when no integer substring is found
  (``"no-digits-here"`` is stored verbatim — non-obvious and surprising).
- Plain ``int`` / ``None`` reaches the parent untouched.

Hermetic — uses the ``_make_doc`` stub pattern from
``test_unit_referenceattr_dirty.py``. No Mongo connection needed.
"""

import pytest

from autonomous.model.autoattr import IntAttr


def _make_doc():
    """Minimal document stub. Mirrors the pattern from
    ``test_unit_referenceattr_dirty.py:_make_doc``."""

    class _Stub:
        _initialised = True
        _created = False
        _dynamic_fields = {}
        _db_field_map = {"count": "count"}
        _data = {"count": None}
        _changed_fields: list[str] = []

        def _mark_as_changed(self, key):
            key = self._db_field_map.get(key, key)
            if key not in self._changed_fields:
                self._changed_fields.append(key)

    return _Stub()


@pytest.fixture
def field():
    f = IntAttr()
    f.name = "count"
    f.db_field = "count"
    f.null = True
    f.default = None
    return f


class TestIntAttrCoercion:
    """Pins ``IntAttr.__set__`` behavior at ``autoattr.py:46-53``."""

    def test_strip_single_comma_in_numeric_string(self, field):
        doc = _make_doc()
        field.__set__(doc, "1,234")
        assert doc._data["count"] == 1234

    def test_strip_multiple_commas(self, field):
        doc = _make_doc()
        field.__set__(doc, "1,234,567")
        assert doc._data["count"] == 1234567

    def test_extract_first_int_from_currency_string(self, field):
        # ``"$42.50"`` doesn't survive ``isdigit()`` after comma-strip,
        # so the regex substring fallback fires and matches "42".
        doc = _make_doc()
        field.__set__(doc, "$42.50")
        assert doc._data["count"] == 42

    def test_extract_negative_int(self, field):
        # The regex is ``r"-?\d+"`` so a leading minus is preserved.
        doc = _make_doc()
        field.__set__(doc, "-5")
        assert doc._data["count"] == -5

    def test_extract_first_int_from_mixed_alphanumeric(self, field):
        # ``"1.5k"`` after comma-strip is not ``isdigit()``; the regex
        # finds the first ``\d+`` substring — ``"1"`` — and stops.
        doc = _make_doc()
        field.__set__(doc, "1.5k")
        assert doc._data["count"] == 1

    def test_no_digits_in_string_passes_through_unchanged(self, field):
        # Critical pass-through case: regex finds no match, value is
        # forwarded to ``IntField.__set__`` verbatim. Documents the
        # silent fall-through path in DIVERGENCE.md.
        doc = _make_doc()
        field.__set__(doc, "no-digits-here")
        assert doc._data["count"] == "no-digits-here"

    def test_plain_int_is_untouched(self, field):
        doc = _make_doc()
        field.__set__(doc, 42)
        assert doc._data["count"] == 42

    def test_none_is_untouched(self, field):
        doc = _make_doc()
        field.__set__(doc, None)
        assert doc._data["count"] is None
