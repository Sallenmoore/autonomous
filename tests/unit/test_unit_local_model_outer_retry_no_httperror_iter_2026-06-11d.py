"""Independent committed coverage for PR #108 (closes #97, #106).

PR #108 narrows ``LocalAIModel.generate_json``'s outer ``retry()`` catch
tuple from the broad ``requests.RequestException`` to two concrete
transient classes::

    catch=(
        requests.ConnectionError,
        requests.Timeout,
        json.JSONDecodeError,
        ValueError,
        KeyError,
    )

The fix prevents a permanent 4xx ``HTTPError`` (a ``RequestException``
subclass) from being re-caught by the outer wrapper and re-attempted up
to ``max_attempts=3``. The same fail-fast violation #91/#99 fixed at the
HttpClient transport layer, recurring here at the outer-caller altitude.

INDEPENDENT PERSPECTIVE — these tests deliberately complement, rather
than mirror, the dev agent's gitignored ``tests/_dev_local`` coverage.
The angles emphasized here:

1. Source-level catch-tuple pin (regex over generate_json's source) so
   a sympathy-driven re-introduction of ``RequestException`` anywhere
   in the tuple is loud at unit time.
2. The ``requests`` class hierarchy assumptions the narrowed tuple
   implicitly relies on — ProxyError/SSLError must remain
   ConnectionError subclasses, ConnectTimeout/ReadTimeout must remain
   Timeout subclasses, HTTPError must remain a non-Connection /
   non-Timeout RequestException subclass, ChunkedEncodingError must
   remain a non-Connection / non-Timeout RequestException subclass.
   A future ``requests`` release re-parenting any of these would
   silently flip PR #108's behavior; pin them as unit-level claims.
3. The documented trade in the PR body — bare ``ChunkedEncodingError``
   is no longer retried by the outer wrapper. Probed end-to-end so a
   future revert that widens the catch back to ``RequestException``
   trips a behavior test, not just the source-pin.
4. The hierarchy claim exercised end-to-end via ``ProxyError`` (a
   ``ConnectionError`` subclass): still retried 3x, proving the
   subclass-aware tuple semantics survive the narrowing.

Out of scope here (covered elsewhere or by dev's ephemerals):
- The schema-absorption / structured-outputs log path
  (tests/unit/test_unit_local_model_json_schema.py).
- HttpClient-internal _RetryableHTTPError marker semantics
  (tests/unit/test_unit_http_nontransport_http_error_iter_2026-06-11c.py).
- JSONDecodeError / ValueError translation to GenerateJSONParseError /
  GenerateJSONEmptyResponseError (dev's ephemeral coverage).
"""

import inspect
import re

import pytest
import requests

from autonomous.ai.models import local_model
from autonomous.ai.models.local_model import LocalAIModel


# ---------------------------------------------------------------------------
# Bare LocalAIModel factory — mirrors the pattern in
# tests/unit/test_unit_local_model_json_schema.py so the test-agent
# coverage stays consistent with the rest of the LocalAIModel unit tier.
# ---------------------------------------------------------------------------


def _local():
    inst = LocalAIModel.__new__(LocalAIModel)
    object.__setattr__(inst, "_data", {"instructions": "x", "name": "t"})
    object.__setattr__(inst, "_dynamic_fields", {})
    object.__setattr__(inst, "_changed_fields", [])
    object.__setattr__(inst, "_initialised", True)
    object.__setattr__(inst, "_created", False)
    # Pin retry sleep to 0 so attempt-count probes don't burn wall time.
    object.__setattr__(inst, "_retry_sleep", 0.0)
    object.__setattr__(inst, "_text_model", "m")
    object.__setattr__(inst, "_ollama_url", "http://stub:11434")
    object.__setattr__(inst, "_context_limit", 1024)
    object.__setattr__(inst, "_json_timeout", 5)
    return inst


def _patch_post(monkeypatch, side_effect):
    """Replace local_model._HTTP.post with a counting fake.

    ``side_effect`` may be:
    - an exception class (instantiated with a fake message and raised)
    - a callable taking the call-log list and returning a stub Response
    """
    calls = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        if isinstance(side_effect, type) and issubclass(
            side_effect, BaseException
        ):
            raise side_effect("fake post failure")
        return side_effect(calls)

    monkeypatch.setattr(local_model._HTTP, "post", fake_post)
    return calls


def _patch_autotasks(monkeypatch):
    """Stub AutoTasks().get_current_task() so the rq/Redis path is
    never touched in unit context."""

    class _Stub:
        def get_current_task(self):
            return None

    monkeypatch.setattr(local_model, "AutoTasks", lambda: _Stub())


def _patch_flush_memory(monkeypatch):
    """_on_retry calls self.flush_memory(self._text_model) which
    issues its own HTTP request. For attempt-count probes that retry,
    no-op the flush so it doesn't pollute the call log."""
    monkeypatch.setattr(
        local_model.LocalAIModel,
        "flush_memory",
        lambda self, model: None,
    )


# ---------------------------------------------------------------------------
# 1. Source-level catch-tuple pin — revert canary.
# ---------------------------------------------------------------------------


class TestCatchTupleSourcePin:
    def test_catch_tuple_drops_request_exception(self):
        """The post-#108 catch tuple must NOT contain
        ``requests.RequestException`` — that's the regression #97/#106
        reported. Narrowed to just the catch=(...) block so the same
        identifier appearing in a docstring or comment is fine."""
        src = inspect.getsource(LocalAIModel.generate_json)
        catch_block = re.search(r"catch=\(([^)]*)\)", src, re.DOTALL)
        assert catch_block is not None, (
            "could not locate catch=(...) tuple in generate_json source"
        )
        catch_str = catch_block.group(1)
        assert "RequestException" not in catch_str, (
            f"requests.RequestException re-introduced in catch tuple — "
            f"regression of #97/#106. catch=({catch_str})"
        )
        assert "ConnectionError" in catch_str
        assert "Timeout" in catch_str

    def test_catch_tuple_keeps_parse_exceptions(self):
        """JSONDecodeError / ValueError / KeyError remain in the catch
        tuple — they aren't transport but they ARE retried at this
        altitude because a memory-flushed model may emit valid JSON on
        the next attempt."""
        src = inspect.getsource(LocalAIModel.generate_json)
        catch_block = re.search(r"catch=\(([^)]*)\)", src, re.DOTALL)
        catch_str = catch_block.group(1)
        for name in ("JSONDecodeError", "ValueError", "KeyError"):
            assert name in catch_str, (
                f"{name} missing from catch tuple — parse-failure retry "
                f"path lost"
            )


# ---------------------------------------------------------------------------
# 2. requests class hierarchy assumptions PR #108 implicitly relies on.
# ---------------------------------------------------------------------------


class TestRequestsHierarchyAssumptions:
    def test_proxy_error_is_connection_error(self):
        """ProxyError stays retried because it's a ConnectionError
        subclass. If ``requests`` ever re-parents it, PR #108's catch
        tuple silently drops proxy failures from retry — flag here."""
        assert issubclass(
            requests.exceptions.ProxyError, requests.ConnectionError
        )

    def test_ssl_error_is_connection_error(self):
        assert issubclass(
            requests.exceptions.SSLError, requests.ConnectionError
        )

    def test_connect_timeout_covered_by_both_branches(self):
        """ConnectTimeout has a double-parent identity. PR #108's catch
        tuple covers it via either branch; pin both so a future
        single-parent refactor in ``requests`` surfaces here."""
        assert issubclass(requests.ConnectTimeout, requests.Timeout)
        assert issubclass(
            requests.ConnectTimeout, requests.ConnectionError
        )

    def test_read_timeout_is_timeout(self):
        assert issubclass(
            requests.exceptions.ReadTimeout, requests.Timeout
        )

    def test_http_error_is_request_exception_only(self):
        """The whole point of #97/#106: HTTPError is a RequestException
        but NOT a ConnectionError nor a Timeout. With #108's narrowed
        catch tuple it falls through cleanly. A future ``requests``
        release that re-parents HTTPError under a transient class would
        silently break the fail-fast contract this PR establishes."""
        assert issubclass(requests.HTTPError, requests.RequestException)
        assert not issubclass(requests.HTTPError, requests.ConnectionError)
        assert not issubclass(requests.HTTPError, requests.Timeout)

    def test_chunked_encoding_error_is_request_exception_only(self):
        """ChunkedEncodingError is the documented-trade case in PR
        #108's body: a RequestException that is NEITHER a
        ConnectionError nor a Timeout, so the narrower catch tuple
        deliberately drops it. Pin the hierarchy so the trade stays
        well-defined."""
        cee = requests.exceptions.ChunkedEncodingError
        assert issubclass(cee, requests.RequestException)
        assert not issubclass(cee, requests.ConnectionError)
        assert not issubclass(cee, requests.Timeout)


# ---------------------------------------------------------------------------
# 3. End-to-end behavior — HTTPError fails fast at the outer altitude.
# ---------------------------------------------------------------------------


class TestHTTPErrorFailsFast:
    def test_4xx_http_error_propagates_after_one_attempt(self, monkeypatch):
        """The PR's core claim. A 4xx HTTPError surfaces unwrapped
        (NOT translated to GenerateJSONParseError /
        GenerateJSONEmptyResponseError) — the except chain after
        retry() only catches JSONDecodeError / ValueError / KeyError."""
        _patch_autotasks(monkeypatch)
        local = _local()

        class _StubResponse:
            status_code = 404

            def raise_for_status(self):
                raise requests.HTTPError("404 Not Found", response=self)

            def json(self):
                return {}

        calls = _patch_post(monkeypatch, lambda _c: _StubResponse())

        with pytest.raises(requests.HTTPError):
            LocalAIModel.generate_json(local, "prompt")

        assert len(calls) == 1, (
            f"4xx HTTPError must NOT trigger outer-retry; got "
            f"{len(calls)} attempts"
        )

    def test_5xx_http_error_also_fails_fast(self, monkeypatch):
        """The PR body explicitly notes 5xx retry policy lives at the
        HttpClient transport layer, not the outer wrapper. So a 5xx
        HTTPError surfacing at this altitude — meaning HttpClient
        already gave up — also fails fast here. Pins the
        altitude-of-responsibility split."""
        _patch_autotasks(monkeypatch)
        local = _local()

        class _StubResponse5xx:
            status_code = 500

            def raise_for_status(self):
                raise requests.HTTPError("500 Internal", response=self)

            def json(self):
                return {}

        calls = _patch_post(monkeypatch, lambda _c: _StubResponse5xx())

        with pytest.raises(requests.HTTPError):
            LocalAIModel.generate_json(local, "prompt")

        assert len(calls) == 1


# ---------------------------------------------------------------------------
# 4. The documented trade — ChunkedEncodingError no longer retried.
# ---------------------------------------------------------------------------


class TestChunkedEncodingErrorDocumentedTrade:
    def test_chunked_encoding_error_fails_fast(self, monkeypatch):
        """ChunkedEncodingError is the documented trade in PR #108: a
        RequestException that is neither ConnectionError nor Timeout,
        so the narrower catch tuple drops it. A future revert that
        re-widens the catch to RequestException would silently restore
        the 3-attempt budget for this class — this test pins the
        trade explicitly."""
        _patch_autotasks(monkeypatch)
        local = _local()

        calls = _patch_post(
            monkeypatch, requests.exceptions.ChunkedEncodingError
        )

        with pytest.raises(requests.exceptions.ChunkedEncodingError):
            LocalAIModel.generate_json(local, "prompt")

        assert len(calls) == 1, (
            "ChunkedEncodingError is the documented trade in PR #108 "
            "— must NOT be retried at the outer wrapper"
        )


# ---------------------------------------------------------------------------
# 5. Classes the narrowed tuple still covers still retry 3x.
#    Also exercises the hierarchy claim end-to-end via ProxyError.
# ---------------------------------------------------------------------------


class TestStillRetriedClasses:
    def test_connection_error_retries_three_times(self, monkeypatch):
        _patch_autotasks(monkeypatch)
        _patch_flush_memory(monkeypatch)
        local = _local()

        calls = _patch_post(monkeypatch, requests.ConnectionError)

        with pytest.raises(requests.ConnectionError):
            LocalAIModel.generate_json(local, "prompt")

        assert len(calls) == 3

    def test_timeout_retries_three_times(self, monkeypatch):
        _patch_autotasks(monkeypatch)
        _patch_flush_memory(monkeypatch)
        local = _local()

        calls = _patch_post(monkeypatch, requests.Timeout)

        with pytest.raises(requests.Timeout):
            LocalAIModel.generate_json(local, "prompt")

        assert len(calls) == 3

    def test_proxy_error_retries_via_connection_subclass(self, monkeypatch):
        """ProxyError → ConnectionError subclass → caught by the
        narrowed tuple → still retried. This is the hierarchy
        guarantee from TestRequestsHierarchyAssumptions exercised
        end-to-end. A regression that special-cased ConnectionError to
        ``type(exc) is ConnectionError`` (no subclass) would pass the
        hierarchy test but break this one."""
        _patch_autotasks(monkeypatch)
        _patch_flush_memory(monkeypatch)
        local = _local()

        calls = _patch_post(
            monkeypatch, requests.exceptions.ProxyError
        )

        with pytest.raises(requests.exceptions.ProxyError):
            LocalAIModel.generate_json(local, "prompt")

        assert len(calls) == 3


# ---------------------------------------------------------------------------
# 6. Production wrap-path probes — patch _HTTP.session.request so
#    HttpClient's transport_error_cls wrap actually fires.
#
# Patching _HTTP.post (sections 3-5 above) lets the test author raise
# any class they want, bypassing HttpClient's wrap. That's the right
# shape for pinning the outer retry's catch-tuple SEMANTICS, but it
# doesn't model what really arrives at the outer retry in production:
# HttpClient catches the inner ``requests.RequestException`` and
# re-raises ``self.transport_error_cls(message)`` — an instance of the
# WRAP CLASS, not of the original exception's class.
#
# These tests pin the WRAP CONTRACT: with transport_error_cls=
# requests.ConnectionError (mirrors flux #85), the wrap is itself a
# ConnectionError subclass instance, so the outer retry's narrowed
# catch tuple (ConnectionError, Timeout, ...) still matches and real
# transient transport failures retry 3x. Before the #97/#106 follow-up
# the wrap was base ``RequestException(msg)`` — neither a
# ConnectionError nor a Timeout subclass instance — and the outer
# catch tuple silently stopped matching, dropping real transport
# failures from 3 attempts to 1.
# ---------------------------------------------------------------------------


def _patch_session_request(monkeypatch, exc_to_raise):
    """Patch the transport seam ONE level deeper than _HTTP.post so
    HttpClient's transport_error_cls wrap actually fires. Returns a
    call counter dict whose ``n`` key is incremented on every attempt
    that reaches the wire."""
    calls = {"n": 0}

    def fake_request(method, url, **kwargs):
        calls["n"] += 1
        raise exc_to_raise

    monkeypatch.setattr(local_model._HTTP.session, "request", fake_request)
    return calls


class TestProductionWrapPath:
    def test_real_connection_error_retries_three_times_via_wrap(
        self, monkeypatch
    ):
        """Real production path: session.request raises ConnectionError,
        HttpClient wraps via transport_error_cls, outer retry catches
        the wrap and retries. With transport_error_cls=
        requests.ConnectionError (post-#97/#106), the wrap is itself a
        ConnectionError instance, so the outer (ConnectionError,
        Timeout, ...) catch tuple matches. Pre-#97/#106 the wrap was
        base RequestException, which the narrowed tuple did NOT match
        — this test would have failed before the follow-up."""
        _patch_autotasks(monkeypatch)
        _patch_flush_memory(monkeypatch)
        local = _local()

        calls = _patch_session_request(
            monkeypatch,
            requests.ConnectionError("network unreachable"),
        )

        with pytest.raises(requests.ConnectionError):
            LocalAIModel.generate_json(local, "prompt")

        assert calls["n"] == 3, (
            f"real ConnectionError must retry 3x via the wrap; got "
            f"{calls['n']} attempt(s) — likely a transport_error_cls "
            f"regression that broke wrap-instance ↔ catch-tuple match"
        )

    def test_real_timeout_retries_three_times_via_wrap(self, monkeypatch):
        """Real production path: session.request raises Timeout. With
        transport_error_cls=requests.ConnectionError the wrap is a
        ConnectionError instance — type is erased but retry budget is
        preserved. Same trade flux #85 made. If a future refactor
        widens transport_error_cls back to RequestException without
        widening the outer catch, this test fails."""
        _patch_autotasks(monkeypatch)
        _patch_flush_memory(monkeypatch)
        local = _local()

        calls = _patch_session_request(
            monkeypatch, requests.Timeout("ollama too slow")
        )

        with pytest.raises(requests.ConnectionError):
            LocalAIModel.generate_json(local, "prompt")

        assert calls["n"] == 3, (
            f"real Timeout must retry 3x via the wrap; got "
            f"{calls['n']} attempt(s)"
        )

    def test_real_http_error_still_fails_fast_via_unwrap(self, monkeypatch):
        """Real production path: session.request returns a 4xx
        response, HttpClient's ``_NonTransportHTTPError`` marker
        unwraps + re-raises the original HTTPError outside its retry
        catch. That HTTPError reaches the outer retry as a
        RequestException (not a ConnectionError/Timeout subclass), so
        the narrowed catch tuple drops it → 1 attempt. End-to-end
        proof the #91/#99 marker-pattern + #108 narrowing + #97/#106
        wrap-class fix compose correctly."""
        _patch_autotasks(monkeypatch)
        local = _local()

        class _Response404:
            status_code = 404
            text = "not found"
            headers = {}

            def raise_for_status(self):
                raise requests.HTTPError("404 Not Found", response=self)

            def json(self):
                return {}

        calls = {"n": 0}

        def fake_request(method, url, **kwargs):
            calls["n"] += 1
            return _Response404()

        monkeypatch.setattr(
            local_model._HTTP.session, "request", fake_request
        )

        with pytest.raises(requests.HTTPError):
            LocalAIModel.generate_json(local, "prompt")

        assert calls["n"] == 1, (
            f"4xx HTTPError must NOT retry at any layer; got "
            f"{calls['n']} attempt(s) — likely the #91/#99 marker "
            f"regressed or the outer catch widened"
        )
