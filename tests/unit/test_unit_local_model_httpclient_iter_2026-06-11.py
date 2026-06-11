"""Independent coverage for PR #70 (#50 slice C).

PR #70 migrates ``LocalAIModel``'s ad-hoc ``_SESSION = requests.Session()``
to a shared ``_HTTP = HttpClient(...)``. Key contract decisions encoded
in the migration:

1. ``timeout=None`` — every call site already passes its own per-call
   ``timeout=`` kwarg (``_text_timeout``, ``_summary_timeout``,
   ``_media_timeout``, or hardcoded 30 for ``flush_memory``). A
   client-level cap on top would double-bound and silently shorten
   long-running media uploads.
2. ``max_attempts=1`` — preserves pre-migration no-retry semantics
   while the slice lands. Retry policy is per-call-site shaped, not
   client-level (README #16).
3. ``transport_error_cls=requests.RequestException`` — the call sites
   wrap POST in ``except (requests.RequestException, ...)``; raising
   the default ``TransportError`` (a ``RuntimeError`` subclass) would
   bypass those catches silently. Pinning the wrapper preserves the
   pre-migration exception ladder.
4. The ``_SESSION`` name is INTENTIONALLY removed — no alias. A stale
   ``_SESSION.post`` monkeypatch from an older consumer test would
   silently fail to intercept a migrated call. The PR's call-site
   comment commits to an honest break.

Independent perspective: pin all four constructor params, the
migration of every call site (no stray ``_SESSION.post`` or
``requests.post`` from inside the migrated functions), and the
absence of the old ``_SESSION`` symbol.
"""

import inspect

import pytest


# ---------------------------------------------------------------------------
# Module-level _HTTP — pin its existence, type, and constructor params.
# ---------------------------------------------------------------------------


def test_http_module_seam_exists():
    import autonomous.ai.models.local_model as lm

    assert hasattr(lm, "_HTTP"), (
        "local_model must expose a module-level _HTTP seam for test patching"
    )


def test_http_is_httpclient_instance():
    from autonomous.ai.models.local_model import _HTTP
    from autonomous.http import HttpClient

    assert isinstance(_HTTP, HttpClient)


def test_http_timeout_is_none():
    """Every call site passes its own ``timeout=`` kwarg (e.g.
    ``self._text_timeout``, hardcoded 30). The client-level cap is
    explicitly None so the per-call value governs without an additional
    upper bound that would silently shorten long media uploads."""
    from autonomous.ai.models.local_model import _HTTP

    assert _HTTP.timeout is None


def test_http_max_attempts_is_one_no_retry():
    """README #16 (per-call-site retry) is a deferred follow-up.
    Pre-migration was no-retry; this slice preserves that exactly.
    A regression that flips this to 3 would re-spend tokens on
    text-generation calls that should never retry."""
    from autonomous.ai.models.local_model import _HTTP

    assert _HTTP.max_attempts == 1


def test_http_transport_error_cls_is_requests_connection_error():
    """Originally ``requests.RequestException`` (PR #70/#50-C); narrowed to
    ``requests.ConnectionError`` in the #97/#106 follow-up after the outer
    ``retry()`` catch tuple in ``generate_json`` was narrowed in the same
    cycle. A base ``RequestException(msg)`` wrap silently stopped matching
    ``(ConnectionError, Timeout)`` in the outer catch. ``ConnectionError``
    IS a ``RequestException`` subclass, so ``flush_memory``'s
    ``except requests.RequestException`` still matches. A regression to
    the default ``TransportError`` (a ``RuntimeError`` subclass) would
    bypass that catch silently."""
    import requests
    from autonomous.ai.models.local_model import _HTTP

    assert _HTTP.transport_error_cls is requests.ConnectionError


# ---------------------------------------------------------------------------
# Symbol removal — _SESSION must NOT survive as an alias.
# ---------------------------------------------------------------------------


def test_legacy_session_symbol_is_gone():
    """The PR's comment commits to NOT preserving ``_SESSION`` as an alias.
    An older test patching ``_SESSION.post`` would silently fail to
    intercept the migrated call (HttpClient routes through
    ``session.request("POST", ...)``, not ``session.post(...)``).
    An honest AttributeError beats a silent miss."""
    import autonomous.ai.models.local_model as lm

    assert not hasattr(lm, "_SESSION"), (
        "_SESSION must be removed (not aliased) so stale monkeypatches "
        "AttributeError loudly instead of failing to intercept"
    )


# ---------------------------------------------------------------------------
# Call-site migration — every POST in the migrated methods routes through
# ``_HTTP``, not a bare ``requests.post`` or a stray ``_SESSION.post``.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method_name",
    [
        "_evaluate_response",
        "flush_memory",
        "generate_json",
        "generate_text",
        "summarize_text",
        "generate_transcription",
        "generate_audio",
        "generate_image",
        "upscale_image",
    ],
)
def test_call_sites_use_http_post_not_bare_requests(method_name):
    """Source-level pin: each method's body must use ``_HTTP.post(...)``.
    A regression that mixes ``requests.post`` (no pooling, no transport
    classification) or ``_SESSION.post`` (stale alias) into one site
    while the rest moved over would silently lose pooling for that path
    and break the uniform exception shape."""
    from autonomous.ai.models.local_model import LocalAIModel

    method = getattr(LocalAIModel, method_name)
    src = inspect.getsource(method)
    assert "_HTTP.post" in src, (
        f"{method_name} must route through _HTTP.post (migration incomplete)"
    )
    assert "_SESSION.post" not in src, (
        f"{method_name} still references the removed _SESSION seam"
    )
    # ``requests.post`` would mean a call site that bypasses the migration
    # entirely (no pooling, no transport wrapper). Allowed only inside a
    # ``raise requests.<Exception>`` pattern, which doesn't appear here.
    assert "requests.post" not in src, (
        f"{method_name} calls bare requests.post — migration bypass"
    )


# ---------------------------------------------------------------------------
# Internal session reuse — HttpClient must carry a real requests.Session
# under the hood so the pooling-via-Session contract from the pre-migration
# code is preserved (intranet Ollama / media_ai calls benefit from keep-
# alive). PR comment explicitly commits to this.
# ---------------------------------------------------------------------------


def test_http_carries_a_requests_session_underneath():
    """The migration claims to preserve connection-pooling behavior. The
    only way to preserve it through HttpClient is for HttpClient to hold
    a real ``requests.Session`` internally. Pin the property so a future
    refactor to "fire a fresh requests.Session per call" goes red here."""
    import requests
    from autonomous.ai.models.local_model import _HTTP

    # HttpClient exposes the underlying session as ``.session``.
    assert hasattr(_HTTP, "session"), (
        "HttpClient must expose its internal session for pooling reuse"
    )
    assert isinstance(_HTTP.session, requests.Session), (
        "internal session must be a real requests.Session, not a "
        "lookalike — connection pooling depends on Session-level state"
    )
