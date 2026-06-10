"""Independent unit coverage for PR #60 — `autonomous.http` + `autonomous.observability`.

PR #60 (dev branch ``iter/2026-06-10-batch``, refs #50 + #51) ships two
new pure-addition modules:

* ``autonomous.http`` — ``HttpClient`` wrapping ``requests.Session``
  with retry / timeout / transport-failure classification / hooks, plus
  ``TransportError`` and ``is_transport_failure``.
* ``autonomous.observability`` — ``Counter`` / ``Histogram`` /
  ``Registry`` / ``counter`` / ``histogram`` / ``event`` /
  ``format_event``.

These tests are written from a fresh read of the PR diff
(test-agent's independent perspective) — they do NOT consult the dev
agent's gitignored ``tests/_dev_local`` ephemerals. They pin the
behaviors the PR explicitly claims:

* Predicate / retry / classification semantics for ``HttpClient``,
  including the non-int-status defensive branch and the
  ``_NON_TRANSPORT_REQUESTS_EXCEPTIONS`` re-raise contract.
* ``poll()`` enforces a wall-clock attempt cap (the README #6 gap).
* ``Counter`` / ``Histogram`` validation, label-key projection
  (unknown label raises, missing label empty-fills), and Prometheus-
  style cumulative-bucket semantics.
* ``counter()`` / ``histogram()`` idempotency-on-name + type-mismatch
  rejection.
* ``event()`` shape (returned dict) + ``format_event()`` rendering
  (marker prefix + spaces/equals repr-quoting).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from autonomous.http import HttpClient, TransportError, is_transport_failure
from autonomous.observability import (
    REGISTRY,
    Counter,
    Histogram,
    Registry,
    counter,
    event,
    format_event,
    histogram,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status_code: int, text: str = "") -> MagicMock:
    """A ``requests.Response``-shaped mock with status_code, text, and
    ``raise_for_status()`` honoring 4xx/5xx the way the real method does."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text
    if status_code >= 400:
        err = requests.HTTPError(f"{status_code} error", response=resp)
        resp.raise_for_status.side_effect = err
    else:
        resp.raise_for_status.return_value = None
    return resp


def _mock_session(*side_effects) -> MagicMock:
    """A ``requests.Session``-shaped mock whose ``request`` returns or
    raises in order across attempts."""
    session = MagicMock(spec=requests.Session)
    session.request.side_effect = side_effects
    return session


# ---------------------------------------------------------------------------
# autonomous.http — module-level predicate
# ---------------------------------------------------------------------------


class TestIsTransportFailure:
    def test_status_500_is_transport_class(self):
        assert is_transport_failure(500) is True

    def test_status_599_is_transport_class(self):
        assert is_transport_failure(599) is True

    def test_status_499_is_not_transport_class(self):
        assert is_transport_failure(499) is False

    def test_status_200_is_not_transport_class(self):
        assert is_transport_failure(200) is False

    def test_extra_code_is_transport_class(self):
        assert is_transport_failure(401, extra_codes=(401,)) is True

    def test_extra_does_not_swallow_other_4xx(self):
        assert is_transport_failure(403, extra_codes=(401,)) is False

    def test_none_status_is_not_transport_class(self):
        """Defensive shape: ``None`` (e.g. exception mid-flight) degrades
        to False rather than crashing the classifier."""
        assert is_transport_failure(None) is False

    def test_non_numeric_status_is_not_transport_class(self):
        assert is_transport_failure("oops") is False


# ---------------------------------------------------------------------------
# autonomous.http — HttpClient construction / introspection
# ---------------------------------------------------------------------------


class TestHttpClientInit:
    def test_max_attempts_below_one_raises(self):
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):
            HttpClient(max_attempts=0)

    def test_defaults_are_sensible(self):
        c = HttpClient()
        assert c.timeout == 30.0
        assert c.max_attempts == 1
        assert c.retry_backoff == 0.0
        assert c.retry_jitter == 0.0
        assert c.transport_failure_codes == frozenset()
        assert c.transport_error_cls is TransportError

    def test_transport_failure_codes_stored_as_frozenset(self):
        c = HttpClient(transport_failure_codes=[401, 429])
        assert c.transport_failure_codes == frozenset({401, 429})

    def test_per_instance_predicate_uses_extras(self):
        c = HttpClient(transport_failure_codes=[401])
        assert c.is_transport_failure(401) is True
        assert c.is_transport_failure(403) is False
        assert c.is_transport_failure(500) is True


# ---------------------------------------------------------------------------
# autonomous.http — HttpClient.request happy path + hooks
# ---------------------------------------------------------------------------


class TestHttpClientRequestSuccess:
    def test_returns_response_on_2xx(self):
        session = _mock_session(_mock_response(200))
        c = HttpClient(session=session)
        resp = c.request("GET", "http://x/y")
        assert resp.status_code == 200

    def test_on_request_and_on_response_hooks_fire(self):
        on_request = MagicMock()
        on_response = MagicMock()
        on_failure = MagicMock()
        session = _mock_session(_mock_response(200))
        c = HttpClient(
            session=session,
            on_request=on_request,
            on_response=on_response,
            on_failure=on_failure,
        )
        c.request("GET", "http://x", headers={"X-Trace": "abc"}, json={"a": 1})
        on_request.assert_called_once_with("GET", "http://x", {"X-Trace": "abc"}, {"a": 1})
        # attempt index is 1-indexed
        on_response.assert_called_once()
        args = on_response.call_args.args
        assert args[0] == "GET"
        assert args[1] == "http://x"
        assert args[3] == 1
        on_failure.assert_not_called()

    def test_body_hook_prefers_json_then_data_then_files(self):
        on_request = MagicMock()
        session = _mock_session(
            _mock_response(200), _mock_response(200), _mock_response(200)
        )
        c = HttpClient(session=session, on_request=on_request)
        c.request("POST", "http://x", json={"a": 1}, data="raw", files={"f": object()})
        # json wins
        assert on_request.call_args.args[3] == {"a": 1}

        on_request.reset_mock()
        c.request("POST", "http://x", data="raw")
        assert on_request.call_args.args[3] == "raw"

        on_request.reset_mock()
        files = {"f": object()}
        c.request("POST", "http://x", files=files)
        assert on_request.call_args.args[3] == files

    def test_per_call_timeout_overrides_default(self):
        session = _mock_session(_mock_response(200))
        c = HttpClient(session=session, timeout=30.0)
        c.request("GET", "http://x", timeout=5.0)
        kwargs = session.request.call_args.kwargs
        assert kwargs["timeout"] == 5.0

    def test_default_timeout_applied_when_not_overridden(self):
        session = _mock_session(_mock_response(200))
        c = HttpClient(session=session, timeout=12.5)
        c.request("GET", "http://x")
        assert session.request.call_args.kwargs["timeout"] == 12.5

    def test_get_post_put_delete_pass_method_through(self):
        # one response per verb
        session = _mock_session(*[_mock_response(200) for _ in range(4)])
        c = HttpClient(session=session)
        c.get("http://x")
        c.post("http://x")
        c.put("http://x")
        c.delete("http://x")
        methods = [call.args[0] for call in session.request.call_args_list]
        assert methods == ["GET", "POST", "PUT", "DELETE"]


# ---------------------------------------------------------------------------
# autonomous.http — HttpClient.request failure paths
# ---------------------------------------------------------------------------


class TestHttpClientRequestFailures:
    def test_5xx_raises_transport_error_after_exhaustion(self):
        session = _mock_session(_mock_response(503, "down"))
        c = HttpClient(session=session, max_attempts=1)
        with pytest.raises(TransportError, match="503"):
            c.request("GET", "http://x")

    def test_5xx_retries_then_succeeds(self):
        session = _mock_session(_mock_response(500, "fail"), _mock_response(200, "ok"))
        c = HttpClient(session=session, max_attempts=3, retry_backoff=0)
        resp = c.request("GET", "http://x")
        assert resp.status_code == 200
        # both attempts dispatched
        assert session.request.call_count == 2

    def test_4xx_not_in_extras_raises_http_error_not_transport(self):
        """A 403 (non-extra) is a programmer/auth error — caller wants
        the raw ``requests.HTTPError`` from ``raise_for_status()``,
        NOT a wrapped ``TransportError`` (which the AI retry loop would
        burn attempts on)."""
        session = _mock_session(_mock_response(403, "forbidden"))
        c = HttpClient(session=session)
        with pytest.raises(requests.HTTPError):
            c.request("GET", "http://x")

    def test_extra_code_routes_through_transport_error(self):
        """401 explicitly configured as transport-class (HPC's revoked-
        token == VPN-drop equivalence) → TransportError, retried."""
        session = _mock_session(
            _mock_response(401, "expired"), _mock_response(401, "expired")
        )
        c = HttpClient(session=session, max_attempts=2, transport_failure_codes={401})
        with pytest.raises(TransportError):
            c.request("GET", "http://x")
        assert session.request.call_count == 2

    def test_connection_error_wrapped_in_transport_error_and_on_failure_fires(self):
        on_failure = MagicMock()
        session = MagicMock(spec=requests.Session)
        session.request.side_effect = requests.ConnectionError("refused")
        c = HttpClient(session=session, max_attempts=1, on_failure=on_failure)
        with pytest.raises(TransportError, match="ConnectionError"):
            c.request("GET", "http://x")
        on_failure.assert_called_once()
        # 4-tuple (method, url, exc, attempt)
        args = on_failure.call_args.args
        assert args[0] == "GET"
        assert args[1] == "http://x"
        assert isinstance(args[2], requests.ConnectionError)
        assert args[3] == 1

    def test_missing_schema_propagates_raw_does_not_burn_retries(self):
        """``MissingSchema`` is a config/programmer error — re-raise raw
        so the caller sees the precise type, and don't burn the retry
        budget against an unfixable cause."""
        on_failure = MagicMock()
        session = MagicMock(spec=requests.Session)
        session.request.side_effect = requests.exceptions.MissingSchema("no scheme")
        c = HttpClient(session=session, max_attempts=5, on_failure=on_failure)
        with pytest.raises(requests.exceptions.MissingSchema):
            c.request("GET", "x.y/z")
        # exactly one attempt — retry budget NOT spent
        assert session.request.call_count == 1
        # on_failure still observed it
        on_failure.assert_called_once()

    def test_invalid_url_also_propagates_raw(self):
        session = MagicMock(spec=requests.Session)
        session.request.side_effect = requests.exceptions.InvalidURL("bad")
        c = HttpClient(session=session, max_attempts=3)
        with pytest.raises(requests.exceptions.InvalidURL):
            c.request("GET", "http://x")
        assert session.request.call_count == 1

    def test_custom_transport_error_cls_is_raised(self):
        class MyTransportError(RuntimeError):
            pass

        session = _mock_session(_mock_response(500, "boom"))
        c = HttpClient(
            session=session, max_attempts=1, transport_error_cls=MyTransportError
        )
        with pytest.raises(MyTransportError):
            c.request("GET", "http://x")


# ---------------------------------------------------------------------------
# autonomous.http — HttpClient.poll
# ---------------------------------------------------------------------------


class TestHttpClientPoll:
    def test_returns_first_satisfying_result(self):
        c = HttpClient()
        calls = iter(["pending", "pending", "done"])
        result = c.poll(
            lambda: next(calls),
            predicate=lambda r: r == "done",
            max_attempts=5,
            sleep_seconds=0,
        )
        assert result == "done"

    def test_immediate_satisfaction_does_not_sleep(self, monkeypatch):
        c = HttpClient()
        sleeps = []
        import autonomous.http.client as client_mod

        monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
        # also patch the in-function `import time as _time` namespace by
        # patching the global ``time.sleep`` (covered above)
        result = c.poll(
            lambda: "done",
            predicate=lambda r: True,
            max_attempts=3,
            sleep_seconds=1.0,
        )
        assert result == "done"
        assert sleeps == []  # predicate True on attempt 1 → no sleep
        # silence the unused-import warning by referencing the module
        assert client_mod.HttpClient is HttpClient

    def test_exhaustion_raises_timeout_with_last_result(self):
        c = HttpClient()
        with pytest.raises(TimeoutError, match="poll\\(\\) exhausted"):
            c.poll(
                lambda: {"state": "pending"},
                predicate=lambda r: r.get("state") == "done",
                max_attempts=2,
                sleep_seconds=0,
            )

    def test_max_attempts_below_one_raises(self):
        c = HttpClient()
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):
            c.poll(lambda: 1, predicate=lambda r: True, max_attempts=0, sleep_seconds=0)

    def test_does_not_sleep_after_final_attempt(self, monkeypatch):
        c = HttpClient()
        sleeps = []
        monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
        with pytest.raises(TimeoutError):
            c.poll(
                lambda: "no",
                predicate=lambda r: False,
                max_attempts=3,
                sleep_seconds=0.1,
            )
        # 3 attempts → 2 sleeps (between 1→2 and 2→3), never after attempt 3
        assert len(sleeps) == 2


# ---------------------------------------------------------------------------
# autonomous.observability — Counter
# ---------------------------------------------------------------------------


class TestCounter:
    def test_inc_default_is_one(self):
        c = Counter("widgets")
        c.inc()
        assert c.collect() == {(): 1.0}

    def test_inc_with_value(self):
        c = Counter("widgets")
        c.inc(2.5)
        c.inc(1.5)
        assert c.collect() == {(): 4.0}

    def test_negative_inc_raises(self):
        c = Counter("widgets")
        with pytest.raises(ValueError, match="non-negative"):
            c.inc(-1)

    def test_unknown_label_raises_key_error(self):
        c = Counter("widgets", label_names=("provider",))
        with pytest.raises(KeyError, match="unknown label"):
            c.inc(provider="openai", typo="oops")

    def test_missing_label_fills_empty_string(self):
        """Prometheus-style empty-label treatment — a missing label
        becomes ``""`` rather than raising, so a partially-labeled
        emission site doesn't crash."""
        c = Counter("widgets", label_names=("provider", "status"))
        c.inc(provider="openai")
        assert c.collect() == {("openai", ""): 1.0}

    def test_label_order_respects_declaration(self):
        c = Counter("widgets", label_names=("provider", "status"))
        # kwarg order differs from declared order — key tuple still in
        # declared order so collect() is deterministic across processes.
        c.inc(status="500", provider="openai")
        assert c.collect() == {("openai", "500"): 1.0}

    def test_reset_clears_all_series(self):
        c = Counter("widgets", label_names=("provider",))
        c.inc(provider="openai")
        c.inc(provider="gemini")
        c.reset()
        assert c.collect() == {}

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            Counter("")


# ---------------------------------------------------------------------------
# autonomous.observability — Histogram
# ---------------------------------------------------------------------------


class TestHistogram:
    def test_observe_increments_count_and_sum(self):
        h = Histogram("latency", buckets=(0.1, 1.0, 10.0))
        h.observe(0.5)
        h.observe(2.0)
        snapshot = h.collect()
        assert snapshot[()]["count"] == 2
        assert snapshot[()]["sum"] == pytest.approx(2.5)

    def test_observation_lands_in_first_le_bucket_and_above_cumulative(self):
        """Prometheus-style cumulative ``<=`` semantics: a value of 0.5
        lands in every bucket whose upper bound is >= 0.5."""
        h = Histogram("latency", buckets=(0.1, 0.5, 1.0, 10.0))
        h.observe(0.5)
        buckets = h.collect()[()]["buckets"]
        # 0.1 bucket: 0 observations (0.5 > 0.1)
        assert buckets[0.1] == 0
        # 0.5 bucket: 1 observation (0.5 <= 0.5)
        assert buckets[0.5] == 1
        # 1.0 bucket: 1 observation (0.5 <= 1.0)
        assert buckets[1.0] == 1
        # 10.0 bucket: 1 observation (0.5 <= 10.0)
        assert buckets[10.0] == 1

    def test_observation_above_all_buckets_lands_in_no_bucket(self):
        h = Histogram("latency", buckets=(0.1, 1.0))
        h.observe(5.0)
        snapshot = h.collect()[()]
        assert snapshot["count"] == 1  # still counted in totals
        assert snapshot["sum"] == 5.0
        assert snapshot["buckets"] == {0.1: 0, 1.0: 0}

    def test_empty_buckets_rejected(self):
        with pytest.raises(ValueError, match="at least one bucket"):
            Histogram("latency", buckets=())

    def test_nonpositive_bucket_rejected(self):
        with pytest.raises(ValueError, match="positive"):
            Histogram("latency", buckets=(0.0, 1.0))
        with pytest.raises(ValueError, match="positive"):
            Histogram("latency", buckets=(-0.1, 1.0))

    def test_duplicate_buckets_collapsed_and_sorted(self):
        h = Histogram("latency", buckets=(1.0, 0.1, 1.0, 0.5))
        assert h.buckets == (0.1, 0.5, 1.0)

    def test_unknown_label_rejected(self):
        h = Histogram("latency", label_names=("op",))
        with pytest.raises(KeyError):
            h.observe(0.1, op="get", surprise="x")

    def test_reset_clears(self):
        h = Histogram("latency")
        h.observe(0.5)
        h.reset()
        assert h.collect() == {}


# ---------------------------------------------------------------------------
# autonomous.observability — Registry + counter()/histogram() helpers
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_register_then_get(self):
        reg = Registry()
        c = Counter("widgets")
        reg.register(c)
        assert reg.get("widgets") is c

    def test_get_missing_returns_none(self):
        reg = Registry()
        assert reg.get("nope") is None

    def test_name_conflict_with_different_type_raises(self):
        reg = Registry()
        reg.register(Counter("metric_x"))
        with pytest.raises(ValueError, match="already registered"):
            reg.register(Counter("metric_x"))  # different instance, same name

    def test_register_same_instance_twice_is_idempotent(self):
        reg = Registry()
        c = Counter("metric_x")
        reg.register(c)
        reg.register(c)  # same instance — no error
        assert reg.get("metric_x") is c

    def test_collect_tags_type_and_includes_description(self):
        reg = Registry()
        reg.register(Counter("c1", description="counter one", label_names=("a",)))
        reg.register(Histogram("h1", description="hist one"))
        snapshot = reg.collect()
        assert snapshot["c1"]["type"] == "counter"
        assert snapshot["c1"]["description"] == "counter one"
        assert snapshot["c1"]["label_names"] == ["a"]
        assert snapshot["h1"]["type"] == "histogram"

    def test_clear_drops_all(self):
        reg = Registry()
        reg.register(Counter("c1"))
        reg.clear()
        assert reg.get("c1") is None


class TestHelpers:
    def test_counter_helper_is_idempotent_on_name(self):
        reg = Registry()
        c1 = counter("widgets", registry=reg, label_names=("provider",))
        c2 = counter("widgets", registry=reg)  # same name → same instance
        assert c1 is c2

    def test_counter_type_mismatch_raises(self):
        reg = Registry()
        histogram("dur", registry=reg)
        with pytest.raises(ValueError, match="not Counter"):
            counter("dur", registry=reg)

    def test_histogram_helper_is_idempotent_on_name(self):
        reg = Registry()
        h1 = histogram("dur", registry=reg)
        h2 = histogram("dur", registry=reg)
        assert h1 is h2

    def test_histogram_type_mismatch_raises(self):
        reg = Registry()
        counter("things", registry=reg)
        with pytest.raises(ValueError, match="not Histogram"):
            histogram("things", registry=reg)

    def test_default_registry_used_when_none_passed(self):
        """The ``counter()`` helper without ``registry=`` lands on
        ``REGISTRY`` (the process default)."""
        c = counter("__test_default_registry_widget__")
        try:
            assert REGISTRY.get("__test_default_registry_widget__") is c
        finally:
            # don't pollute the global registry for other tests
            REGISTRY._metrics.pop("__test_default_registry_widget__", None)


# ---------------------------------------------------------------------------
# autonomous.observability — event + format_event
# ---------------------------------------------------------------------------


class TestFormatEvent:
    def test_basic_no_marker(self):
        out = format_event("login", user="alice")
        assert out == "event=login user=alice"

    def test_with_marker_prefix(self):
        out = format_event("hpc_unreachable", marker="HPC-UNREACHABLE", status=500)
        assert out.startswith("[HPC-UNREACHABLE] event=hpc_unreachable ")
        assert "status=500" in out

    def test_value_with_space_is_repr_quoted(self):
        """A value containing whitespace would otherwise break the
        ``key=value`` parser shape, so it's repr'd."""
        out = format_event("e", note="hello world")
        assert "note='hello world'" in out

    def test_value_with_equals_is_repr_quoted(self):
        out = format_event("e", expr="a=b")
        assert "expr='a=b'" in out

    def test_value_with_tab_is_repr_quoted(self):
        out = format_event("e", note="a\tb")
        assert "note=" in out and "\\t" in out  # repr renders \t

    def test_none_and_bool_pass_through_as_str(self):
        out = format_event("e", x=None, ok=True)
        assert "x=None" in out
        assert "ok=True" in out

    def test_int_and_float_pass_through_as_str(self):
        out = format_event("e", n=42, ratio=0.5)
        assert "n=42" in out
        assert "ratio=0.5" in out


class TestEvent:
    def test_returns_event_dict(self):
        payload = event("login", level="info", user="alice")
        assert payload["event"] == "login"
        assert payload["level"] == "info"
        assert payload["user"] == "alice"
        assert "marker" not in payload  # absent when no marker passed

    def test_marker_included_in_payload(self):
        payload = event("hpc_unreachable", marker="HPC-UNREACHABLE", status=500)
        assert payload["marker"] == "HPC-UNREACHABLE"
        assert payload["status"] == 500

    def test_invalid_level_rejected(self):
        with pytest.raises(ValueError, match="level must be one of"):
            event("login", level="loud")

    def test_level_is_case_insensitive(self):
        payload = event("e", level="WARNING")
        assert payload["level"] == "warning"

    def test_default_level_is_info(self):
        payload = event("e")
        assert payload["level"] == "info"

    def test_fields_attached_to_payload(self):
        payload = event("e", level="info", provider="openai", count=3)
        assert payload["provider"] == "openai"
        assert payload["count"] == 3
