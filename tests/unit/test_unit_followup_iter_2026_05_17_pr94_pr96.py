"""Tests for the iter/2026-05-17-pr94-pr96-followups batch (PR #103).

Independent test-agent coverage for the 4-issue follow-up bundle that
addresses /review-pr findings on the prior cycle's PRs #94 + #96:

- **#97** — ``auto_post_save`` adds isinstance gate + invokes
  ``AutoUser._invalidate_guest_cache()`` (walks the WHOLE AutoUser
  tree), and ``_invalidate_guest_cache`` itself recurses into
  ``__subclasses__()``.
- **#98** — ``get_guest()`` bootstrap branch flips from
  ``if not guest:`` to ``if guest is None:``.
- **#99** — ``openai_compat`` carve-out adds ``SSLError`` and
  ``ProxyError``; ``ContentDecodingError`` is *deliberately* excluded.
- **#100** — ``gemini._add_files`` adds a per-value shape check so
  asymmetric typos (``{"name": "alice.webp", "metadata": fobj}``) are
  rejected with a typed error rather than silently uploading garbage.

The dev PR (#103) includes substantial lockstep edits across three
existing iter test files. From a fresh perspective, those lockstep
edits adequately cover the primary positive/negative shapes (per-type
parametrize for #99, sibling+deep-chain subclass for #97,
empty-list-doesn't-bootstrap for #98, string/int/bytes/file-like for
#100). This file pins ORTHOGONAL surfaces the lockstep tests leave
exposed:

- #97 design-decision pin: ``auto_post_save`` calls
  ``AutoUser._invalidate_guest_cache`` *specifically* — NOT
  ``cls._invalidate_guest_cache`` (a regression to the latter
  would still pass dev's two-sibling cross-walk test for the
  dispatching class but silently skip cousin subtrees).
- #97 second-gate pin: isinstance-match + name-mismatch must be a
  no-op (dev pins isinstance-mismatch but not the name gate).
- #98 generic falsy-non-None: an object whose ``__bool__`` returns
  False but is not None must NOT trigger bootstrap (dev pins
  empty-list; this proves the ``is None`` check is shape-generic,
  not list-specific).
- #99 positive ContentDecodingError translation: dev pins the
  source-text exclusion; this pins the *behavioral* outcome
  (ContentDecodingError still becomes HPCUnreachableError, proving
  the deliberate exclusion is live, not aspirational).
- #99 SSLError single-attempt: SSLError raises raw from
  ``_attempt`` and propagates BEFORE the ``retry()`` loop fires
  again — pinned by ``_attempt`` call-count.
- #100 operator-UX pin: the error message must include the
  offending KEY name (so the caller can find their typo).
- #100 path-isolation pin: the list-of-dicts path is *unaffected*
  by the new value-shape guard (only the dict-shape path runs it).
- #100 precedence pin: the both-keys guard fires BEFORE the
  value-shape guard for ``{"name": <str>, "file": <str>}``.
"""

import io
import time
from unittest.mock import patch

import pytest
import requests


# ===========================================================================
# #97 — auto_post_save invokes AutoUser._invalidate_guest_cache specifically
# ===========================================================================


class TestAutoPostSaveInvalidatorTarget:
    """Pin the implementation choice from #97 design-decision #2: the
    invalidation call inside ``auto_post_save`` targets ``AutoUser``
    explicitly, not the dispatching ``cls``.

    Issue #97's *suggested* fix was ``cls._invalidate_guest_cache()``
    (walk only ``cls``'s descendants). The merged fix went with
    ``AutoUser._invalidate_guest_cache()`` (walk the entire AutoUser
    tree) because saving via ``AdminUser`` must also drop ``User``'s
    cache — sibling subclasses share the same Mongo guest doc. A
    future refactor that reverts to ``cls.*`` would still pass dev's
    sibling-subclass walk test (because the test's saved doc IS a
    descendant of the dispatching cls), but it would silently break
    the cousin-subtree case. This pin discriminates the two.
    """

    def test_invokes_via_AutoUser_explicit_not_via_cls(self):
        from autonomous.auth.user import AutoUser

        class _SubA(AutoUser):
            meta = {"abstract": True, "allow_inheritance": True}

        try:
            # Patch BOTH the AutoUser entry and the per-subclass entry.
            # If the source calls AutoUser._invalidate_guest_cache(),
            # only the AutoUser mock fires. If it called
            # cls._invalidate_guest_cache(), MRO lookup on _SubA would
            # hit _SubA's create=True entry and the _SubA mock would
            # fire. The two mocks are distinct objects so this is a
            # clean discriminator.
            with patch.object(AutoUser, "_invalidate_guest_cache") as au_m, \
                 patch.object(_SubA, "_invalidate_guest_cache", create=True) as sub_m:
                doc = _SubA()
                doc.name = "_GuestOfAutonomous_"
                AutoUser.auto_post_save.__func__(
                    _SubA, sender=_SubA, document=doc,
                )

                assert au_m.call_count == 1, (
                    f"auto_post_save must call "
                    f"AutoUser._invalidate_guest_cache exactly once "
                    f"(per design decision #2 — walk the whole "
                    f"AutoUser tree, not just cls's descendants). "
                    f"Got: AutoUser calls={au_m.call_count}, "
                    f"_SubA calls={sub_m.call_count}"
                )
                assert sub_m.call_count == 0, (
                    "auto_post_save must NOT call "
                    "cls._invalidate_guest_cache (would skip cousin "
                    "subtrees that share the same Mongo guest doc)"
                )
        finally:
            AutoUser._cached_guest = None


# ===========================================================================
# #97 — second gate: name-mismatch with isinstance-match must be no-op
# ===========================================================================


class TestAutoPostSaveNameGate:
    """Pin the second guard in ``auto_post_save``: even when the
    document IS an instance of ``cls`` (passes the new isinstance
    gate from #97), a name other than ``_GuestOfAutonomous_`` must
    short-circuit *before* the invalidator runs.

    Dev's cross-subclass tests fire only with the guest name, so they
    don't distinguish "name-mismatch returns early" from "name-match
    fires invalidator". Pinning the negative case here ensures a
    future edit that drops the name check (e.g. accidentally
    invalidating on EVERY save of an AutoUser doc) is caught.
    """

    def test_name_mismatch_isinstance_match_does_not_invalidate(self):
        from autonomous.auth.user import AutoUser

        class _SubB(AutoUser):
            meta = {"abstract": True, "allow_inheritance": True}

        try:
            with patch.object(AutoUser, "_invalidate_guest_cache") as au_m:
                # Doc IS an instance of _SubB (passes isinstance gate)
                # but has the WRONG name. Must be a no-op.
                doc = _SubB()
                doc.name = "alice@example.com"
                AutoUser.auto_post_save.__func__(
                    _SubB, sender=_SubB, document=doc,
                )

                assert au_m.call_count == 0, (
                    "name != '_GuestOfAutonomous_' must short-circuit "
                    "before invalidator. A future edit that drops "
                    "the name guard would invalidate the cache on "
                    "every authenticated-user save, defeating #96's "
                    "whole purpose."
                )
        finally:
            AutoUser._cached_guest = None

    def test_missing_name_attribute_does_not_invalidate(self):
        # `getattr(document, "name", None)` defaults to None on
        # missing attr — must compare unequal to the guest sentinel
        # and short-circuit. Pin against a future refactor that
        # drops the getattr default (would raise AttributeError on
        # docs without `.name`, polluting traceback noise).
        from autonomous.auth.user import AutoUser

        class _SubC(AutoUser):
            meta = {"abstract": True, "allow_inheritance": True}

        class _DocNoName(_SubC):
            meta = {"abstract": True, "allow_inheritance": True}
            # explicitly no `.name` attribute on the instance level

        try:
            with patch.object(AutoUser, "_invalidate_guest_cache") as au_m:
                doc = object.__new__(_DocNoName)  # skip __init__
                AutoUser.auto_post_save.__func__(
                    _SubC, sender=_SubC, document=doc,
                )
                # Either short-circuits on isinstance (doc is _DocNoName,
                # which IS a _SubC subclass so isinstance passes) or
                # short-circuits on name. Either way: no invalidate.
                assert au_m.call_count == 0
        finally:
            AutoUser._cached_guest = None


# ===========================================================================
# #97 — _invalidate_guest_cache walks descendants directly (no signal needed)
# ===========================================================================


class TestInvalidateGuestCacheWalksDescendants:
    """Pin the public helper ``_invalidate_guest_cache`` independently
    of ``auto_post_save``. Tests/admin tooling can call this helper
    directly (per its docstring) and must get the full subtree walk.

    Dev's tests reach the walk THROUGH ``auto_post_save``; this pins
    the walk via the public entry point so a refactor that moves the
    walk logic INTO ``auto_post_save`` (leaving the helper as a
    single-class clear) would be caught.
    """

    def test_invalidate_clears_self_and_descendants(self):
        from autonomous.auth.user import AutoUser

        class _Root(AutoUser):
            meta = {"abstract": True, "allow_inheritance": True}

        class _Child(_Root):
            meta = {"abstract": True, "allow_inheritance": True}

        class _Grandchild(_Child):
            meta = {"abstract": True, "allow_inheritance": True}

        try:
            _Root._cached_guest = "root_cache"
            _Child._cached_guest = "child_cache"
            _Grandchild._cached_guest = "grand_cache"

            _Root._invalidate_guest_cache()

            assert _Root._cached_guest is None, "root must be cleared"
            assert _Child._cached_guest is None, "child must be cleared"
            assert _Grandchild._cached_guest is None, (
                "grandchild must be cleared (recursive walk, not "
                "single-level)"
            )
        finally:
            _Root._cached_guest = None
            _Child._cached_guest = None
            _Grandchild._cached_guest = None


# ===========================================================================
# #98 — generic falsy-non-None doesn't bootstrap
# ===========================================================================


class TestGetGuestIsNoneShapeGeneric:
    """Pin that ``if guest is None`` is shape-generic, not just
    empty-list-aware.

    Dev's lockstep test pins empty-list-doesn't-bootstrap. This pin
    uses a custom object whose ``__bool__`` returns False but which
    is NOT None — proves the post-#98 check rejects ALL falsy
    non-None values, not just iterables that happen to be empty.
    A regression to ``if not guest:`` would bootstrap on this object
    and produce a duplicate.
    """

    def test_falsy_custom_object_does_not_bootstrap(self):
        from autonomous.auth.user import AutoUser

        class _FalsyDoc:
            """Looks like a doc, but bool(self) is False."""

            pk = "existing_falsy_pk"

            def __bool__(self):
                return False

            def __repr__(self):
                return "<FalsyDoc>"

        falsy_doc = _FalsyDoc()
        bootstrap_call_count = []

        class _Stub:
            _cached_guest = None

            @classmethod
            def find(cls, **kw):
                return falsy_doc  # falsy, but is NOT None

            def __init__(self, **kw):
                bootstrap_call_count.append(kw)
                self.pk = "bootstrap_pk"

            def save(self):
                pass

        result = AutoUser.get_guest.__func__(_Stub)

        assert result is falsy_doc, (
            "post-#98 the falsy non-None doc must be returned as-is "
            "(memoized to the cache). A regression to `if not guest:` "
            "would replace it with a freshly-bootstrapped duplicate."
        )
        assert bootstrap_call_count == [], (
            "bootstrap branch must NOT fire on falsy non-None — "
            "the `is None` check is shape-generic. "
            f"Got {len(bootstrap_call_count)} bootstrap calls."
        )
        assert _Stub._cached_guest is falsy_doc, (
            "memoization must store the find() result identity, "
            "not the bootstrap-loop output"
        )


# ===========================================================================
# #98 — log() side-effects on get_guest() branches
# ===========================================================================


class TestGetGuestLogSideEffects:
    """Pin the new log() side-effects added by #98 in ``get_guest``.

    The bootstrap branch added ``log(f"Bootstrapped …")`` with default
    print behavior (stdout echo). The memoization line (always runs
    on cache miss) added ``log(…, _print=False)`` — keyword-only
    deliberate. Both calls were untested by dev's restructured file.

    Regression risk worth pinning:
      - a future edit that drops ``_print=False`` would spam stdout
        on every cache miss across every process
      - a future edit that drops the bootstrap log would lose the
        only diagnostic for "did we ever bootstrap?" troubleshooting
    """

    def test_bootstrap_path_logs_bootstrap_and_memoize(self, monkeypatch):
        # Stub a `cls` whose find() returns None (forces bootstrap)
        # so both new log() calls fire.
        log_calls = []

        def _capture_log(msg, *args, **kwargs):
            log_calls.append((msg, kwargs))

        monkeypatch.setattr("autonomous.auth.user.log", _capture_log)

        class _Stub:
            _cached_guest = None

            @classmethod
            def find(cls, **kw):
                return None

            def __init__(self, **kw):
                self.pk = "bootstrapped_pk"

            def save(self):
                pass

        from autonomous.auth.user import AutoUser

        AutoUser.get_guest.__func__(_Stub)

        # Filter log_calls to just the two new ones (bootstrap +
        # memoize). The implementation might call log() more often
        # elsewhere; pin by message content.
        bootstrap_calls = [
            c for c in log_calls if "Bootstrapped" in str(c[0])
        ]
        memoize_calls = [
            c for c in log_calls if "Memoized" in str(c[0])
        ]

        assert len(bootstrap_calls) == 1, (
            f"bootstrap branch must log exactly one 'Bootstrapped' "
            f"diagnostic. Got: {bootstrap_calls!r}"
        )
        assert len(memoize_calls) == 1, (
            f"memoize line must log exactly one 'Memoized' "
            f"breadcrumb. Got: {memoize_calls!r}"
        )
        # Memoize call MUST be _print=False (per source line that
        # explicitly keyword-passes it) — a regression to default
        # would spam stdout on every cache miss.
        _, memoize_kwargs = memoize_calls[0]
        assert memoize_kwargs.get("_print") is False, (
            f"Memoize log must use _print=False to avoid stdout "
            f"spam on every cache miss. Got kwargs: {memoize_kwargs!r}"
        )

    def test_cache_hit_path_does_not_log(self, monkeypatch):
        # Cache hit short-circuits BEFORE reaching either log line.
        # If a future refactor moves the log calls above the cache
        # check, this test would flag it (and would also negate
        # the whole point of the cache, since stdout I/O is the
        # per-request cost we're trying to eliminate).
        log_calls = []
        monkeypatch.setattr(
            "autonomous.auth.user.log",
            lambda msg, *a, **kw: log_calls.append((msg, kw)),
        )

        class _Stub:
            _cached_guest = "cache-hit-sentinel"

            @classmethod
            def find(cls, **kw):
                raise AssertionError(
                    "find must not be called on cache hit"
                )

        from autonomous.auth.user import AutoUser

        result = AutoUser.get_guest.__func__(_Stub)
        assert result == "cache-hit-sentinel"

        # No "Bootstrapped" or "Memoized" log line should fire on
        # a cache hit — both are below the cache-hit early return.
        guest_related = [
            c for c in log_calls
            if "Bootstrapped" in str(c[0]) or "Memoized" in str(c[0])
        ]
        assert guest_related == [], (
            f"cache-hit path must short-circuit before guest-doc "
            f"log lines fire (otherwise the per-request I/O cost "
            f"the cache exists to eliminate creeps back in via "
            f"the log call). Got: {guest_related!r}"
        )


# ===========================================================================
# #99 — ContentDecodingError still gets translated (positive proof)
# ===========================================================================


class TestContentDecodingErrorTranslated:
    """Pin that ``ContentDecodingError`` is *behaviorally* outside the
    carve-out — it gets translated to ``HPCUnreachableError`` and
    triggers the retry loop.

    Dev's source-text pin asserts ``ContentDecodingError`` is absent
    from the carve-out tuple. This pin proves the deliberate
    exclusion is *live*: it actually goes through the
    ``except requests.RequestException`` branch, gets wrapped, and
    feeds into ``retry()``. A regression that accidentally adds it
    to the carve-out would propagate raw (skipping the wrap),
    breaking the ``[HPC-UNREACHABLE]`` Sentry scrape sentinel.
    """

    def _make_client(self):
        from autonomous.ai.models.openai_compat import OpenAIClient

        client = OpenAIClient.__new__(OpenAIClient)
        client._base_url = "http://localhost:9999"
        client._api_key = "test"
        client._timeout = 1
        client._text_model = "test-model"
        client._json_model = "test-model"
        client._retry_attempts = 1  # don't multiply attempts in the test
        client._retry_backoff = 0
        return client

    def test_content_decoding_error_translates_to_hpc_unreachable(
        self, monkeypatch
    ):
        from autonomous.ai.models.openai_compat import (
            HPCUnreachableError,
            OpenAIClient,
        )

        client = self._make_client()

        def _raise_content_decoding(*a, **kw):
            raise requests.exceptions.ContentDecodingError(
                "simulated malformed gzip"
            )

        monkeypatch.setattr(
            "autonomous.ai.models.openai_compat._SESSION.post",
            _raise_content_decoding,
        )

        # Must NOT propagate raw — must become HPCUnreachableError.
        with pytest.raises(HPCUnreachableError) as exc:
            client._post("/test", json_body={})

        # The wrapped exception's message preserves the original
        # exception class name (per source: `f"HPC unreachable
        # ({type(exc).__name__}): {exc}"`).
        assert "ContentDecodingError" in str(exc.value), (
            "wrap must preserve the original exception class name "
            "for Sentry triage. "
            f"Got: {exc.value!r}"
        )


# ===========================================================================
# #99 — SSLError propagates raw without entering retry loop
# ===========================================================================


class TestSSLErrorBypassesRetryLoop:
    """Pin that SSLError (newly in the carve-out per #99) raises raw
    from ``_attempt`` and propagates BEFORE ``retry()`` triggers a
    second attempt or sleeps.

    Dev's lockstep parametrize pins per-type propagation (the raise
    type). This pin adds the *behavioral* property: the carve-out
    short-circuits the retry loop entirely. A regression that moved
    SSLError out of the carve-out and let it become
    HPCUnreachableError would trigger ``retry()`` to call
    ``_SESSION.post`` ``_retry_attempts`` times AND sleep between
    them — multiplying the operator-debugging burden and burning
    backoff time.
    """

    def _make_client(self):
        from autonomous.ai.models.openai_compat import OpenAIClient

        client = OpenAIClient.__new__(OpenAIClient)
        client._base_url = "http://localhost:9999"
        client._api_key = "test"
        client._timeout = 1
        client._text_model = "test-model"
        client._json_model = "test-model"
        # If SSLError went through HPC translation, retry would
        # call _attempt this many times. The pin asserts exactly 1.
        client._retry_attempts = 5
        client._retry_backoff = 10  # would be noticeable if invoked
        return client

    def test_ssl_error_single_attempt_no_sleep(self, monkeypatch):
        post_calls = []
        sleep_calls = []

        def _raise_ssl(*a, **kw):
            post_calls.append((a, kw))
            raise requests.exceptions.SSLError(
                "[SSL: CERTIFICATE_VERIFY_FAILED] cert chain bogus"
            )

        def _record_sleep(seconds):
            sleep_calls.append(seconds)

        monkeypatch.setattr(
            "autonomous.ai.models.openai_compat._SESSION.post",
            _raise_ssl,
        )
        # The retry helper imports time at module level; patch both
        # the local and the helper module to be safe.
        monkeypatch.setattr(time, "sleep", _record_sleep)
        monkeypatch.setattr(
            "autonomous.ai.retry.time.sleep", _record_sleep,
        )

        client = self._make_client()

        with pytest.raises(requests.exceptions.SSLError):
            client._post("/test", json_body={})

        assert len(post_calls) == 1, (
            f"carve-out must short-circuit retry — SSLError must "
            f"trigger exactly 1 _SESSION.post call, not "
            f"{client._retry_attempts}. Got {len(post_calls)} calls."
        )
        assert sleep_calls == [], (
            f"carve-out must propagate BEFORE retry's sleep — "
            f"a regression to HPC translation would sleep "
            f"_retry_backoff={client._retry_backoff}s between "
            f"attempts. Got sleeps: {sleep_calls}"
        )


# ===========================================================================
# #100 — gemini value-shape guard: gap pins (UX, path-isolation, precedence)
# ===========================================================================


class TestGeminiValueShapeGapPins:
    """Pin orthogonal angles on the #100 value-shape guard that dev's
    lockstep tests leave exposed.

    Dev pins per-value-shape (string/int raises; bytes/bytearray/
    file-like passes). This class adds:
      - operator UX: error message includes the offending KEY name
      - path-isolation: list-of-dicts path is UNAFFECTED by value-shape
      - precedence: both-keys guard fires BEFORE value-shape
    """

    def _stub(self):
        from autonomous.ai.models.gemini import GeminiAIModel

        class _ClientFilesStub:
            @staticmethod
            def list():
                return []

        class _ClientStub:
            files = _ClientFilesStub()

        class _Stub:
            MAX_FILES = 0  # short-circuit the upload loop
            client = _ClientStub()

            def __init__(self):
                self.files = []
                self.file_refs = []

            def save(self):
                pass

        return GeminiAIModel, _Stub()

    def test_error_message_includes_offending_key_name(self):
        # Operator UX: when the value at key "name" is a string,
        # the error must call out "name" so the caller can grep
        # their code for the typo. A generic "value is not
        # file-like" message that omits the key would leave the
        # operator hunting through every dict key.
        GeminiAIModel, stub = self._stub()
        misused = {"name": "alice.webp", "metadata": io.BytesIO(b"x")}

        with pytest.raises(TypeError) as exc:
            GeminiAIModel._add_files(stub, misused)

        msg = str(exc.value)
        assert "'name'" in msg or '"name"' in msg, (
            f"error message must include the offending key name "
            f"(repr-quoted so the operator can grep). Got: {msg!r}"
        )

    def test_none_value_raises_TypeError(self):
        # None has no .read() and isn't bytes — must trip the guard.
        # Dev pins string/int values; None is a third independent
        # non-file shape that's worth a regression pin (a future
        # `if fobj is None: continue` performance "optimization"
        # would let bogus None entries through).
        GeminiAIModel, stub = self._stub()
        misused = {"alice.webp": None}

        with pytest.raises(TypeError) as exc:
            GeminiAIModel._add_files(stub, misused)
        assert "NoneType" in str(exc.value), (
            f"error message must call out NoneType so the operator "
            f"sees they passed None instead of a fileobj. "
            f"Got: {str(exc.value)!r}"
        )

    def test_list_path_unaffected_by_value_shape_guard(self):
        # The value-shape guard lives in the `isinstance(dict)`
        # branch only. The list-of-dicts path has its own validator
        # (per-entry: must be {'name', 'file'} dict). Pin that an
        # entry with a string `file` value flows through the list
        # path (the value-shape guard is NOT applied — only the
        # entry-shape guard is). A regression that hoists the
        # value-shape check above the branch split would break
        # the list path.
        GeminiAIModel, stub = self._stub()
        # Each list entry has the required keys; the value at
        # "file" is a string. The list-path validator only checks
        # entry shape, not value shape.
        entries = [{"name": "alice.webp", "file": "should-be-file-obj"}]
        # Should NOT raise the value-shape error (which would
        # mention #100). With MAX_FILES=0 the upload loop short-
        # circuits and the function returns [] cleanly.
        result = GeminiAIModel._add_files(stub, entries)
        assert result == [], (
            "list path must not run the dict-branch value-shape "
            "guard; only the dict-shape path validates value types"
        )

    def test_both_keys_guard_fires_before_value_shape_guard(self):
        # Precedence pin: a dict {"name": <str>, "file": <str>}
        # has BOTH keys (the both-keys guard from #90 fires) AND
        # non-file values (the value-shape guard from #100 would
        # also fire). The both-keys guard must win — its error
        # message is more informative (tells the operator to wrap
        # in a list).
        #
        # Discriminator: source contains "#85, #90." in the
        # both-keys message and "#85, #90, #100." in the value-
        # shape message. Pin via issue-tag presence rather than
        # English keywords ("wrap", "list") — keywords would
        # break on harmless message rewording.
        GeminiAIModel, stub = self._stub()
        misuse = {"name": "alice.webp", "file": "should-be-file-obj"}

        with pytest.raises(TypeError) as exc:
            GeminiAIModel._add_files(stub, misuse)

        msg = str(exc.value)
        assert "#100" not in msg, (
            f"value-shape error contains '#100'; presence here "
            f"means value-shape guard fired before both-keys "
            f"guard — wrong precedence. Got: {msg!r}"
        )
        assert "#90" in msg, (
            f"both-keys error must reference its source issue "
            f"(#90). Got: {msg!r}"
        )
