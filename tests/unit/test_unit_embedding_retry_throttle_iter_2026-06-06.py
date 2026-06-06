"""Independent coverage for PR #41 / issue #39 — embedding 5xx retry +
``[HPC-UNREACHABLE]`` log throttle.

Issue #39 had two failures braided together:

1. **500 bypassed retry entirely.** ``_TRANSPORT_FAILURE_CODES`` was
   ``{401, 502, 503, 504}`` — HTTP 500 didn't match, so 500 responses
   skipped the ``HPCUnreachableError`` translation and propagated as raw
   ``requests.HTTPError``. ``retry()`` catches the former, not the
   latter — so every 500 was a hard failure with zero retry attempts.
2. **The marker print path had no dedup.** Every embedding-chunk failure
   during a sustained degradation printed its own ``[HPC-UNREACHABLE]``
   line; ops observed ~60 identical-signature prints per 24h drowning
   unrelated signal.

PR #41's fix:

- Refactor the transport-failure check into ``_is_transport_failure(status)``
  covering 401 plus the full 5xx range (500-599, including partner-CDN
  codes 521-529). 500 now translates and retries.
- Add ``_emit_hpc_unreachable(signature, message)`` helper with **opt-in**
  throttling via ``HPC_UNREACHABLE_THROTTLE_SECONDS`` (default 0 = off).
  When set, identical-signature prints within the window are suppressed;
  the next print after the window includes a
  ``(N suppressed in last Ws)`` annotation. ``record_embedding_sync_event``
  remains unthrottled so the Redis health counter stays accurate.

Contracts pinned here:

- ``_is_transport_failure`` covers the full retry-eligible surface AND
  treats non-orderable inputs (the MagicMock fixture pattern) as
  "not transport" rather than raising — the latter would break
  pre-existing tests that mock the response object.
- The ``[HPC-UNREACHABLE]`` prefix is an observability contract; tests
  pin it under both throttle states.
- Default throttle behavior is **identical** to pre-#39 behavior
  (env unset → 0 → no throttle → print every call). Operators that
  haven't read the migration note get the same output stream they had
  before.
- Throttle scope is per-signature: a degraded ``openai`` provider does
  not silence a separate ``local:http:500`` signature firing for an
  unrelated upstream.
- ``record_embedding_sync_event("hpc_failure")`` fires on every embedding
  failure regardless of throttle state — the Redis bucket must capture
  every failure so the health dashboard stays accurate during
  log-throttled storms.
- The 500-now-retries fix in ``_post`` raises ``HPCUnreachableError`` from
  a 500 response so the existing ``retry(..., catch=(HPCUnreachableError,))``
  engages. Pre-fix the 500 raised ``requests.HTTPError`` from
  ``raise_for_status`` and slipped past the retry catch list.

Fresh-perspective check: I deliberately did NOT consult dev's local tests
under ``tests/_dev_local/`` (gitignored — invisible in the PR diff).
Tests derived from the diff in ``src/autonomous/ai/models/openai_compat.py``
and ``src/autonomous/db/db_sync.py``.
"""

from unittest.mock import MagicMock, patch

import pytest

from autonomous.ai.models.openai_compat import (
    HPCUnreachableError,
    OpenAIClient,
    _is_transport_failure,
    _TRANSPORT_FAILURE_CODES,
)
from autonomous.db import db_sync
from autonomous.db.db_sync import (
    _emit_hpc_unreachable,
    _throttle_window_seconds,
)


# ---------------------------------------------------------------------------
# Module state isolation
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_throttle_state():
    """Module-level dicts (_HPC_UNREACHABLE_LAST_LOGGED /
    _HPC_UNREACHABLE_SUPPRESSED) accumulate across calls; clear them
    before AND after each test so accidental leakage between tests can't
    mask a regression in either direction. Reading the originals via
    ``db_sync.`` (not via direct import-bind) so the .clear() actually
    mutates the module-level dict the production code uses."""
    db_sync._HPC_UNREACHABLE_LAST_LOGGED.clear()
    db_sync._HPC_UNREACHABLE_SUPPRESSED.clear()
    yield
    db_sync._HPC_UNREACHABLE_LAST_LOGGED.clear()
    db_sync._HPC_UNREACHABLE_SUPPRESSED.clear()


@pytest.fixture(autouse=True)
def _silence_redis(monkeypatch):
    """``record_embedding_sync_event`` writes to Redis. Tests that exercise
    the embedding call sites should still see the counter call happen,
    but the actual Redis write must not require a live container.
    ``_get_redis()`` already swallows failures (best-effort observability),
    but patching it to a MagicMock makes the call site testable AND
    avoids spurious connection errors / timeouts in the unit tier."""
    monkeypatch.setattr(db_sync, "_get_redis", lambda: MagicMock())


# ===========================================================================
# Part 1 — _is_transport_failure: the retry-eligibility check
# ===========================================================================

class TestIsTransportFailureRetryEligibleCodes:
    """The full set that must engage retry. 500 is the headline addition
    in #39 — previously omitted, so it bypassed the HPCUnreachableError
    translation entirely. Pinning the rest of the 5xx family so a future
    refactor that re-introduces a fixed-set membership check would have
    to remove these assertions explicitly."""

    @pytest.mark.parametrize("status", [
        401,           # auth — same recovery as VPN drop, retryable
        500,           # THE #39 BUG: was missing from the fixed set
        501, 502, 503, 504, 505,  # standard 5xx
        521, 522, 523, 524, 525, 526, 527, 528, 529,  # Cloudflare/CDN
        599,           # upper bound of 5xx range
    ])
    def test_status_eligible_for_retry(self, status):
        assert _is_transport_failure(status) is True, (
            f"status {status} must be transport-failure (retry-eligible); "
            f"#39 fix uses range check status >= 500"
        )


class TestIsTransportFailureNonRetryable:
    """Bad-input / client-error codes must NOT engage retry — 400s have
    a different recovery path (caller fixes the request) and a retry
    would just re-fail the same way."""

    @pytest.mark.parametrize("status", [
        100, 200, 201, 204, 301, 302, 304, 400, 403, 404, 422, 429, 499,
    ])
    def test_status_not_transport_failure(self, status):
        # 429 (rate-limit) is debatable — left non-retryable here to
        # match the diff. If a future patch adds 429 retry, update.
        assert _is_transport_failure(status) is False, (
            f"status {status} must not be transport-failure"
        )


class TestIsTransportFailureNonIntegerInputs:
    """The check must be robust to non-int inputs. Pre-existing tests use
    ``MagicMock`` for the response object, and ``MagicMock`` is neither in
    the frozenset nor orderable against an int with ``>=`` — the diff
    catches TypeError and returns False, preserving the legacy
    ``response.status_code in {401, 502, ...}`` semantics for those
    fixtures."""

    def test_magicmock_returns_false(self):
        # MagicMock supports ``in`` (returns False) but `>=` raises TypeError.
        assert _is_transport_failure(MagicMock()) is False

    def test_none_returns_false(self):
        # ``None >= 500`` raises TypeError on Py3.
        assert _is_transport_failure(None) is False

    def test_string_status_returns_false(self):
        # ``"500" >= 500`` raises TypeError on Py3. Treating as non-transport
        # matches the legacy fixed-set ``in`` behavior (string "500" is not
        # int 500). If a caller is passing strings, that's a separate bug.
        assert _is_transport_failure("500") is False


class TestTransportFailureCodesFrozenSet:
    """Pin the explicit-codes set to the new minimal value. If a future
    edit re-expands it back to include 5xx members, the range check in
    ``_is_transport_failure`` becomes redundant for those values — but
    the set itself should stay minimal so the range branch is the
    single source of truth for 5xx-class failures (easier to audit)."""

    def test_set_contains_only_401(self):
        # 401 is the non-5xx exception — auth has the same recovery
        # path as a transient transport failure (re-auth / refresh).
        assert _TRANSPORT_FAILURE_CODES == frozenset({401})


# ===========================================================================
# Part 2 — _throttle_window_seconds: env-var parsing
# ===========================================================================

class TestThrottleWindowSeconds:
    """Read each call — supports an ops-side env flip without a worker
    restart. Malformed values must degrade to 0 (disabled) — the
    historical default — rather than crash the print path."""

    def test_unset_returns_zero(self, monkeypatch):
        monkeypatch.delenv("HPC_UNREACHABLE_THROTTLE_SECONDS", raising=False)
        assert _throttle_window_seconds() == 0

    def test_explicit_zero_returns_zero(self, monkeypatch):
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "0")
        assert _throttle_window_seconds() == 0

    def test_positive_int_returns_int(self, monkeypatch):
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "60")
        assert _throttle_window_seconds() == 60

    @pytest.mark.parametrize("malformed", ["abc", "", "60s", "1.5", "nan"])
    def test_malformed_returns_zero(self, monkeypatch, malformed):
        """Garbage env values fall back to 0 (throttle off) — the safest
        default for an observability path. The fail-open posture means
        a misconfigured env never silences legitimate prints."""
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", malformed)
        assert _throttle_window_seconds() == 0

    def test_reads_each_call_not_cached(self, monkeypatch):
        """Ops flip the env mid-run — the next call must see the new
        value. Module-level caching would defeat the runtime tuning."""
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "0")
        assert _throttle_window_seconds() == 0
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "60")
        assert _throttle_window_seconds() == 60


# ===========================================================================
# Part 3 — _emit_hpc_unreachable: print + throttle
# ===========================================================================

class TestEmitHpcUnreachableThrottleOff:
    """Default behavior (env unset / 0): every call prints verbatim.
    THIS IS THE BACKWARDS-COMPAT CONTRACT — pre-#39 every embedding
    failure printed exactly once. Operators that haven't read the
    migration must get identical output."""

    def test_prints_message_when_throttle_off(self, monkeypatch, capsys):
        monkeypatch.delenv("HPC_UNREACHABLE_THROTTLE_SECONDS", raising=False)
        _emit_hpc_unreachable("sig", "[HPC-UNREACHABLE] test message")
        out = capsys.readouterr().out
        assert "[HPC-UNREACHABLE] test message" in out

    def test_prints_every_call_when_throttle_off(self, monkeypatch, capsys):
        monkeypatch.delenv("HPC_UNREACHABLE_THROTTLE_SECONDS", raising=False)
        for i in range(5):
            _emit_hpc_unreachable("sig", f"[HPC-UNREACHABLE] msg {i}")
        out = capsys.readouterr().out
        for i in range(5):
            assert f"[HPC-UNREACHABLE] msg {i}" in out

    def test_throttle_zero_explicit_same_as_unset(self, monkeypatch, capsys):
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "0")
        for i in range(3):
            _emit_hpc_unreachable("sig", f"msg {i}")
        out = capsys.readouterr().out
        for i in range(3):
            assert f"msg {i}" in out


class TestEmitHpcUnreachableThrottleOn:
    """When env > 0, identical-signature prints within the window are
    suppressed; the next print outside the window carries a
    ``(N suppressed in last Ws)`` annotation. ``time.monotonic`` is
    monkey-patched so the test doesn't actually sleep."""

    def test_first_call_prints_within_window(self, monkeypatch, capsys):
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "60")
        monkeypatch.setattr(db_sync.time, "monotonic", lambda: 1000.0)
        _emit_hpc_unreachable("sig", "[HPC-UNREACHABLE] first")
        out = capsys.readouterr().out
        assert "[HPC-UNREACHABLE] first" in out

    def test_second_call_within_window_suppressed(self, monkeypatch, capsys):
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "60")
        clock = [1000.0]
        monkeypatch.setattr(db_sync.time, "monotonic", lambda: clock[0])

        _emit_hpc_unreachable("sig", "[HPC-UNREACHABLE] first")
        clock[0] = 1030.0  # 30s later — inside the 60s window
        _emit_hpc_unreachable("sig", "[HPC-UNREACHABLE] second")

        out = capsys.readouterr().out
        # First prints; second is suppressed.
        assert "[HPC-UNREACHABLE] first" in out
        assert "[HPC-UNREACHABLE] second" not in out

    def test_print_after_window_includes_suppressed_count(
        self, monkeypatch, capsys
    ):
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "60")
        clock = [1000.0]
        monkeypatch.setattr(db_sync.time, "monotonic", lambda: clock[0])

        _emit_hpc_unreachable("sig", "first")  # prints
        # Three suppressions within the window.
        for offset in (10.0, 20.0, 30.0):
            clock[0] = 1000.0 + offset
            _emit_hpc_unreachable("sig", "suppressed")

        # Advance past the window — next call prints, with annotation.
        clock[0] = 1100.0  # 100s after the first → outside the 60s window
        _emit_hpc_unreachable("sig", "tail")

        out = capsys.readouterr().out
        assert "first" in out
        assert "tail" in out
        assert "(3 suppressed in last 60s)" in out, (
            f"tail call must include the suppressed-count annotation; "
            f"got: {out!r}"
        )

    def test_suppressed_counter_clears_after_print(
        self, monkeypatch, capsys
    ):
        """The annotation is one-shot — after printing it, the counter
        resets so the NEXT print doesn't double-count."""
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "60")
        clock = [1000.0]
        monkeypatch.setattr(db_sync.time, "monotonic", lambda: clock[0])

        _emit_hpc_unreachable("sig", "first")  # prints, no suppressed yet
        clock[0] = 1030.0
        _emit_hpc_unreachable("sig", "suppressed-A")  # suppressed (count=1)
        clock[0] = 1100.0
        _emit_hpc_unreachable("sig", "tail-1")  # prints w/ "(1 suppressed...)"
        clock[0] = 1200.0
        _emit_hpc_unreachable("sig", "tail-2")  # prints, no annotation

        out = capsys.readouterr().out
        assert "(1 suppressed in last 60s)" in out
        # Crucial: tail-2 prints WITHOUT carrying tail-1's annotation.
        # If the counter wasn't cleared, tail-2 would re-emit "(1 suppressed...)".
        lines = [ln for ln in out.split("\n") if "tail-2" in ln]
        assert len(lines) == 1
        assert "suppressed" not in lines[0]

    def test_distinct_signatures_dont_collide(self, monkeypatch, capsys):
        """A degraded openai provider must not silence an unrelated
        local-provider failure. Per-signature scope is the whole point —
        otherwise the dedup eats genuinely new signals."""
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "60")
        monkeypatch.setattr(db_sync.time, "monotonic", lambda: 1000.0)

        _emit_hpc_unreachable("openai:HPCUnreachableError", "openai down")
        _emit_hpc_unreachable("local:http:500", "local down")

        out = capsys.readouterr().out
        assert "openai down" in out
        assert "local down" in out  # MUST print — different signature

    def test_signature_window_independence(self, monkeypatch, capsys):
        """Each signature has its own window. sig-A being throttled
        doesn't reset sig-B's clock."""
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "60")
        clock = [1000.0]
        monkeypatch.setattr(db_sync.time, "monotonic", lambda: clock[0])

        _emit_hpc_unreachable("sig-A", "A-first")
        clock[0] = 1010.0
        _emit_hpc_unreachable("sig-B", "B-first")
        # Both first prints land.
        out = capsys.readouterr().out
        assert "A-first" in out
        assert "B-first" in out

        # Now both suppressed within their own windows.
        clock[0] = 1030.0
        _emit_hpc_unreachable("sig-A", "A-supp")
        _emit_hpc_unreachable("sig-B", "B-supp")
        out = capsys.readouterr().out
        assert "A-supp" not in out
        assert "B-supp" not in out


class TestEmitMarkerPrefixPreserved:
    """The ``[HPC-UNREACHABLE]`` prefix is an observability contract; log
    scrapers grep for it. Pin under both throttle states so a future
    refactor of the throttle path doesn't silently mangle the prefix.

    The function itself doesn't add the prefix — the caller does. Pin
    that the function passes the message through verbatim AND that the
    suppressed-count annotation is appended AFTER the message (so the
    prefix at message-start stays at line-start)."""

    def test_prefix_verbatim_throttle_off(self, monkeypatch, capsys):
        monkeypatch.delenv("HPC_UNREACHABLE_THROTTLE_SECONDS", raising=False)
        msg = "[HPC-UNREACHABLE] openai embedding failed: oops"
        _emit_hpc_unreachable("sig", msg)
        out = capsys.readouterr().out
        assert msg in out

    def test_prefix_verbatim_throttle_on_first_call(
        self, monkeypatch, capsys
    ):
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "60")
        monkeypatch.setattr(db_sync.time, "monotonic", lambda: 1000.0)
        msg = "[HPC-UNREACHABLE] openai embedding failed: oops"
        _emit_hpc_unreachable("sig", msg)
        out = capsys.readouterr().out
        assert msg in out

    def test_suppressed_annotation_appended_not_inserted(
        self, monkeypatch, capsys
    ):
        """``(N suppressed ...)`` must come AFTER the message, not be
        spliced inside the ``[HPC-UNREACHABLE]`` prefix or the body —
        log scrapers parse left-to-right and the prefix should remain
        at line-start."""
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "60")
        clock = [1000.0]
        monkeypatch.setattr(db_sync.time, "monotonic", lambda: clock[0])

        _emit_hpc_unreachable("sig", "[HPC-UNREACHABLE] first")
        clock[0] = 1010.0
        _emit_hpc_unreachable("sig", "[HPC-UNREACHABLE] suppressed")
        clock[0] = 1100.0
        _emit_hpc_unreachable("sig", "[HPC-UNREACHABLE] tail")

        out = capsys.readouterr().out
        # The tail line must start with the prefix and end with the
        # annotation, not have the annotation interleaved.
        tail_line = next(
            ln for ln in out.split("\n")
            if "[HPC-UNREACHABLE] tail" in ln
        )
        assert tail_line.startswith("[HPC-UNREACHABLE] tail")
        assert tail_line.endswith("(1 suppressed in last 60s)")


# ===========================================================================
# Part 4 — _post in openai_compat: 500 now retries (was bypassing)
# ===========================================================================

class TestPostFiveHundredRetries:
    """Pre-#39: a 500 response status fell through the
    ``response.status_code in _TRANSPORT_FAILURE_CODES`` membership check
    (set was ``{401, 502, 503, 504}``), so ``response.raise_for_status()``
    raised ``requests.HTTPError`` — and ``retry()`` is configured with
    ``catch=(HPCUnreachableError,)``, so the HTTPError slipped past the
    retry layer entirely.

    Post-#39: 500 routes through the new range check, raises
    ``HPCUnreachableError``, and ``retry()`` engages. Pinning by
    asserting the exception type the call site sees after retry exhaustion.
    """

    def _client(self, monkeypatch):
        """Bare OpenAIClient that bypasses __init__'s env-var reads and
        sets the bare minimum for _post to run."""
        client = OpenAIClient.__new__(OpenAIClient)
        client._base_url = "http://hpc.test"
        client._timeout = 5
        client._retry_attempts = 1  # one attempt, no actual retry sleep
        client._retry_backoff = 0
        client._headers = lambda content_type=None: {}
        return client

    def test_500_raises_hpcunreachable_not_httperror(self, monkeypatch):
        """Direct contract: a 500 status from the HTTP session must
        produce HPCUnreachableError, NOT requests.HTTPError. This is the
        translation step that lets retry() catch and re-attempt."""
        client = self._client(monkeypatch)

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "internal server error"
        # raise_for_status() should NOT be hit — the transport-failure
        # check happens first. Configure it to raise loudly to catch
        # regressions where the check is bypassed.
        mock_response.raise_for_status.side_effect = AssertionError(
            "raise_for_status must not be called for 500 — "
            "_is_transport_failure should engage first and raise "
            "HPCUnreachableError before the HTTPError path."
        )
        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        monkeypatch.setattr(
            "autonomous.ai.models.openai_compat._SESSION", mock_session
        )

        with pytest.raises(HPCUnreachableError) as excinfo:
            client._post("/chat/completions", json_body={"x": 1})

        # The error message should surface the 500 status for diagnostic
        # legibility (the existing format string includes status code).
        assert "500" in str(excinfo.value)

    def test_502_503_504_still_route_through_retry(self, monkeypatch):
        """Sanity-check that the pre-existing 5xx members still hit the
        same translation. The diff replaced the fixed-set check with a
        range — these used to be in the set and must remain
        transport-failures under the new logic."""
        for status in (502, 503, 504):
            client = self._client(monkeypatch)
            mock_response = MagicMock()
            mock_response.status_code = status
            mock_response.text = ""
            mock_session = MagicMock()
            mock_session.post.return_value = mock_response
            monkeypatch.setattr(
                "autonomous.ai.models.openai_compat._SESSION", mock_session
            )
            with pytest.raises(HPCUnreachableError):
                client._post("/chat/completions", json_body={})

    def test_400_does_not_route_through_retry(self, monkeypatch):
        """Negative control: a 400 is NOT a transport failure — must
        propagate as the regular HTTPError from raise_for_status. The
        retry layer would just spin on the bad input otherwise."""
        import requests

        client = self._client(monkeypatch)
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "bad request"
        mock_response.raise_for_status.side_effect = requests.HTTPError(
            "400 Client Error"
        )
        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        monkeypatch.setattr(
            "autonomous.ai.models.openai_compat._SESSION", mock_session
        )

        with pytest.raises(requests.HTTPError):
            client._post("/chat/completions", json_body={})


# ===========================================================================
# Part 5 — call-site contract: record_embedding_sync_event is NOT throttled
# ===========================================================================

class TestRecordEventNotThrottled:
    """Throttling is for the print path only — the Redis hour-bucketed
    counter must increment on EVERY failure so the health dashboard
    stays accurate during log-throttled storms. Operators specifically
    set the throttle to dedup logs, NOT to dedup health signal."""

    def test_local_path_calls_record_event_per_failure_under_throttle(
        self, monkeypatch
    ):
        """Drive ``_get_vector_local`` through a 500-on-every-call path,
        with the throttle ON and small window — count how many times
        ``record_embedding_sync_event`` was called. Even though most
        prints are suppressed, every failure must hit the counter."""
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "3600")

        # Frozen clock keeps every call inside the throttle window so
        # only the first print fires — but record_embedding_sync_event
        # should still be called per call.
        monkeypatch.setattr(db_sync.time, "monotonic", lambda: 1000.0)

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {}
        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        monkeypatch.setattr(db_sync, "_HTTP_SESSION", mock_session)

        recorded = []

        def fake_record(event, redis_client=None):
            recorded.append(event)

        monkeypatch.setattr(db_sync, "record_embedding_sync_event", fake_record)

        from autonomous.db.db_sync import _get_vector_local
        for _ in range(5):
            result = _get_vector_local("anything")
            assert result is None  # documented degrade contract

        # 5 failures → 5 counter increments, regardless of throttle state.
        assert recorded == ["hpc_failure"] * 5, (
            "Redis counter must increment on every failure even when log "
            "prints are throttled; got: %r" % recorded
        )

    def test_openai_path_calls_record_event_per_failure_under_throttle(
        self, monkeypatch
    ):
        """Same contract on the openai path. The two paths share the
        same observability contract — both call record_event regardless
        of print throttling."""
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "3600")
        monkeypatch.setattr(db_sync.time, "monotonic", lambda: 1000.0)

        recorded = []

        def fake_record(event, redis_client=None):
            recorded.append(event)

        monkeypatch.setattr(db_sync, "record_embedding_sync_event", fake_record)

        with patch.object(
            OpenAIClient,
            "get_embedding",
            side_effect=HPCUnreachableError("upstream gone"),
        ):
            from autonomous.db.db_sync import _get_vector_openai
            for _ in range(5):
                result = _get_vector_openai("anything")
                assert result is None

        assert recorded == ["hpc_failure"] * 5


# ===========================================================================
# Part 6 — call-site contract: throttle ON suppresses prints, OFF preserves
# ===========================================================================

class TestCallSiteThrottleIntegration:
    """End-to-end through ``_get_vector_local`` — confirm the throttle
    actually engages at the production call site (not just in a direct
    test of the helper). The signature shape ``local:http:{status}``
    means N consecutive 500s should print once under throttle."""

    def test_throttle_off_prints_per_call(self, monkeypatch, capsys):
        monkeypatch.delenv("HPC_UNREACHABLE_THROTTLE_SECONDS", raising=False)

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {}
        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        monkeypatch.setattr(db_sync, "_HTTP_SESSION", mock_session)

        from autonomous.db.db_sync import _get_vector_local
        for _ in range(3):
            _get_vector_local("text")

        out = capsys.readouterr().out
        # Three failures, throttle off → three prints (one per call).
        assert out.count("[HPC-UNREACHABLE] local embedding failed: HTTP 500") == 3

    def test_throttle_on_dedups_same_signature(self, monkeypatch, capsys):
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "3600")
        monkeypatch.setattr(db_sync.time, "monotonic", lambda: 1000.0)

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {}
        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        monkeypatch.setattr(db_sync, "_HTTP_SESSION", mock_session)

        from autonomous.db.db_sync import _get_vector_local
        for _ in range(3):
            _get_vector_local("text")

        out = capsys.readouterr().out
        # Same signature (local:http:500) × 3 calls within window → 1 print.
        assert out.count("[HPC-UNREACHABLE] local embedding failed: HTTP 500") == 1

    def test_throttle_on_different_status_codes_print_each(
        self, monkeypatch, capsys
    ):
        """Signatures differ by status code (``local:http:500`` vs
        ``local:http:503``), so distinct upstream codes don't silence
        each other under throttle. Useful when an upstream cycles
        through multiple failure modes."""
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "3600")
        monkeypatch.setattr(db_sync.time, "monotonic", lambda: 1000.0)

        codes = [500, 503, 502, 500]  # 500 should print once, others once each

        responses = []
        for code in codes:
            r = MagicMock()
            r.status_code = code
            r.json.return_value = {}
            responses.append(r)

        mock_session = MagicMock()
        mock_session.post.side_effect = responses
        monkeypatch.setattr(db_sync, "_HTTP_SESSION", mock_session)

        from autonomous.db.db_sync import _get_vector_local
        for _ in codes:
            _get_vector_local("text")

        out = capsys.readouterr().out
        # Distinct codes get distinct signatures → distinct prints.
        # The repeated 500 is throttled → 3 prints total (500, 503, 502).
        assert out.count("HTTP 500") == 1
        assert out.count("HTTP 503") == 1
        assert out.count("HTTP 502") == 1
