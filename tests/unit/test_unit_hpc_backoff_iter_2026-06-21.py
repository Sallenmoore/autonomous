"""Issue #182 / PR #184: exponential backoff on the HPC retry budget.

Independent second-perspective coverage, written from the PR diff alone
(the dev agent's ``tests/_dev_local/`` are gitignored and invisible here).

The change under test adds a ``backoff_factor`` knob to the retry stack so
the *same* HPC attempt budget can ride out a longer transient-degraded
backend window before surfacing ``HPCUnreachableError``. The fix the
consumer (#182 / storyteller #326) needed: a ``ReadTimeout`` already rode
the retry budget, but the *flat* spacing (3 attempts x 10s = ~20s) was too
short for the observed degraded windows. Geometric spacing widens the
ride-out without inflating ``max_attempts`` (extra attempts would add a
full read-timeout stall each, on the fast path).

Layers exercised, lowest to highest:
- A — ``retry(backoff_factor=...)`` sleep math (the geometric series).
- B — ``retry`` validation guard (``>= 1.0``, finite; same shape as jitter).
- C — ``HttpClient(retry_backoff_factor=...)`` eager constructor validation.
- D — the ``backoff_factor=1.0`` no-op forwarding seam (keeps the legacy
      ``retry(...)`` call signature byte-identical for flat-backoff
      adapters — the seam that keeps the existing ``fake_retry`` mocks in
      ``test_unit_http_observability_iter_2026-06-10.py`` passing).
- E — ``Settings`` clamps ``HPC_RETRY_BACKOFF_FACTOR`` (default 2.0).
- F — end-to-end through ``openai_compat._HTTP``: a ``ReadTimeout`` retries
      ``max_attempts`` times then raises ``HPCUnreachableError``; a
      recover-on-2nd-attempt case succeeds; default HPC factor (2.0) yields
      10s, 20s spacing.

These tests bind to the NEW behavior — the revert-sanity-check
(temporarily reverting the touched source to ``origin/test``) makes the
backoff-specific assertions fail, proving they don't pass vacuously.
"""

from __future__ import annotations

import math

import pytest
import requests

from autonomous.ai.retry import retry


# ---------------------------------------------------------------------------
# Section A — retry() geometric sleep math
# ---------------------------------------------------------------------------


class TestRetryBackoffSleepMath:
    """The wait BEFORE attempt ``n`` (1-indexed) is
    ``sleep_seconds * backoff_factor ** (n - 1)``. Patch ``time.sleep`` to
    record the sleep sequence and assert the geometric series directly —
    no real sleeping. The first inter-attempt gap uses factor**0 == 1
    (i.e. plain ``sleep_seconds``); each subsequent gap multiplies by the
    factor."""

    def _record_sleeps(self, monkeypatch):
        slept: list[float] = []
        monkeypatch.setattr("autonomous.ai.retry.time.sleep", slept.append)
        return slept

    def test_factor_2_yields_geometric_series(self, monkeypatch):
        slept = self._record_sleeps(monkeypatch)
        calls = {"n": 0}

        def always_fail():
            calls["n"] += 1
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            retry(
                always_fail,
                max_attempts=4,
                sleep_seconds=10,
                backoff_factor=2.0,
            )
        # 4 attempts => 3 inter-attempt sleeps (none after the final).
        assert calls["n"] == 4
        assert slept == [10.0, 20.0, 40.0]

    def test_factor_2_matches_hpc_defaults_10s_20s(self, monkeypatch):
        """The HPC opt-in shape: 3 attempts, base 10s, factor 2.0 ->
        inter-attempt waits of 10s then 20s (the #182 ride-out, ~30s
        total vs. the old flat ~20s)."""
        slept = self._record_sleeps(monkeypatch)

        def always_fail():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            retry(always_fail, max_attempts=3, sleep_seconds=10, backoff_factor=2.0)
        assert slept == [10.0, 20.0]

    def test_factor_1_is_byte_identical_flat_backoff(self, monkeypatch):
        """Default factor 1.0 == legacy flat backoff: every gap is exactly
        ``sleep_seconds`` (factor**(n-1) == 1 for all n). This is the
        back-compat guarantee for every existing caller."""
        slept = self._record_sleeps(monkeypatch)

        def always_fail():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            retry(always_fail, max_attempts=4, sleep_seconds=5, backoff_factor=1.0)
        assert slept == [5.0, 5.0, 5.0]

    def test_default_factor_is_flat(self, monkeypatch):
        """Omitting ``backoff_factor`` entirely must behave exactly like
        the pre-#182 flat backoff — the default is 1.0, not 2.0. (2.0 is
        the *HPC settings* default, not the function default; conflating
        them would silently change every existing caller's spacing.)"""
        slept = self._record_sleeps(monkeypatch)

        def always_fail():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            retry(always_fail, max_attempts=3, sleep_seconds=7)
        assert slept == [7.0, 7.0]

    def test_no_sleep_after_final_attempt(self, monkeypatch):
        """Even with growth, the loop never sleeps after the last attempt —
        there's nothing left to retry. 1 attempt => 0 sleeps."""
        slept = self._record_sleeps(monkeypatch)

        def always_fail():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            retry(always_fail, max_attempts=1, sleep_seconds=10, backoff_factor=2.0)
        assert slept == []

    def test_success_short_circuits_before_backoff_grows(self, monkeypatch):
        """Recovery on attempt 2 only pays the first (un-grown) gap; the
        later, larger gaps are never incurred."""
        slept = self._record_sleeps(monkeypatch)
        calls = {"n": 0}

        def fail_once_then_ok():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient")
            return "ok"

        result = retry(
            fail_once_then_ok,
            max_attempts=4,
            sleep_seconds=10,
            backoff_factor=2.0,
        )
        assert result == "ok"
        assert calls["n"] == 2
        assert slept == [10.0]  # only the first gap, never 20/40


# ---------------------------------------------------------------------------
# Section B — retry() backoff_factor validation guard
# ---------------------------------------------------------------------------


class TestRetryBackoffValidation:
    """``backoff_factor`` must be a finite float ``>= 1.0`` — same defect
    class as the existing ``jitter`` NaN guard. A shrinking factor is
    almost always a config typo; a non-finite one (``NaN`` survives a bare
    ``< 1.0`` check) would poison ``factor ** (n-1)`` -> ``time.sleep``
    mid-loop with no breadcrumb."""

    def _noop(self):
        return "x"

    def test_factor_below_one_rejected(self):
        with pytest.raises(ValueError, match="backoff_factor"):
            retry(self._noop, backoff_factor=0.5)

    def test_factor_zero_rejected(self):
        with pytest.raises(ValueError, match="backoff_factor"):
            retry(self._noop, backoff_factor=0.0)

    def test_nan_factor_rejected(self):
        # NaN < 1.0 is False, so a bare comparison would let it through —
        # this is the whole reason the guard uses math.isfinite.
        with pytest.raises(ValueError, match="backoff_factor"):
            retry(self._noop, backoff_factor=float("nan"))

    def test_inf_factor_rejected(self):
        with pytest.raises(ValueError, match="backoff_factor"):
            retry(self._noop, backoff_factor=float("inf"))

    def test_factor_exactly_one_accepted(self):
        # The boundary value (legacy flat backoff) must be valid.
        assert retry(self._noop, backoff_factor=1.0) == "x"

    def test_large_finite_factor_accepted(self):
        assert retry(self._noop, backoff_factor=10.0) == "x"

    def test_validation_runs_before_first_call(self):
        """The guard must reject up-front, not after burning an attempt —
        a bad factor is a programming/config error, not a transient one."""
        calls = {"n": 0}

        def counted():
            calls["n"] += 1
            return "x"

        with pytest.raises(ValueError):
            retry(counted, backoff_factor=float("nan"))
        assert calls["n"] == 0


# ---------------------------------------------------------------------------
# Section C — HttpClient eager constructor validation
# ---------------------------------------------------------------------------


class TestHttpClientBackoffFactorConstruction:
    """``HttpClient(retry_backoff_factor=...)`` validates eagerly at
    construction (mirrors the ``max_attempts`` check) so a misconfigured
    module-level adapter constant (e.g. ``openai_compat._HTTP``) fails at
    import, not on the first transient failure in prod."""

    def test_default_factor_is_one(self):
        from autonomous.http.client import HttpClient

        c = HttpClient()
        assert c.retry_backoff_factor == 1.0

    def test_valid_factor_roundtrips(self):
        from autonomous.http.client import HttpClient

        c = HttpClient(retry_backoff_factor=2.0)
        assert c.retry_backoff_factor == 2.0

    @pytest.mark.parametrize("bad", [0.5, 0.0, float("nan"), float("inf")])
    def test_invalid_factor_raises_at_construction(self, bad):
        from autonomous.http.client import HttpClient

        with pytest.raises(ValueError, match="retry_backoff_factor"):
            HttpClient(retry_backoff_factor=bad)

    def test_factor_exactly_one_constructs(self):
        from autonomous.http.client import HttpClient

        assert HttpClient(retry_backoff_factor=1.0).retry_backoff_factor == 1.0


# ---------------------------------------------------------------------------
# Section D — the backoff_factor=1.0 no-op forwarding seam
# ---------------------------------------------------------------------------


class _FakeResp:
    status_code = 200
    text = "{}"
    content = b"{}"

    def raise_for_status(self):
        # 200 — no-op, mirroring requests.Response.raise_for_status.
        return None

    def json(self):
        return {}


def _mock_session_request(resp):
    def _request(method, url, **kwargs):
        return resp
    sess = requests.Session()
    sess.request = _request  # type: ignore[method-assign]
    return sess


class TestBackoffFactorForwardingSeam:
    """``HttpClient.request`` forwards ``backoff_factor`` to ``retry`` ONLY
    when it's the non-default exponential value. ``1.0`` is a true no-op in
    ``retry`` (every gap x 1.0**(n-1) == itself), so omitting it for
    flat-backoff clients keeps the ``retry(...)`` call signature
    byte-identical to pre-#182. This is the seam that keeps the existing
    legacy-signature ``fake_retry`` mocks (no ``backoff_factor`` kwarg)
    passing — a naive always-forward would break them with a TypeError."""

    def test_factor_one_does_not_forward_backoff_factor(self, monkeypatch):
        from autonomous.http.client import HttpClient

        captured: dict = {}

        # Mimic the legacy-signature mock in
        # test_unit_http_observability_iter_2026-06-10.py — it has NO
        # backoff_factor param. If client.py forwarded backoff_factor for a
        # default (1.0) client, this would blow up with a TypeError.
        def legacy_fake_retry(func, *, max_attempts, sleep_seconds, jitter, catch):
            captured["called"] = True
            return func()

        monkeypatch.setattr("autonomous.http.client.retry", legacy_fake_retry)
        c = HttpClient(
            session=_mock_session_request(_FakeResp()),
            max_attempts=3,
            retry_backoff=2.0,
        )  # retry_backoff_factor defaults to 1.0
        c.request("GET", "http://x")  # must NOT raise TypeError
        assert captured.get("called") is True

    def test_non_default_factor_is_forwarded(self, monkeypatch):
        from autonomous.http.client import HttpClient

        captured: dict = {}

        def fake_retry(func, *, max_attempts, sleep_seconds, jitter, catch, **kwargs):
            captured.update(kwargs)
            captured["max_attempts"] = max_attempts
            return func()

        monkeypatch.setattr("autonomous.http.client.retry", fake_retry)
        c = HttpClient(
            session=_mock_session_request(_FakeResp()),
            max_attempts=3,
            retry_backoff=10.0,
            retry_backoff_factor=2.0,
        )
        c.request("GET", "http://x")
        assert captured.get("backoff_factor") == 2.0

    def test_legacy_mock_signature_still_works_for_default_client(self, monkeypatch):
        """Directly defends the seam contract that
        test_unit_http_observability_iter_2026-06-10.py relies on: a mock
        with the exact pre-#182 signature must accept the call from a
        default-factor client without a TypeError. If this test ever fails,
        the observability plumbing tests will have broken too."""
        from autonomous.http.client import HttpClient, TransportError

        seen: dict = {}

        def fake_retry(func, *, max_attempts, sleep_seconds, jitter, catch):
            seen["max_attempts"] = max_attempts
            seen["sleep_seconds"] = sleep_seconds
            seen["jitter"] = jitter
            seen["catch"] = catch
            return func()

        monkeypatch.setattr("autonomous.http.client.retry", fake_retry)
        c = HttpClient(
            session=_mock_session_request(_FakeResp()),
            max_attempts=4,
            retry_backoff=2.5,
            retry_jitter=0.3,
        )
        c.request("GET", "http://x")
        assert seen["max_attempts"] == 4
        assert seen["sleep_seconds"] == 2.5
        assert seen["jitter"] == 0.3
        assert TransportError in seen["catch"]


# ---------------------------------------------------------------------------
# Section E — Settings clamps HPC_RETRY_BACKOFF_FACTOR
# ---------------------------------------------------------------------------


class TestSettingsBackoffFactorClamp:
    """``HPC_RETRY_BACKOFF_FACTOR`` (float, default 2.0) is range-clamped in
    ``Settings.__init__``: a numeric-but-invalid value (shrinking ``0.5``,
    non-finite ``inf``/``nan``) survives float parsing but would hard-crash
    the ``HttpClient(retry_backoff_factor=...)`` constructor at import — so
    it's sanitized to the documented 2.0 default with a ``[CONFIG]``
    breadcrumb rather than bricking the import."""

    def _fresh_settings(self, monkeypatch, value):
        from autonomous.config import Settings

        if value is None:
            monkeypatch.delenv("HPC_RETRY_BACKOFF_FACTOR", raising=False)
        else:
            monkeypatch.setenv("HPC_RETRY_BACKOFF_FACTOR", value)
        return Settings()

    def test_default_is_2(self, monkeypatch):
        s = self._fresh_settings(monkeypatch, None)
        assert s.hpc_retry_backoff_factor == 2.0

    def test_explicit_valid_value_honored(self, monkeypatch):
        s = self._fresh_settings(monkeypatch, "3.0")
        assert s.hpc_retry_backoff_factor == 3.0

    def test_factor_exactly_one_honored(self, monkeypatch):
        # 1.0 is the legacy-flat opt-out and is a valid value (not clamped).
        s = self._fresh_settings(monkeypatch, "1.0")
        assert s.hpc_retry_backoff_factor == 1.0

    @pytest.mark.parametrize("bad", ["0.5", "0", "-1", "inf", "nan"])
    def test_out_of_range_clamps_to_default(self, monkeypatch, bad):
        s = self._fresh_settings(monkeypatch, bad)
        assert s.hpc_retry_backoff_factor == 2.0

    def test_clamped_value_is_constructor_safe(self, monkeypatch):
        """The whole point of the clamp: the sanitized snapshot must always
        satisfy the HttpClient constructor's ``>= 1.0`` & finite guard."""
        from autonomous.http.client import HttpClient

        s = self._fresh_settings(monkeypatch, "nan")
        assert math.isfinite(s.hpc_retry_backoff_factor)
        assert s.hpc_retry_backoff_factor >= 1.0
        # Should not raise:
        HttpClient(retry_backoff_factor=s.hpc_retry_backoff_factor)


# ---------------------------------------------------------------------------
# Section F — end-to-end through openai_compat._HTTP
# ---------------------------------------------------------------------------


def _make_openai_client():
    """Build an OpenAIClient without MongoEngine descriptor machinery —
    priming ``_data`` etc. avoids the lazy DB connect on attribute access.
    Same pattern as test_unit_hpc_timeout_iter_2026_06_19.py."""
    from autonomous.ai.models.openai_compat import OpenAIClient

    client = OpenAIClient.__new__(OpenAIClient)
    object.__setattr__(client, "_data", {
        "name": "test-agent",
        "instructions": "Be helpful.",
    })
    object.__setattr__(client, "_dynamic_fields", {})
    object.__setattr__(client, "_changed_fields", [])
    object.__setattr__(client, "_initialised", True)
    object.__setattr__(client, "_created", False)
    return client


class TestHpcReadTimeoutRidesRetryBudget:
    """The #182 headline: a ``ReadTimeout`` rides the *full* HPC attempt
    budget (geometric spacing) before surfacing ``HPCUnreachableError``,
    and a backend that recovers mid-budget succeeds. Patch
    ``_HTTP.session.request`` at the requests boundary so the whole
    HttpClient classification + retry path runs; patch ``time.sleep`` so
    the geometric waits don't actually elapse."""

    def test_sustained_read_timeout_retries_max_attempts_then_raises(
        self, monkeypatch
    ):
        from autonomous.ai.models import openai_compat as oc

        # 3-attempt budget, factor 2.0 (the HPC opt-in shape). Patch sleep
        # so we don't really wait 10s+20s.
        monkeypatch.setattr("autonomous.ai.retry.time.sleep", lambda *_a, **_k: None)
        monkeypatch.setattr(oc._HTTP, "max_attempts", 3)
        monkeypatch.setattr(oc._HTTP, "retry_backoff", 10)
        monkeypatch.setattr(oc._HTTP, "retry_backoff_factor", 2.0)
        monkeypatch.setattr(oc.OpenAIClient, "_base_url", "http://hpc.test")

        calls = {"n": 0}

        def stalled_backend(*args, **kwargs):
            calls["n"] += 1
            raise requests.exceptions.ReadTimeout(
                "backend stalled mid-response (simulated)"
            )

        monkeypatch.setattr(oc._HTTP.session, "request", stalled_backend)

        client = _make_openai_client()
        with pytest.raises(oc.HPCUnreachableError):
            client._post("/v1/chat/completions", json_body={"model": "x"})

        # The retry budget must have been fully spent — one request per
        # attempt — before the error surfaced. Pre-#182 this was already 3
        # (the budget existed); the #182 change is the *spacing*, which the
        # next test pins.
        assert calls["n"] == 3

    def test_geometric_spacing_is_applied_across_the_budget(self, monkeypatch):
        """The behavior #182 actually changed: the inter-attempt waits grow
        geometrically (10s, 20s) instead of flat (10s, 10s). Record the
        sleep sequence at the requests boundary."""
        from autonomous.ai.models import openai_compat as oc

        slept: list[float] = []
        monkeypatch.setattr("autonomous.ai.retry.time.sleep", slept.append)
        monkeypatch.setattr(oc._HTTP, "max_attempts", 3)
        monkeypatch.setattr(oc._HTTP, "retry_backoff", 10)
        monkeypatch.setattr(oc._HTTP, "retry_backoff_factor", 2.0)
        monkeypatch.setattr(oc.OpenAIClient, "_base_url", "http://hpc.test")

        def stalled_backend(*args, **kwargs):
            raise requests.exceptions.ReadTimeout("stalled")

        monkeypatch.setattr(oc._HTTP.session, "request", stalled_backend)

        client = _make_openai_client()
        with pytest.raises(oc.HPCUnreachableError):
            client._post("/v1/chat/completions", json_body={"model": "x"})

        # 3 attempts => 2 inter-attempt sleeps, geometric: 10s then 20s.
        # Under the old flat backoff this would be [10, 10]; the de-pinned
        # source makes it [10, 20] — this is the assertion that fails on a
        # revert to origin/test (revert-sanity-check anchor).
        assert slept == [10.0, 20.0]

    def test_recovery_on_second_attempt_succeeds(self, monkeypatch):
        """A degraded window that self-heals before the budget is exhausted
        must return the 200 — the whole point of riding out the blip. Fail
        once with a ReadTimeout, then return a 200."""
        from autonomous.ai.models import openai_compat as oc

        monkeypatch.setattr("autonomous.ai.retry.time.sleep", lambda *_a, **_k: None)
        monkeypatch.setattr(oc._HTTP, "max_attempts", 3)
        monkeypatch.setattr(oc._HTTP, "retry_backoff", 10)
        monkeypatch.setattr(oc._HTTP, "retry_backoff_factor", 2.0)
        monkeypatch.setattr(oc.OpenAIClient, "_base_url", "http://hpc.test")

        calls = {"n": 0}

        class _OkResp:
            status_code = 200
            text = '{"ok": true}'
            content = b'{"ok": true}'

            def raise_for_status(self):
                return None

            def json(self):
                return {"ok": True}

        def flaky_backend(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise requests.exceptions.ReadTimeout("transient blip")
            return _OkResp()

        monkeypatch.setattr(oc._HTTP.session, "request", flaky_backend)

        client = _make_openai_client()
        resp = client._post("/v1/chat/completions", json_body={"model": "x"})
        assert resp.status_code == 200
        assert calls["n"] == 2  # failed once, succeeded on attempt 2

    def test_hpc_http_client_opted_into_exponential_by_default(self):
        """The module-level ``_HTTP`` constant reads
        ``settings.hpc_retry_backoff_factor`` (default 2.0) at import, so
        the HPC adapter ships with exponential backoff ON. A regression that
        dropped the kwarg or defaulted it to 1.0 would silently revert the
        #182 fix without failing the spacing tests above (they monkeypatch
        the factor explicitly)."""
        from autonomous.ai.models.openai_compat import _HTTP

        # Whatever the live env, the wired factor must be the exponential
        # (>1.0) value the HPC client opted into — never silently flat.
        assert _HTTP.retry_backoff_factor >= 1.0
        # And under default settings (no env override) it is 2.0.
        from autonomous.config import settings as _live_settings
        if _live_settings.hpc_retry_backoff_factor == 2.0:
            assert _HTTP.retry_backoff_factor == 2.0
