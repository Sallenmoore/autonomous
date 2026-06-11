"""Independent committed coverage for PR #99 / issue #91.

PR #99 is the altitude fix the #85 flux-local narrowing addressed
symptomatically. Pre-#91, ``HttpClient.request``'s retry catch tuple
was ``(self.transport_error_cls,)``. When an adapter passed
``transport_error_cls=requests.RequestException`` (db_sync, local_model,
flux pre-#85), the tuple matched ``requests.HTTPError`` too because
HTTPError is-a RequestException — burning the retry budget on permanent
4xx responses.

The fix: ``HttpClient._attempt`` wraps ``response.raise_for_status``'s
HTTPError in a private ``_NonTransportHTTPError(Exception)`` marker
that is NOT a subclass of any plausible ``transport_error_cls``. The
retry catch tuple never matches it. ``HttpClient.request`` catches the
marker at the boundary and re-raises the original HTTPError via
``raise captured from None`` OUTSIDE the except block — Python doesn't
set ``__context__`` to the marker class, so the marker stays fully
private even from programmatic chain-walkers (sentry / structlog).

Independent perspective (no peek at dev's ``tests/_dev_local/``):
- The fail-fast contract: a 4xx never burns more than one attempt,
  regardless of ``max_attempts`` setting.
- The marker class exists and is NOT a subclass of common
  ``transport_error_cls`` choices (RequestException, ConnectionError,
  any custom RuntimeError).
- The marker class is never observed by callers — ``__cause__`` is
  None, ``__context__`` doesn't reference the marker.
- ``on_failure`` hook fires on the HTTPError attempt (observability
  contract preserved).
- Regression boundary 1: transport-class (5xx, in
  ``is_transport_failure``) STILL uses the full retry budget.
- Regression boundary 2: transport-class exception (ConnectionError)
  STILL uses the full retry budget.
- Adapter-specific pin: HttpClients built with
  ``transport_error_cls=requests.RequestException`` (the bug-shape
  case) STILL fail-fast on 4xx.
"""

from unittest.mock import MagicMock

import pytest
import requests


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, *, status=200, text="", content=b""):
        self.status_code = status
        self.text = text or f"simulated {status} body"
        self.content = content
        self._json = {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(f"{self.status_code} HTTP Error")
            err.response = self
            raise err


# ---------------------------------------------------------------------------
# Fail-fast contract — the central #91 invariant
# ---------------------------------------------------------------------------


def test_4xx_fails_after_one_attempt_with_request_exception_transport_cls(monkeypatch):
    """The flagship #91 case. A 4xx response on a client built with
    ``transport_error_cls=requests.RequestException`` (the bug-shape
    that db_sync and local_model still use) must fail after exactly
    one attempt, NOT consume the retry budget. Pre-#91 this would
    have looped 5 times because HTTPError is-a RequestException →
    matched the retry catch tuple."""
    from autonomous.http import HttpClient

    client = HttpClient(
        max_attempts=5,
        retry_backoff=0.0,
        transport_error_cls=requests.RequestException,
    )

    call_count = {"n": 0}

    def fake_request(method, url, **kwargs):
        call_count["n"] += 1
        return _FakeResponse(status=404, text="not found")

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(requests.HTTPError, match="404"):
        client.get("http://example.com")

    assert call_count["n"] == 1, (
        f"post-#91, a permanent 4xx on a RequestException-typed client "
        f"must fail after 1 attempt, not burn max_attempts=5. Got "
        f"{call_count['n']} attempts."
    )


def test_4xx_fails_fast_regardless_of_transport_error_cls(monkeypatch):
    """Belt-and-suspenders — the fail-fast contract must hold for
    every plausible ``transport_error_cls`` choice. Pin via
    parametrized adapters: HPCUnreachableError (RuntimeError),
    RequestException (the bug-shape), ConnectionError (the narrow
    fix), and a custom RuntimeError. None must consume the retry
    budget for a 4xx."""
    from autonomous.http import HttpClient

    class _CustomTransport(RuntimeError):
        pass

    for cls in [
        _CustomTransport,
        requests.RequestException,
        requests.ConnectionError,
    ]:
        client = HttpClient(
            max_attempts=4,
            retry_backoff=0.0,
            transport_error_cls=cls,
        )
        call_count = {"n": 0}

        def fake_request(method, url, **kwargs):
            call_count["n"] += 1
            return _FakeResponse(status=403, text="forbidden")

        monkeypatch.setattr(client.session, "request", fake_request)

        with pytest.raises(requests.HTTPError):
            client.get("http://example.com")

        assert call_count["n"] == 1, (
            f"4xx must fail after 1 attempt regardless of "
            f"transport_error_cls; with {cls.__name__} got "
            f"{call_count['n']} attempts."
        )


# ---------------------------------------------------------------------------
# Marker class identity + invariants
# ---------------------------------------------------------------------------


def test_non_transport_http_error_marker_exists_and_is_private():
    """Pin the marker class symbol. The marker is internal — callers
    never see it — but its identity matters for the dispatch logic.
    A regression that renamed it could silently change the dispatch
    surface (e.g. a new class with the same name in a different
    module accidentally collapses two catch sites)."""
    from autonomous.http import client

    assert hasattr(client, "_NonTransportHTTPError"), (
        "the _NonTransportHTTPError marker class must exist on the "
        "http.client module — it's the dispatch hinge for #91"
    )


def test_marker_is_not_subclass_of_common_transport_error_choices():
    """The whole #91 design hinges on the marker NOT being a subclass
    of any plausible ``transport_error_cls`` so the retry catch tuple
    never matches it. Pin all common adapter choices."""
    from autonomous.http import HttpClient, TransportError
    from autonomous.http.client import _NonTransportHTTPError

    for cls in [
        requests.RequestException,
        requests.ConnectionError,
        requests.Timeout,
        requests.HTTPError,
        TransportError,
        RuntimeError,  # base case — many adapter exception types subclass this
    ]:
        assert not issubclass(_NonTransportHTTPError, cls), (
            f"_NonTransportHTTPError must NOT be a {cls.__name__} "
            f"subclass — otherwise the retry catch tuple would match "
            f"it and #91 is regressed. Got an unexpected subclass "
            f"relationship."
        )


def test_marker_class_never_propagates_to_caller(monkeypatch):
    """Callers must see ``requests.HTTPError``, not the marker. Pin
    the unwrap at the ``HttpClient.request`` boundary works."""
    from autonomous.http import HttpClient
    from autonomous.http.client import _NonTransportHTTPError

    client = HttpClient(max_attempts=3, retry_backoff=0.0)

    def fake_request(method, url, **kwargs):
        return _FakeResponse(status=400)

    monkeypatch.setattr(client.session, "request", fake_request)

    raised = None
    try:
        client.get("http://example.com")
    except BaseException as e:
        raised = e

    assert isinstance(raised, requests.HTTPError), (
        f"caller must see requests.HTTPError; got {type(raised).__name__}"
    )
    assert not isinstance(raised, _NonTransportHTTPError), (
        f"the marker must never propagate to the caller"
    )


def test_marker_class_not_in_cause_chain_after_unwrap(monkeypatch):
    """The ``raise captured from None`` pattern sets
    ``__suppress_context__`` AND clears ``__cause__``. Verify both —
    a regression that used plain ``raise captured`` would leak the
    marker through ``__context__`` to programmatic chain-walkers
    (sentry, structlog) even though ``__suppress_context__`` hid it
    from default tracebacks."""
    from autonomous.http import HttpClient
    from autonomous.http.client import _NonTransportHTTPError

    client = HttpClient(max_attempts=3, retry_backoff=0.0)

    def fake_request(method, url, **kwargs):
        return _FakeResponse(status=401)

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(requests.HTTPError) as excinfo:
        client.get("http://example.com")

    exc = excinfo.value
    # ``__cause__`` must be None — the marker was never the cause as
    # far as Python's traceback machinery is concerned.
    assert exc.__cause__ is None, (
        f"__cause__ must be None after raise-from-None unwrap; got "
        f"{exc.__cause__!r}"
    )
    # The marker must not appear ANYWHERE in the chain — not as
    # __cause__, not as __context__ (the # 91 specific concern about
    # sentry-style introspection).
    chain = []
    walk = exc
    while walk is not None and len(chain) < 5:
        chain.append(type(walk).__name__)
        walk = getattr(walk, "__context__", None)
    assert _NonTransportHTTPError.__name__ not in chain, (
        f"the marker class must not appear in __context__ chain; got "
        f"{chain}"
    )


# ---------------------------------------------------------------------------
# Observability — on_failure hook
# ---------------------------------------------------------------------------


def test_on_failure_hook_fires_for_non_transport_http_error(monkeypatch):
    """The new try/except in ``_attempt`` for the HTTPError path calls
    ``_safe_hook(self.on_failure, ...)`` BEFORE wrapping. Pin the
    hook fires — preserves the documented contract that on_failure
    fires "on every caught exception during an attempt"."""
    from autonomous.http import HttpClient

    failures = []

    def on_failure(method, url, exc, attempt):
        failures.append((method, url, type(exc).__name__, attempt))

    client = HttpClient(
        max_attempts=3,
        retry_backoff=0.0,
        on_failure=on_failure,
    )

    def fake_request(method, url, **kwargs):
        return _FakeResponse(status=403)

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(requests.HTTPError):
        client.get("http://example.com")

    assert len(failures) == 1, (
        f"on_failure must fire exactly once for the non-transport "
        f"HTTPError attempt; got {len(failures)} fires"
    )
    method, url, exc_name, attempt = failures[0]
    assert exc_name == "HTTPError", (
        f"on_failure must see the original HTTPError, not the marker; "
        f"got {exc_name}"
    )
    assert attempt == 1


# ---------------------------------------------------------------------------
# Regression boundaries — transport-class still uses full retry budget
# ---------------------------------------------------------------------------


def test_5xx_still_uses_full_retry_budget(monkeypatch):
    """Regression boundary: a refactor that over-broadened the
    HTTPError wrap (e.g. wrapped 5xx too) would silently disable
    retry for transient server errors. Pin that 5xx STILL uses the
    full ``max_attempts``."""
    from autonomous.http import HttpClient

    client = HttpClient(max_attempts=4, retry_backoff=0.0)

    call_count = {"n": 0}

    def fake_request(method, url, **kwargs):
        call_count["n"] += 1
        return _FakeResponse(status=503)

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(Exception):
        client.get("http://example.com")

    assert call_count["n"] == 4, (
        f"5xx is transport-class via is_transport_failure(>=500); the "
        f"full retry budget (max_attempts=4) must engage. Got "
        f"{call_count['n']} attempts."
    )


def test_transport_class_exception_still_uses_full_retry_budget(monkeypatch):
    """Sibling regression boundary: a transport-class exception
    (ConnectionError) raised from ``session.request`` must STILL
    burn the full retry budget. #91's narrowing of the catch must
    not accidentally narrow the transport-class catch."""
    from autonomous.http import HttpClient, TransportError

    client = HttpClient(max_attempts=3, retry_backoff=0.0)

    call_count = {"n": 0}

    def fake_request(method, url, **kwargs):
        call_count["n"] += 1
        raise requests.ConnectionError("network unreachable")

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(TransportError):
        client.get("http://example.com")

    assert call_count["n"] == 3, (
        f"transport-class ConnectionError must use the full retry "
        f"budget; got {call_count['n']} attempts."
    )


def test_extra_codes_in_transport_failure_still_retried(monkeypatch):
    """Extras-codes (e.g. 401 for openai_compat token-revoked-as-VPN-
    drop, 429 for throttling) are explicitly transport-class. Pin
    that #91 doesn't accidentally fail-fast on these."""
    from autonomous.http import HttpClient

    client = HttpClient(
        max_attempts=3,
        retry_backoff=0.0,
        transport_failure_codes={401},
    )

    call_count = {"n": 0}

    def fake_request(method, url, **kwargs):
        call_count["n"] += 1
        return _FakeResponse(status=401)

    monkeypatch.setattr(client.session, "request", fake_request)

    with pytest.raises(Exception):
        client.get("http://example.com")

    assert call_count["n"] == 3, (
        f"401 in transport_failure_codes must use the full retry "
        f"budget; got {call_count['n']} attempts."
    )
