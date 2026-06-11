"""Independent coverage for issues #78 (default-equivalence) and #79
(runtime dispatch) — both flagged as Important gaps by /review-pr on
PR #74 and explicitly recommended for follow-up.

`HttpClient.__init__` (slice F / PR #73) extended the constructor with
``extra_non_transport_exceptions: Iterable[type[BaseException]] = ()``
and changed the runtime ``except`` clause from the module-level
``_NON_TRANSPORT_REQUESTS_EXCEPTIONS`` to ``self._non_transport_exceptions``.

The openai_compat-specific extras (SSLError, ProxyError) are pinned at
the tuple level by ``test_unit_openai_compat_httpclient_iter_2026-06-11.py``,
but two surfaces stayed unguarded:

1. **#78 — default-equivalence.** A ``HttpClient()`` constructed without
   the kwarg must produce the same per-instance tuple as the pre-slice-F
   module constant. A regression like
   ``tuple(extra_non_transport_exceptions) or _NON_TRANSPORT_REQUESTS_EXCEPTIONS``
   would pass every openai_compat test (extras non-empty there) while
   silently breaking every other adopter (autoauth, local_model, db_sync,
   flux).

2. **#79 — runtime dispatch.** Driving an actual request through ``_HTTP.post(...)``
   with ``session.request`` side-effecting an SSLError / ProxyError and
   verifying the raw exception type re-raises (NOT wrapped to
   HPCUnreachableError, NOT consumed by retry). A regression that built
   the per-instance tuple correctly but failed to wire it into the
   ``except`` clause would pass tuple-level checks and silently regress.

Hermetic — no network access.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests


# ---------------------------------------------------------------------------
# #78 — default-equivalence: HttpClient() with no extras matches the
# module-level constant exactly.
# ---------------------------------------------------------------------------


def test_default_non_transport_exceptions_matches_module_constant():
    """Pin that ``HttpClient()`` with no ``extra_non_transport_exceptions``
    produces the same per-instance tuple as the module-level constant.
    A regression that flipped the constructor logic (e.g.
    ``tuple(extras) or _NON_TRANSPORT_REQUESTS_EXCEPTIONS``) would
    silently break every default-configured HttpClient adopter
    (autoauth, local_model, db_sync, flux) while leaving openai_compat
    passing — extras is non-empty there so the short-circuit hides the
    bug."""
    from autonomous.http.client import HttpClient, _NON_TRANSPORT_REQUESTS_EXCEPTIONS

    client = HttpClient()
    assert client._non_transport_exceptions == _NON_TRANSPORT_REQUESTS_EXCEPTIONS, (
        f"default HttpClient() tuple must equal the module-level constant; "
        f"got {client._non_transport_exceptions!r} vs "
        f"{_NON_TRANSPORT_REQUESTS_EXCEPTIONS!r}"
    )


def test_empty_extras_equivalent_to_no_kwarg():
    """``extra_non_transport_exceptions=()`` and the kwarg omitted must
    produce identical tuples. Pins the second branch of the regression
    pattern in #78 — a refactor that special-cased "extras is None"
    vs. "extras is empty tuple" would diverge these two construction
    paths."""
    from autonomous.http.client import HttpClient

    a = HttpClient()
    b = HttpClient(extra_non_transport_exceptions=())
    assert a._non_transport_exceptions == b._non_transport_exceptions, (
        f"empty-extras kwarg must be observationally equivalent to omitting "
        f"it; got {a._non_transport_exceptions!r} vs "
        f"{b._non_transport_exceptions!r}"
    )


def test_extras_prepend_or_append_does_not_drop_module_constant():
    """Belt-and-suspenders for #78: even when extras IS non-empty, the
    per-instance tuple must contain every member of the module-level
    constant. Already pinned for openai_compat in
    test_unit_openai_compat_httpclient_iter_2026-06-11.py, but pin
    here at the HttpClient-direct level too so the invariant is
    independently verified — a refactor that changed the slot order
    or replaced concatenation with set-union (would deduplicate) would
    still be caught here even if openai_compat's extras happened to
    overlap with the module constant."""
    from autonomous.http.client import HttpClient, _NON_TRANSPORT_REQUESTS_EXCEPTIONS

    client = HttpClient(
        extra_non_transport_exceptions=(requests.exceptions.SSLError,),
    )
    for cls in _NON_TRANSPORT_REQUESTS_EXCEPTIONS:
        assert cls in client._non_transport_exceptions, (
            f"per-instance tuple lost module-level {cls.__name__} when "
            f"extras was non-empty — concat replaced by something else?"
        )
    assert requests.exceptions.SSLError in client._non_transport_exceptions


# ---------------------------------------------------------------------------
# #79 — runtime dispatch: drive _HTTP.post so session.request raises
# SSLError / ProxyError, verify they re-raise raw (NOT wrapped to
# HPCUnreachableError, NOT consumed by retry budget).
# ---------------------------------------------------------------------------


def _fast_retry_for_openai_compat(monkeypatch):
    """Disable retry backoff so the test doesn't burn real sleeps in
    the (hopefully zero) retry path."""
    from autonomous.ai.models import openai_compat
    monkeypatch.setattr(openai_compat._HTTP, "retry_backoff", 0)


def test_ssl_error_reraises_raw_not_wrapped_through_openai_compat_http(monkeypatch):
    """End-to-end: drive a real request where ``session.request`` raises
    ``SSLError``; verify it propagates as ``SSLError`` (NOT wrapped to
    ``HPCUnreachableError``, NOT consumed by the retry budget). Pins
    the runtime dispatch of the extras tuple — complements the
    tuple-membership checks already in
    test_unit_openai_compat_httpclient_iter_2026-06-11.py."""
    _fast_retry_for_openai_compat(monkeypatch)
    from autonomous.ai.models.openai_compat import _HTTP

    ssl_err = requests.exceptions.SSLError("corporate cert bundle missing")
    mock_req = MagicMock(side_effect=ssl_err)
    monkeypatch.setattr(_HTTP.session, "request", mock_req)

    with pytest.raises(requests.exceptions.SSLError, match="corporate cert"):
        _HTTP.post("https://hpc.example/api/chat", json={"k": "v"})

    # Single attempt — retry budget MUST NOT fire for carved-out
    # config-class exceptions. If this asserts >1, the runtime
    # except-branch order is wrong (e.g. the broad
    # ``except requests.RequestException`` caught the SSLError before
    # the carve-out branch had a chance to re-raise raw).
    assert mock_req.call_count == 1, (
        f"SSLError is in openai_compat's config-class carve-out; retry "
        f"must NOT engage. Got {mock_req.call_count} attempts."
    )


def test_proxy_error_reraises_raw_not_wrapped_through_openai_compat_http(monkeypatch):
    """Same shape as SSLError test, for ProxyError. The two carve-outs
    have independent failure modes in production (cert vs proxy), so
    pin both independently — a partial regression that broke only one
    of the two would be visible from the start."""
    _fast_retry_for_openai_compat(monkeypatch)
    from autonomous.ai.models.openai_compat import _HTTP

    proxy_err = requests.exceptions.ProxyError("corporate proxy misconfigured")
    mock_req = MagicMock(side_effect=proxy_err)
    monkeypatch.setattr(_HTTP.session, "request", mock_req)

    with pytest.raises(requests.exceptions.ProxyError, match="proxy"):
        _HTTP.post("https://hpc.example/api/chat", json={"k": "v"})

    assert mock_req.call_count == 1, (
        f"ProxyError is in openai_compat's config-class carve-out; retry "
        f"must NOT engage. Got {mock_req.call_count} attempts."
    )


def test_module_level_carve_out_also_reraises_raw_on_default_client(monkeypatch):
    """Complement #79: pin that a DEFAULT-config ``HttpClient()`` still
    re-raises module-level carve-out exceptions raw. The openai_compat
    tests cover the extras-extended path; this covers the empty-extras
    path through the same runtime branch — verifies the
    ``self._non_transport_exceptions`` lookup works whether the tuple
    came from the constructor extras OR the module constant alone."""
    from autonomous.http.client import HttpClient

    client = HttpClient(max_attempts=5, retry_backoff=0.0)

    missing_schema_err = requests.exceptions.MissingSchema(
        "Invalid URL 'no-scheme': No scheme supplied."
    )
    mock_req = MagicMock(side_effect=missing_schema_err)
    monkeypatch.setattr(client.session, "request", mock_req)

    with pytest.raises(requests.exceptions.MissingSchema, match="No scheme"):
        client.get("no-scheme")

    # max_attempts=5 was set but MissingSchema is a config-class
    # exception — the dispatch must catch it from the per-instance
    # tuple and re-raise raw without burning the retry budget.
    assert mock_req.call_count == 1, (
        f"MissingSchema is a module-level carve-out; retry must NOT "
        f"engage even on a max_attempts=5 client. Got {mock_req.call_count} attempts."
    )


def test_transport_class_exception_still_uses_retry_budget(monkeypatch):
    """Sanity / regression guard: the carve-out must NOT swallow
    actual transport-class exceptions. A refactor that over-broadened
    the carve-out (e.g. added ``requests.RequestException`` itself to
    the tuple) would silently disable retry for every adopter. Pin
    the boundary — ``ConnectionError`` is transport-class and MUST go
    through the full retry budget."""
    from autonomous.http.client import HttpClient, TransportError

    client = HttpClient(max_attempts=3, retry_backoff=0.0)

    conn_err = requests.exceptions.ConnectionError("network unreachable")
    mock_req = MagicMock(side_effect=conn_err)
    monkeypatch.setattr(client.session, "request", mock_req)

    with pytest.raises(TransportError):
        client.get("http://example.com")

    assert mock_req.call_count == 3, (
        f"ConnectionError is transport-class; the full retry budget "
        f"(max_attempts=3) must engage. Got {mock_req.call_count} attempts."
    )
