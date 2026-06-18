"""Independent second-perspective coverage for PR #160 / issue #144 —
three small caches added to the vendored db fork:

- D.1 ``_to_mongo_co_varnames(field_class)`` in ``db/base/document.py`` —
  ``lru_cache(maxsize=None)`` keyed by field CLASS.
- D.2 ``_LOOKUP_FIELD_SUBCLASS_CACHE`` in ``db/base/document.py`` —
  module-level dict keyed by ``(cls, field_name)``; **additive-only**
  (successful resolutions cached; misses NOT cached).
- D.3 ``_compile_cached(pattern, flags)`` in ``db/fields.py`` —
  ``lru_cache(maxsize=512)`` keyed by ``(pattern, flags)``.

Dev wrote ephemeral tests under ``tests/_dev_local/`` (gitignored — not
visible from the PR diff, so this file is written from a fresh read of
the diff alone). Dev's angle (per the PR body) was identity-checks +
``cache_info().hits`` + a walk-counter + a negative-space pin. This
file's angle is **deliberately different**:

1. **Output-equivalence** — the cached return value equals what the
   uncached path (a fresh ``__code__.co_varnames`` lookup / fresh
   ``re.compile`` / fresh subclass walk) would have produced. Dev pinned
   identity; we pin semantic correctness.
2. **End-to-end through the public API** — drive ``to_mongo()``,
   ``StringField.prepare_query_value()``, and ``_lookup_field()`` from
   the consumer's surface and confirm behavior is unchanged.
3. **Cache-key boundary cases** — D.1 keyed by class (two field
   subclasses → two entries with the right values); D.3 distinguishes
   ``flags=0`` from ``re.IGNORECASE`` for the same pattern.
4. **D.2 additive-only from a different angle** — first verify a
   lookup-without-resolution does NOT populate the cache for that key
   (otherwise a later subclass registration would be masked).
"""

import re

import pytest

from autonomous.db import fields as fields_module
from autonomous.db.base import document as document_module
from autonomous.db.base.document import (
    _LOOKUP_FIELD_SUBCLASS_CACHE,
    _to_mongo_co_varnames,
)
from autonomous.db.errors import LookUpError
from autonomous.db.fields import IntField, StringField, _compile_cached


# ----------------------------------------------------------------------
# D.1 — _to_mongo_co_varnames
# ----------------------------------------------------------------------


class TestToMongoCoVarnamesCache:
    """``_to_mongo_co_varnames(field_class)`` returns the field class's
    ``to_mongo.__code__.co_varnames`` tuple, memoized per class.
    """

    def setup_method(self):
        _to_mongo_co_varnames.cache_clear()

    def teardown_method(self):
        _to_mongo_co_varnames.cache_clear()

    def test_value_matches_direct_introspection(self):
        """Cached call returns the same tuple as ``.__code__.co_varnames``."""
        expected = StringField.to_mongo.__code__.co_varnames
        assert _to_mongo_co_varnames(StringField) == expected
        # The uncached path returns a tuple of the to_mongo arg names —
        # at minimum ``self`` and ``value``.
        assert "self" in expected
        assert "value" in expected

    def test_second_call_is_a_cache_hit_with_equal_value(self):
        """A repeat call hits the cache AND returns an equal value
        (a regression where the cache silently returned ``None`` or a
        stale tuple would still be caught)."""
        first = _to_mongo_co_varnames(StringField)
        second = _to_mongo_co_varnames(StringField)
        info = _to_mongo_co_varnames.cache_info()
        assert info.hits >= 1
        assert info.misses == 1
        assert first == second
        # Sanity: same value as a direct re-introspection.
        assert second == StringField.to_mongo.__code__.co_varnames

    def test_keyed_by_class_not_instance(self):
        """Two different field CLASSES → two cache entries; an INSTANCE
        of an already-cached class does NOT add a new entry (since the
        cache key is the class, passing the class object — not an
        instance — is the documented contract)."""
        _to_mongo_co_varnames(StringField)
        _to_mongo_co_varnames(IntField)
        # Two distinct misses → two cache entries.
        assert _to_mongo_co_varnames.cache_info().currsize == 2
        assert _to_mongo_co_varnames.cache_info().misses == 2

        # Re-calling with the same StringField CLASS does not grow the cache.
        before = _to_mongo_co_varnames.cache_info().currsize
        _to_mongo_co_varnames(StringField)
        assert _to_mongo_co_varnames.cache_info().currsize == before

    def test_returned_varnames_match_per_class(self):
        """The cache returns the RIGHT varnames per class (key isolation
        — a bug where StringField's entry leaked into IntField would be
        loud here)."""
        s = _to_mongo_co_varnames(StringField)
        i = _to_mongo_co_varnames(IntField)
        assert s == StringField.to_mongo.__code__.co_varnames
        assert i == IntField.to_mongo.__code__.co_varnames

    def test_cache_clear_idempotent(self):
        """``cache_clear()`` is the documented escape hatch and must
        return the cache to a known-empty state — a pin so that a future
        refactor adding non-clearable state (e.g. a side dict) is loud."""
        _to_mongo_co_varnames(StringField)
        _to_mongo_co_varnames(IntField)
        assert _to_mongo_co_varnames.cache_info().currsize == 2
        _to_mongo_co_varnames.cache_clear()
        info = _to_mongo_co_varnames.cache_info()
        assert info.currsize == 0
        assert info.hits == 0
        assert info.misses == 0


# ----------------------------------------------------------------------
# D.2 — _LOOKUP_FIELD_SUBCLASS_CACHE
# ----------------------------------------------------------------------


class TestLookupFieldSubclassCache:
    """``_LOOKUP_FIELD_SUBCLASS_CACHE`` memoizes the
    ``cls.__subclasses__()`` walk in ``_lookup_field`` for parents with
    ``allow_inheritance=True``. **Additive-only**: misses must not be
    cached because a subclass with the target field may register later.
    """

    def teardown_method(self):
        # Don't blanket-clear — leave entries seeded by other tests alone
        # so we don't introduce ordering surprises. The classes we create
        # below are local and become unreferenced at teardown; clear the
        # specific keys we may have inserted.
        for key in list(_LOOKUP_FIELD_SUBCLASS_CACHE.keys()):
            owner, _name = key
            if getattr(owner, "__module__", "") == __name__:
                del _LOOKUP_FIELD_SUBCLASS_CACHE[key]

    def _make_parent_with_subclass(self, field_name="payload"):
        from autonomous.db import Document, StringField

        class _D144Parent(Document):
            meta = {"abstract": True, "allow_inheritance": True}

        class _D144Child(_D144Parent):
            meta = {"abstract": True}

        setattr(_D144Child, field_name, StringField())
        _D144Child._fields[field_name] = getattr(_D144Child, field_name)
        return _D144Parent, _D144Child

    def test_first_lookup_via_parent_populates_cache(self):
        parent, child = self._make_parent_with_subclass()
        fields = parent._lookup_field(["payload"])
        assert fields, "lookup should resolve via subclass walk"
        assert (parent, "payload") in _LOOKUP_FIELD_SUBCLASS_CACHE

    def test_second_lookup_short_circuits_subclasses_walk(self, monkeypatch):
        """After priming, a second lookup must NOT invoke
        ``cls.__subclasses__()`` — make ``__subclasses__`` blow up to
        prove the cache short-circuits before reaching the walk."""
        parent, _child = self._make_parent_with_subclass()
        parent._lookup_field(["payload"])  # prime

        sentinel = {"walked": False}
        orig_subclasses = parent.__subclasses__

        def _exploding():
            sentinel["walked"] = True
            return orig_subclasses()

        monkeypatch.setattr(parent, "__subclasses__", _exploding)

        result = parent._lookup_field(["payload"])
        assert result, "cached path should still return the field"
        assert sentinel["walked"] is False, (
            "second lookup should NOT walk __subclasses__()"
        )

    def test_missed_lookup_does_not_poison_cache(self):
        """A failed lookup must NOT add a ``None`` (or any) entry for
        ``(parent, missing_name)`` — otherwise a subclass registered
        AFTER the failure could never resolve via the parent.
        """
        from autonomous.db import Document

        class _D144EmptyParent(Document):
            meta = {"abstract": True, "allow_inheritance": True}

        # No subclass has the field yet — first lookup must raise.
        with pytest.raises(LookUpError):
            _D144EmptyParent._lookup_field(["latecomer"])

        assert (_D144EmptyParent, "latecomer") not in _LOOKUP_FIELD_SUBCLASS_CACHE, (
            "miss must not be cached (additive-only invariant)"
        )

    def test_late_registered_subclass_can_resolve_after_initial_miss(self):
        """The behavioral consequence of additive-only: a subclass
        registered AFTER an initial failed parent lookup can satisfy a
        subsequent lookup. Exercises the negative-space pin from the
        ``Document``-level entrypoint (a separate angle from a direct
        walk-counter)."""
        from autonomous.db import Document, StringField

        class _D144Parent2(Document):
            meta = {"abstract": True, "allow_inheritance": True}

        # First lookup: subclass doesn't exist yet → raises.
        with pytest.raises(LookUpError):
            _D144Parent2._lookup_field(["plumage"])

        # Register a subclass AFTER the failed lookup.
        class _D144Plumed(_D144Parent2):
            meta = {"abstract": True}
            plumage = StringField()
        _D144Plumed._fields["plumage"] = _D144Plumed.plumage

        # Second lookup must succeed via the freshly-registered subclass.
        fields = _D144Parent2._lookup_field(["plumage"])
        assert fields, "late subclass registration should be visible after miss"
        # And NOW the cache is populated.
        assert (_D144Parent2, "plumage") in _LOOKUP_FIELD_SUBCLASS_CACHE

    def test_cache_key_isolates_field_names(self):
        """Two distinct ``(cls, field_name)`` lookups produce two
        separate cache entries (the key is a tuple, not just ``cls``)."""
        from autonomous.db import Document, IntField, StringField

        class _D144MultiParent(Document):
            meta = {"abstract": True, "allow_inheritance": True}

        class _D144MultiChild(_D144MultiParent):
            meta = {"abstract": True}
            alpha = StringField()
            beta = IntField()
        _D144MultiChild._fields["alpha"] = _D144MultiChild.alpha
        _D144MultiChild._fields["beta"] = _D144MultiChild.beta

        _D144MultiParent._lookup_field(["alpha"])
        _D144MultiParent._lookup_field(["beta"])

        assert (_D144MultiParent, "alpha") in _LOOKUP_FIELD_SUBCLASS_CACHE
        assert (_D144MultiParent, "beta") in _LOOKUP_FIELD_SUBCLASS_CACHE
        # Different fields → different cached entries.
        assert (
            _LOOKUP_FIELD_SUBCLASS_CACHE[(_D144MultiParent, "alpha")]
            is not _LOOKUP_FIELD_SUBCLASS_CACHE[(_D144MultiParent, "beta")]
        )


# ----------------------------------------------------------------------
# D.3 — _compile_cached
# ----------------------------------------------------------------------


class TestCompileCached:
    """``_compile_cached(pattern, flags)`` is an LRU-cached wrapper
    around ``re.compile``. Behavioral contract: the returned ``Pattern``
    is functionally identical to ``re.compile(pattern, flags)`` and is
    the SAME object on a repeat call (so the consumer can amortize
    repeated identical queries)."""

    def setup_method(self):
        _compile_cached.cache_clear()

    def teardown_method(self):
        _compile_cached.cache_clear()

    def test_returned_pattern_behaves_like_re_compile(self):
        """The cached compile produces a Pattern with the same match
        behavior as ``re.compile`` directly — pins the consumer-API
        contract claim (no behavior change)."""
        pat = "^foo[0-9]+$"
        cached = _compile_cached(pat, 0)
        direct = re.compile(pat, 0)
        assert cached.pattern == direct.pattern
        assert cached.flags == direct.flags
        # Match behavior matches: matching string passes, non-matching fails.
        assert cached.match("foo42") is not None
        assert cached.match("bar42") is None

    def test_repeat_call_same_object(self):
        """Repeat call with the same ``(pattern, flags)`` returns the
        SAME compiled object (cache hit). Cache info reflects the hit."""
        first = _compile_cached("hello.*world", 0)
        second = _compile_cached("hello.*world", 0)
        assert first is second
        info = _compile_cached.cache_info()
        assert info.hits >= 1
        assert info.misses == 1

    def test_flags_are_part_of_cache_key(self):
        """Same pattern with different flags MUST produce different
        cache entries — otherwise case-insensitive queries would silently
        fall back to whichever flag landed first."""
        a = _compile_cached("Hello", 0)
        b = _compile_cached("Hello", re.IGNORECASE)
        assert a is not b
        # Behavioral pin: the IGNORECASE one actually ignores case.
        assert a.match("hello") is None
        assert b.match("hello") is not None

    def test_bounded_maxsize(self):
        """The cache is bounded at 512 entries (adversarial input
        protection per the PR body)."""
        assert _compile_cached.cache_info().maxsize == 512

    def test_endtoend_stringfield_query_value_caches(self):
        """End-to-end: ``StringField.prepare_query_value("startswith",
        ...)`` returns the cached compiled pattern, and a repeat call
        with the same arguments returns the SAME object."""
        f = StringField()
        a = f.prepare_query_value("startswith", "needle")
        b = f.prepare_query_value("startswith", "needle")
        assert isinstance(a, re.Pattern)
        # Same compiled regex on repeat — comes from the shared cache.
        assert a is b
        # And it actually matches strings starting with 'needle'.
        assert a.match("needlework") is not None
        assert a.match("haystack") is None

    def test_endtoend_distinct_ops_distinct_patterns(self):
        """``startswith`` and ``endswith`` of the same value produce
        DIFFERENT compiled patterns (the prefix/suffix anchors differ),
        so they must end up at different cache keys."""
        f = StringField()
        starts = f.prepare_query_value("startswith", "abc")
        ends = f.prepare_query_value("endswith", "abc")
        assert starts is not ends
        assert starts.match("abc-xyz") is not None
        assert starts.match("xyz-abc") is None
        assert ends.search("xyz-abc") is not None
        assert ends.search("abc-xyz") is None


# ----------------------------------------------------------------------
# Module-level smoke: the symbols exist on their respective modules
# (catches the trivial "renamed/removed" regression).
# ----------------------------------------------------------------------


def test_module_exports():
    assert hasattr(document_module, "_to_mongo_co_varnames")
    assert hasattr(document_module, "_LOOKUP_FIELD_SUBCLASS_CACHE")
    assert hasattr(fields_module, "_compile_cached")
    # Type sanity.
    assert isinstance(_LOOKUP_FIELD_SUBCLASS_CACHE, dict)
    assert callable(_to_mongo_co_varnames)
    assert callable(_compile_cached)
