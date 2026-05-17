"""Tests for the iter/2026-05-17 guest-cache batch (PR #96).

Independent test-agent coverage for issue #95 — ``User.get_guest()``
was performing an uncached MongoDB ``find`` on every unauthenticated
request, causing CSOT cancellation under load in storyteller.

PR #96 ships four mechanisms in defense-in-depth layers:

1. **Index on ``AutoUser.name``** — makes the find cheap even
   on a cache miss.
2. **Class-level ``_cached_guest`` slot** — eliminates the find
   after the first call (the guest doc is effectively immutable).
3. **``_invalidate_guest_cache()`` classmethod** — admin/test
   escape hatch.
4. **``auto_post_save`` hook** — defensive: drops the cache if
   any code path saves the guest doc, so the cache can never drift
   from Mongo state.

This file pins each mechanism independently. Tests use the
unbound-classmethod-with-stub pattern (``cls.method.__func__(stub)``)
so each test can substitute a minimal ``cls`` and isolate behavior
without touching real MongoDB.
"""

import pytest

from autonomous.auth.user import AutoUser, User


# ===========================================================================
# Mechanism 1: index on AutoUser.name
# ===========================================================================


class TestAutoUserNameIndex:
    """Pin the meta-level index declaration."""

    def test_meta_declares_name_index(self):
        # Defense layer 1: even on a cache miss, the find must hit
        # an index. Without this, the fallback to Mongo is O(N)
        # over the user collection — exactly the CSOT-under-load
        # symptom #95 described, with caching only delaying it
        # until the next process restart.
        # MongoEngine metaclass consumes the author-provided `meta`
        # dict into the resolved `_meta` namespace. The resolved
        # form is what the ODM actually queries with.
        indexes = AutoUser._meta.get("indexes", [])
        assert "name" in indexes, (
            f"AutoUser._meta['indexes'] must include 'name' per #95; "
            f"got: {indexes}"
        )

    def test_concrete_subclass_inherits_index(self):
        # The vendored MetaDict (db/base/metaclasses.py) merges
        # `indexes` from abstract base into concrete subclasses.
        # Pin User (the project-extendable concrete subclass) sees
        # the index too — if MetaDict merge ever regresses, the
        # AutoUser-level declaration would be silently ineffective
        # for the actual production code path.
        merged = User._meta.get("indexes", [])
        # MongoEngine resolves string indexes into one of two forms
        # depending on ODM version:
        #  - kept as bare strings: ["name", ...]
        #  - lifted to spec dicts: [{"fields": ["name"]}, ...]
        # Walk both shapes and pin EXACT field-name match (not
        # substring — "name" would otherwise also match "filename"
        # or any other index referencing a name-suffixed field).
        def _index_targets_name(spec):
            if isinstance(spec, str):
                # Bare-string form. May be prefixed by "+"/"-" for
                # direction; strip and compare on field-name.
                return spec.lstrip("+-") == "name"
            if isinstance(spec, dict):
                fields = spec.get("fields", [])
                return any(
                    (isinstance(f, str) and f.lstrip("+-") == "name")
                    or (isinstance(f, (list, tuple)) and "name" in f)
                    for f in fields
                )
            return False

        assert any(_index_targets_name(s) for s in merged), (
            f"User (concrete subclass) should inherit an index "
            f"targeting field 'name' from AutoUser; merged spec: "
            f"{merged!r}"
        )


# ===========================================================================
# Mechanism 2: class-level _cached_guest slot
# ===========================================================================


class TestGuestCacheHitReturnsWithoutFind:
    """Pin the cache-hit fast path."""

    def test_cached_guest_slot_declared_on_autouser(self):
        # Pre-#96 the slot didn't exist at all. Pin the EXISTENCE of
        # `_cached_guest` on AutoUser's class dict — checking it's
        # `None`-valued via `dict.get(K, None)` would be a tautology
        # (returns None when K is absent). The presence check is
        # what actually distinguishes pre-#96 from post-#96.
        assert "_cached_guest" in AutoUser.__dict__, (
            "AutoUser must declare `_cached_guest = None` as a "
            "class-level slot per #96 — without the declaration "
            "the cache lives only on whichever subclass first "
            "assigns to it, breaking the per-subclass isolation "
            "promise in the docstring."
        )
        assert AutoUser.__dict__["_cached_guest"] is None, (
            f"Initial slot value must be None (signals empty "
            f"cache); got: {AutoUser.__dict__['_cached_guest']!r}"
        )

    def test_cache_hit_returns_without_calling_find(self):
        # Cache hit must NOT call find — that's the entire point
        # of #96 (eliminate the per-request round-trip). Pin via
        # call count on a stub `find`.
        find_calls = []

        class _Stub:
            _cached_guest = "preexisting_guest_sentinel"

            @classmethod
            def find(cls, **kw):
                find_calls.append(kw)
                return None

        result = AutoUser.get_guest.__func__(_Stub)
        assert result == "preexisting_guest_sentinel"
        assert find_calls == [], (
            f"Cache hit must skip find entirely; got calls: "
            f"{find_calls}"
        )

    def test_cache_miss_calls_find_then_caches(self):
        # First miss: find returns an existing doc → cache it AND
        # return it. Pin BOTH the return value and the cache write.
        find_calls = []
        existing = object()

        class _Stub:
            _cached_guest = None

            @classmethod
            def find(cls, **kw):
                find_calls.append(kw)
                return existing

        result = AutoUser.get_guest.__func__(_Stub)
        assert result is existing
        assert _Stub._cached_guest is existing, (
            "After cache miss, _cached_guest must be set to the "
            "find result so subsequent calls hit cache"
        )
        assert find_calls == [{"name": "_GuestOfAutonomous_"}]

    def test_cache_miss_no_existing_doc_bootstraps_and_caches(self):
        # First miss + no existing guest in Mongo: must instantiate,
        # save, AND cache the new doc. The bootstrap path was the
        # original code; the caching is the #96 addition.
        find_calls = []
        save_calls = []

        class _BootstrapStub:
            _cached_guest = None
            _init_kwargs = None

            @classmethod
            def find(cls, **kw):
                find_calls.append(kw)
                return None

            def __init__(self, **kw):
                type(self)._init_kwargs = kw

            def save(self):
                save_calls.append(self)

        result = AutoUser.get_guest.__func__(_BootstrapStub)
        assert isinstance(result, _BootstrapStub)
        assert result is _BootstrapStub._cached_guest, (
            "Bootstrap-path doc must be cached on the class"
        )
        assert save_calls == [result], (
            "Bootstrap path must save the new doc"
        )
        # Constructor kwargs pin the guest contract (name, email,
        # state, role). A regression that changed the guest's email
        # or role would be caught here.
        assert _BootstrapStub._init_kwargs == {
            "name": "_GuestOfAutonomous_",
            "email": "guest@mail.com",
            "state": "guest",
            "role": "guest",
        }


# ===========================================================================
# Mechanism 3: _invalidate_guest_cache classmethod
# ===========================================================================


class TestInvalidateGuestCache:
    """Pin the escape hatch."""

    def test_invalidate_drops_cache(self):
        class _Stub:
            _cached_guest = "stale_sentinel"

        AutoUser._invalidate_guest_cache.__func__(_Stub)
        assert _Stub._cached_guest is None, (
            "_invalidate_guest_cache must reset slot to None"
        )

    def test_invalidate_is_idempotent(self):
        # Calling on an already-None cache must not raise.
        class _Stub:
            _cached_guest = None

        AutoUser._invalidate_guest_cache.__func__(_Stub)
        AutoUser._invalidate_guest_cache.__func__(_Stub)
        assert _Stub._cached_guest is None

    def test_invalidate_then_get_refreshes(self):
        # End-to-end: invalidate triggers next get to re-find.
        find_calls = []

        class _Stub:
            _cached_guest = "old_doc"

            @classmethod
            def find(cls, **kw):
                find_calls.append(kw)
                return "fresh_doc"

        # Hit cache first.
        assert AutoUser.get_guest.__func__(_Stub) == "old_doc"
        assert find_calls == []
        # Invalidate then re-fetch.
        AutoUser._invalidate_guest_cache.__func__(_Stub)
        assert AutoUser.get_guest.__func__(_Stub) == "fresh_doc"
        assert find_calls == [{"name": "_GuestOfAutonomous_"}]


# ===========================================================================
# Mechanism 4: auto_post_save hook
# ===========================================================================


class TestAutoPostSaveInvalidatesOnGuestSave:
    """Pin the defensive cache invalidation."""

    def _doc_with_name(self, name):
        # Build a minimal stand-in for a saved document with a
        # `.name` attribute — that's all the hook reaches.
        return type("_DocStub", (), {"name": name})()

    def test_guest_doc_save_drops_cache(self):
        # The substance of #96's defensive layer: if anyone saves
        # the guest doc (initial bootstrap, admin tooling, migrations),
        # the cache must drop so the next get_guest reloads.
        class _Stub:
            _cached_guest = "cached_guest_sentinel"

        AutoUser.auto_post_save.__func__(
            _Stub,
            sender=None,
            document=self._doc_with_name("_GuestOfAutonomous_"),
        )
        assert _Stub._cached_guest is None, (
            "auto_post_save must invalidate cache when document.name "
            "is the guest sentinel"
        )

    def test_non_guest_doc_save_preserves_cache(self):
        # Critical asymmetry: saving Alice's account must NOT touch
        # the guest cache. Pre-#96 there was no cache so this was
        # a non-issue; post-#96 a regression that drops the
        # `if name == sentinel` check would invalidate on every
        # save and defeat the entire point of caching.
        class _Stub:
            _cached_guest = "cached_guest_sentinel"

        AutoUser.auto_post_save.__func__(
            _Stub,
            sender=None,
            document=self._doc_with_name("Alice"),
        )
        assert _Stub._cached_guest == "cached_guest_sentinel", (
            "auto_post_save MUST NOT invalidate cache for non-guest "
            "saves — that would defeat the caching purpose"
        )

    def test_document_without_name_attribute_is_safe(self):
        # `getattr(document, "name", None)` defensive pattern — must
        # not AttributeError on weird document types (e.g. during
        # signal-firing on partially-constructed docs).
        class _Stub:
            _cached_guest = "cached_guest_sentinel"

        # Empty object with no `name` attr at all.
        AutoUser.auto_post_save.__func__(
            _Stub,
            sender=None,
            document=object(),
        )
        # Cache must NOT be dropped (None != sentinel string).
        assert _Stub._cached_guest == "cached_guest_sentinel"

    def test_document_with_none_name_is_safe(self):
        # `document.name = None` (a freshly-instantiated AutoUser
        # before defaults fire) → getattr returns None → comparison
        # vs sentinel string is False → no invalidation. Pin so
        # nobody accidentally rewrites the comparison as
        # `if name in ("_GuestOfAutonomous_", None)`.
        class _Stub:
            _cached_guest = "cached_guest_sentinel"

        AutoUser.auto_post_save.__func__(
            _Stub,
            sender=None,
            document=self._doc_with_name(None),
        )
        assert _Stub._cached_guest == "cached_guest_sentinel"


# ===========================================================================
# Subclass cache-isolation invariant
# ===========================================================================


class TestPerSubclassCacheIsolation:
    """Pin the docstring's "each AutoUser subclass keeps its own cache" claim.

    `_cached_guest` lives on the class. The source-code comment
    explicitly notes the assignment happens on `cls` (the concrete
    subclass), not `AutoUser`. This means a project with two
    AutoUser subclasses (e.g. `AdminUser` and `User`) gets two
    independent caches — important if their respective guest docs
    diverge (different defaults, different roles).
    """

    def test_get_guest_caches_on_passed_cls_not_autouser(self):
        # The source comment says "Set on the concrete subclass
        # (not AutoUser) so each AutoUser subclass keeps its own
        # cache." Pin this by calling get_guest with a stub `cls`
        # and verifying the assignment lands on the stub, NOT on
        # AutoUser's class dict. A regression that hardcoded
        # `AutoUser._cached_guest = guest` (instead of
        # `cls._cached_guest = guest`) would break per-subclass
        # isolation — pin that the actual assignment target is
        # the passed `cls`.
        autouser_slot_before = AutoUser.__dict__.get("_cached_guest")
        sentinel = object()

        class _Stub:
            _cached_guest = None

            @classmethod
            def find(cls, **kw):
                return sentinel

        result = AutoUser.get_guest.__func__(_Stub)
        assert result is sentinel
        # Assignment landed on _Stub.
        assert _Stub._cached_guest is sentinel
        # AutoUser's class-dict slot UNCHANGED (otherwise the
        # source did `AutoUser._cached_guest = ...` instead of
        # `cls._cached_guest = ...`).
        assert AutoUser.__dict__.get("_cached_guest") is (
            autouser_slot_before
        ), (
            "get_guest must assign to `cls._cached_guest`, not "
            "`AutoUser._cached_guest`. If AutoUser's slot changed, "
            "the source is bypassing per-subclass cache isolation."
        )

    def test_invalidate_on_subclass_does_not_affect_other_subclass(self):
        class _SubA:
            _cached_guest = "sub_a_cache"

        class _SubB:
            _cached_guest = "sub_b_cache"

        AutoUser._invalidate_guest_cache.__func__(_SubA)
        assert _SubA._cached_guest is None
        assert _SubB._cached_guest == "sub_b_cache", (
            "Invalidating SubA's cache must NOT touch SubB"
        )
