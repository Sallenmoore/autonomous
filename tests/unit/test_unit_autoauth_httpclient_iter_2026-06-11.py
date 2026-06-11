"""Independent coverage for PR #69 (#50 slice B).

PR #69 migrates the OAuth userinfo fetch in ``AutoAuth.handle_response``
from a bare ``requests.get(...)`` to ``HttpClient.get(...)``. Pre-migration
there was no timeout on that call — a VPN drop mid-callback would hang
the worker indefinitely while the user stared at a spinner in their
browser. Post-migration, the module-level ``_HTTP = HttpClient(timeout=30.0)``
caps that wait, and the explicit ``max_attempts=1`` keeps the interactive
OAuth round-trip from retrying through a flapping network.

Independent perspective: pin the load-bearing constructor params
(timeout=30, max_attempts=1), the existence of ``_HTTP`` as a module
seam (so tests in this and future iterations can patch it), and the
fact that ``handle_response`` does NOT call the legacy ``requests.get``
seam any more. The bare-``requests`` import was retained for back-compat
with external code that patches it — that's fine, but the in-module
call site must have moved.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Module-level _HTTP — its identity is the patch-seam contract for every
# existing oauth test in the repo. If a refactor renames or removes it,
# downstream tests break silently. Pin it.
# ---------------------------------------------------------------------------


def test_http_module_seam_exists():
    """Pin the importable name ``_HTTP`` on the autoauth module. Every other
    test in this repo (and storyteller's vendored copy) patches this exact
    attribute path; renaming it without coordinating breaks the world."""
    import autonomous.auth.autoauth as autoauth_mod

    assert hasattr(autoauth_mod, "_HTTP"), (
        "autoauth must expose a module-level _HTTP seam for test patching"
    )


def test_http_is_httpclient_instance():
    """Pin the type. A subclass with different timeout semantics would
    silently change the contract on the userinfo fetch."""
    from autonomous.auth.autoauth import _HTTP
    from autonomous.http import HttpClient

    assert isinstance(_HTTP, HttpClient)


def test_http_timeout_is_30_seconds():
    """The contract the comment commits to: 30-second cap on the userinfo
    fetch. This is the explicit fix for the pre-migration "VPN drop hangs
    the worker forever" failure mode. A future change that raises this to
    `None` or lowers it below typical IdP latency goes red here."""
    from autonomous.auth.autoauth import _HTTP

    assert _HTTP.timeout == 30.0


def test_http_max_attempts_is_one_no_retry():
    """OAuth is an interactive round-trip — the user is waiting on a browser
    redirect. Retrying through a flapping network keeps them waiting longer
    while still likely failing. The PR explicitly chooses fail-fast
    (``max_attempts=1``); pin it so a "let's add retry for resilience"
    refactor surfaces here."""
    from autonomous.auth.autoauth import _HTTP

    assert _HTTP.max_attempts == 1


# ---------------------------------------------------------------------------
# handle_response uses the new seam — pin the migration is complete.
# ---------------------------------------------------------------------------


def test_handle_response_calls_http_not_legacy_requests(monkeypatch):
    """The load-bearing assertion: ``handle_response`` must call ``_HTTP.get``,
    not ``requests.get`` directly. The diff retains ``import requests`` for
    back-compat with consumers that patch the legacy surface, so a simple
    "the import is gone" check would over-fit. Instead: trip a sentinel on
    the legacy path AND verify the new path was the one used."""
    from autonomous.auth.autoauth import AutoAuth

    # Minimal AutoAuth subclass that skips the OAuth2Session construction —
    # we only care about the request mechanics of handle_response, not the
    # authlib token exchange.
    class _StubAuth(AutoAuth):
        def __init__(self):
            self.req_uri = "https://idp.example/userinfo"
            self.session = MagicMock()
            self.session.fetch_token = MagicMock(
                return_value={"access_token": "tok"}
            )
            self.session.token = {"access_token": "tok"}

    auth = _StubAuth()

    new_seam = MagicMock(return_value=SimpleNamespace(
        json=MagicMock(return_value={"sub": "subj", "email": "a@b.c"}),
    ))
    legacy_trip = MagicMock(side_effect=AssertionError(
        "handle_response must not call the legacy requests.get seam"
    ))

    with patch("autonomous.auth.autoauth._HTTP.get", new_seam), \
         patch("autonomous.auth.autoauth.requests.get", legacy_trip), \
         patch("autonomous.auth.autoauth.get_session", return_value={"oauth_state": "xyz"}):
        auth.handle_response("http://cb/?code=abc&state=xyz")

    new_seam.assert_called_once()
    legacy_trip.assert_not_called()


def test_handle_response_passes_oauth2auth_through_new_seam():
    """The auth-bearer contract: the userinfo endpoint requires the bearer
    token, threaded via ``auth=OAuth2Auth(token)``. The migration must
    preserve that — calling ``_HTTP.get`` without ``auth=`` would 401 every
    consumer in production. Pin the kwarg is forwarded."""
    from authlib.integrations.requests_client import OAuth2Auth
    from autonomous.auth.autoauth import AutoAuth

    class _StubAuth(AutoAuth):
        def __init__(self):
            self.req_uri = "https://idp.example/userinfo"
            self.session = MagicMock()
            self.session.fetch_token = MagicMock(
                return_value={"access_token": "tok"}
            )
            self.session.token = {"access_token": "tok"}

    auth = _StubAuth()

    new_seam = MagicMock(return_value=SimpleNamespace(
        json=MagicMock(return_value={"email": "x@y.z"}),
    ))

    with patch("autonomous.auth.autoauth._HTTP.get", new_seam), \
         patch("autonomous.auth.autoauth.get_session", return_value={"oauth_state": "xyz"}):
        auth.handle_response("http://cb/?code=abc&state=xyz")

    # The URL is positional, and `auth=` is a kwarg.
    args, kwargs = new_seam.call_args
    assert args[0] == "https://idp.example/userinfo", (
        f"first positional arg must be the userinfo URI: got {args!r}"
    )
    assert "auth" in kwargs, (
        f"OAuth2Auth must be threaded via the auth= kwarg: kwargs={kwargs!r}"
    )
    assert isinstance(kwargs["auth"], OAuth2Auth), (
        "auth= kwarg must be an OAuth2Auth instance (bearer-token plumbing)"
    )


# ---------------------------------------------------------------------------
# Construction must not network — covered by the existing
# TestNoNetworkAtConstruction::test_construction_makes_no_http_call in
# tests/unit/test_unit_oauth_new_providers_iter_2026-06-06.py (which PR
# #69 updated to patch both the legacy requests.get/post seam AND the
# new _HTTP.get/post seam). Not duplicated here — a reload-based
# import-time test would corrupt module state for subsequent tests.
# ---------------------------------------------------------------------------
