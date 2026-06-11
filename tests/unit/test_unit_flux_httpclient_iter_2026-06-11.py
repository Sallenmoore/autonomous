"""Independent coverage for PR #72 (#50 slice E).

PR #72 collapses the ``flux._SESSION + inner _post() + retry(...)`` pattern
into a single ``_HTTP = HttpClient(...)`` at module scope. HttpClient's
``max_attempts`` + ``retry_backoff`` absorb the retry policy, and both
the POST and the CDN GET now go through the SAME retry budget (the
pre-migration retry wrapped only the POST, leaving the CDN fetch
single-attempt).

Independent perspective: pin the constructor params (read from
``settings.flux_max_attempts`` / ``settings.flux_retry_sleep`` — same
defaults the pre-migration ``retry()`` consumed), the removal of the
class attrs ``_max_attempts`` and ``_retry_sleep`` (test docs commit to
this), the removal of the ``_SESSION`` and ``retry`` symbols, and the
fact that both ``_HTTP.post`` AND ``_HTTP.get`` are now in the retry
budget (the documented behavior change).
"""

import inspect

import pytest
import requests


# ---------------------------------------------------------------------------
# Module-level _HTTP — constructor params + identity.
# ---------------------------------------------------------------------------


def test_http_module_seam_exists():
    import autonomous.ai.models.flux as flux

    assert hasattr(flux, "_HTTP")


def test_http_is_httpclient_instance():
    from autonomous.ai.models.flux import _HTTP
    from autonomous.http import HttpClient

    assert isinstance(_HTTP, HttpClient)


def test_http_timeout_is_none():
    """Each call site passes ``timeout=self._media_timeout``; client-level
    cap is None to let the per-call value govern."""
    from autonomous.ai.models.flux import _HTTP

    assert _HTTP.timeout is None


def test_http_max_attempts_from_settings():
    """The pre-migration ``retry(max_attempts=self._max_attempts, ...)``
    read from ``settings.flux_max_attempts`` (default 3). HttpClient's
    constructor must read from the same source so the env override
    ``FLUX_MAX_ATTEMPTS`` keeps working without code changes."""
    from autonomous.ai.models.flux import _HTTP
    from autonomous.config import settings

    assert _HTTP.max_attempts == settings.flux_max_attempts


def test_http_retry_backoff_from_settings():
    """Same setting path migration for the backoff. A regression that
    hardcodes ``retry_backoff=1.0`` instead of reading the setting would
    silently break ``FLUX_RETRY_SLEEP`` env-var deployments."""
    from autonomous.ai.models.flux import _HTTP
    from autonomous.config import settings

    assert _HTTP.retry_backoff == settings.flux_retry_sleep


def test_http_transport_error_cls_is_requests_connection_error():
    """Post-#85 the override narrowed from ``requests.RequestException``
    to ``requests.ConnectionError`` so HttpClient's retry loop no longer
    catches ``raise_for_status``-raised ``HTTPError`` (HTTPError is-a
    RequestException but not-a ConnectionError) — 4xx now fails fast at
    the altitude layer instead of burning the retry budget.

    The original constraint still holds via subclass relation: the
    ``except (requests.RequestException, ValueError, OSError)`` catch in
    ``generate_image`` continues to catch transport-class failures
    because ``ConnectionError`` is-a ``RequestException``. Without this
    override the default ``TransportError`` (RuntimeError subclass) would
    bypass the downstream catch silently.

    Source and test were updated in the same patch (#85). The literal
    assertion has to change with the override; the test's intent
    (downstream catch still triggers) is preserved by the
    ConnectionError → RequestException subclass relation. Same
    source-and-test inseparability pattern as the #50 HttpClient
    migration slices."""
    from autonomous.ai.models.flux import _HTTP

    assert _HTTP.transport_error_cls is requests.ConnectionError
    # Sanity: the downstream catch tuple in generate_image still matches
    # the new wrap class via the subclass relation — this is the actual
    # operator-facing contract the original test was guarding.
    assert issubclass(_HTTP.transport_error_cls, requests.RequestException), (
        "ConnectionError must remain a RequestException subclass so the "
        "downstream catch in generate_image still matches retry-exhaustion "
        "failures."
    )


# ---------------------------------------------------------------------------
# Symbol removal — _SESSION gone, retry() import gone, class attrs gone.
# ---------------------------------------------------------------------------


def test_legacy_session_symbol_is_gone():
    """The PR comment commits to NOT aliasing ``_SESSION`` — HttpClient
    routes through ``session.request(...)`` so an alias would silently
    no-op a ``_SESSION.post`` monkeypatch."""
    import autonomous.ai.models.flux as flux

    assert not hasattr(flux, "_SESSION"), (
        "_SESSION must be removed (not aliased) so stale monkeypatches "
        "AttributeError loudly instead of silently no-opping"
    )


def test_retry_import_is_gone_from_module():
    """The inner ``_post()`` + ``retry(...)`` dance is replaced by
    HttpClient's internal retry. The ``from autonomous.ai.retry import
    retry`` import has no remaining callers in this module."""
    import autonomous.ai.models.flux as flux

    # ``retry`` may still be importable via ``autonomous.ai.retry`` —
    # that's fine. The check is that it's NOT re-exported from the flux
    # module's globals.
    assert "retry" not in vars(flux), (
        "flux module still references retry — should have been deleted "
        "when _HTTP absorbed the pattern"
    )


def test_flux_class_no_longer_carries_retry_class_attrs():
    """The class attrs ``_max_attempts`` and ``_retry_sleep`` are gone —
    they used to feed the inner ``_post()`` retry wrapper. Now they live
    on the module-scope ``_HTTP`` instance. Pin removal so tests that
    used to monkeypatch the class attrs (and would silently no-op
    post-migration) surface."""
    from autonomous.ai.models.flux import FluxAIModel

    # Defensive check: walk MRO to catch a regression that re-introduces
    # the class attr at the FluxAIModel level OR at any non-AutoModel
    # ancestor that wasn't there before.
    for cls in FluxAIModel.__mro__:
        if cls.__name__ in ("AutoModel", "Document", "object"):
            break
        assert "_max_attempts" not in vars(cls), (
            f"{cls.__name__}._max_attempts must be removed — config "
            f"now lives on _HTTP.max_attempts"
        )
        assert "_retry_sleep" not in vars(cls), (
            f"{cls.__name__}._retry_sleep must be removed — config "
            f"now lives on _HTTP.retry_backoff"
        )


# ---------------------------------------------------------------------------
# Call-site migration — generate_image must use _HTTP.post AND _HTTP.get
# (the documented behavior change: both inside the retry budget now).
# ---------------------------------------------------------------------------


def test_generate_image_uses_http_post_not_legacy_session():
    """Pin the POST call site moved over. A regression that leaves
    ``_SESSION.post`` in this method would (a) AttributeError because
    ``_SESSION`` is gone, but a refactor adding ``import requests`` then
    ``requests.Session().post`` would bypass HttpClient silently."""
    from autonomous.ai.models.flux import FluxAIModel

    src = inspect.getsource(FluxAIModel.generate_image)
    assert "_HTTP.post" in src, (
        "generate_image must POST through _HTTP for retry coverage"
    )
    assert "_SESSION" not in src, (
        "generate_image still references the removed _SESSION seam"
    )


def test_generate_image_cdn_get_uses_http_get_not_bare_requests():
    """The DOCUMENTED behavior change: the CDN GET that used to run
    outside the retry loop now goes through ``_HTTP.get``, so it
    inherits HttpClient's retry budget. A regression that leaves a
    bare ``requests.get(...)`` here would silently revert the
    reliability improvement the slice intends."""
    from autonomous.ai.models.flux import FluxAIModel

    src = inspect.getsource(FluxAIModel.generate_image)
    assert "_HTTP.get" in src, (
        "CDN GET must route through _HTTP.get to gain retry coverage "
        "(the explicit reliability improvement of #50 slice E)"
    )
    assert "requests.get" not in src, (
        "CDN GET via bare requests.get would silently revert the "
        "retry-coverage improvement"
    )


# ---------------------------------------------------------------------------
# Pooling preserved — HttpClient must carry a real session.
# ---------------------------------------------------------------------------


def test_http_carries_a_requests_session_underneath():
    from autonomous.ai.models.flux import _HTTP

    assert hasattr(_HTTP, "session")
    assert isinstance(_HTTP.session, requests.Session)
