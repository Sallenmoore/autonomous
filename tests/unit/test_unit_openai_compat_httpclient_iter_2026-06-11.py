"""Independent coverage for PR #73 (#50 slice F — closes #50).

PR #73 is the capstone of the #50 slice train: ``openai_compat._SESSION``
plus an ~70-line ``_post()`` exception ladder are replaced by a single
``_HTTP = HttpClient(...)`` and a 12-line ``_post()``. The migration
required extending HttpClient with a new ``extra_non_transport_exceptions=``
constructor kwarg so openai_compat could keep its per-deployment
SSL/Proxy config-error carve-out (in the HPC deployment those are
corporate-cert misconfigs; in public-internet adapters they can be
transient).

The migration also introduces a **documented** behavior change: the
``HPCUnreachableError`` message format changes (the exception class
is unchanged). And openai_compat's HttpClient uniquely sets the
``transport_failure_codes`` kwarg with the deployment's 401 carve-out.

Independent perspective: pin
1. The constructor params (max_attempts/retry_backoff read from
   settings.hpc_*, transport_error_cls=HPCUnreachableError,
   transport_failure_codes includes 401, extra_non_transport_exceptions
   carves SSLError + ProxyError).
2. The class-attr removal (_retry_attempts / _retry_backoff gone from
   OpenAIClient).
3. The legacy ``_SESSION`` symbol is gone.
4. The HttpClient extension itself: per-instance
   ``_non_transport_exceptions`` tuple is built from the module-level
   constant + the constructor kwarg.
5. ContentDecodingError is deliberately NOT in the carve-out (PR #99
   decision, preserved as an in-source breadcrumb in the migration).
"""

import inspect

import pytest
import requests


# ---------------------------------------------------------------------------
# Module-level _HTTP — six constructor params, all load-bearing.
# ---------------------------------------------------------------------------


def test_http_module_seam_exists():
    import autonomous.ai.models.openai_compat as oc

    assert hasattr(oc, "_HTTP")


def test_http_is_httpclient_instance():
    from autonomous.ai.models.openai_compat import _HTTP
    from autonomous.http import HttpClient

    assert isinstance(_HTTP, HttpClient)


def test_http_timeout_is_none():
    """``_post`` passes ``timeout=self._timeout``; client-level cap is None."""
    from autonomous.ai.models.openai_compat import _HTTP

    assert _HTTP.timeout is None


def test_http_max_attempts_from_settings_hpc_retry_attempts():
    """The pre-migration ``retry(max_attempts=self._retry_attempts, ...)``
    read from ``settings.hpc_retry_attempts``. HttpClient must read from
    the same source so ``HPC_RETRY_ATTEMPTS`` env override keeps working."""
    from autonomous.ai.models.openai_compat import _HTTP
    from autonomous.config import settings

    assert _HTTP.max_attempts == settings.hpc_retry_attempts


def test_http_retry_backoff_from_settings_hpc_retry_backoff():
    from autonomous.ai.models.openai_compat import _HTTP
    from autonomous.config import settings

    assert _HTTP.retry_backoff == settings.hpc_retry_backoff


def test_http_transport_error_cls_is_hpc_unreachable_error():
    """The retry budget catches ``transport_error_cls``. The pre-migration
    outer ``retry(...)`` caught ``HPCUnreachableError`` specifically;
    HttpClient must wrap caught requests.RequestException + transport-class
    status codes into HPCUnreachableError so the retry budget still fires."""
    from autonomous.ai.models.openai_compat import _HTTP, HPCUnreachableError

    assert _HTTP.transport_error_cls is HPCUnreachableError


def test_http_transport_failure_codes_includes_401():
    """The HPC deployment treats 401 as "VPN drop / token expiry — retry can
    recover" rather than a hard auth failure. Pre-migration this carve-out
    lived in ``_is_transport_failure``; post-migration it must be threaded
    to HttpClient via ``transport_failure_codes=``. A regression that drops
    401 from the set would turn transient VPN drops into hard failures."""
    from autonomous.ai.models.openai_compat import _HTTP, _TRANSPORT_FAILURE_CODES

    assert 401 in _HTTP.transport_failure_codes, (
        "_HTTP must carry the 401 carve-out from _TRANSPORT_FAILURE_CODES "
        "for the HPC deployment's VPN-drop tolerance"
    )
    # And the full set must come from the module's frozenset.
    assert _HTTP.transport_failure_codes == frozenset(_TRANSPORT_FAILURE_CODES), (
        "_HTTP.transport_failure_codes must mirror "
        "openai_compat._TRANSPORT_FAILURE_CODES exactly"
    )


# ---------------------------------------------------------------------------
# extra_non_transport_exceptions — the new HttpClient extension. Per-instance
# tuple must combine the module-level constant with the constructor kwarg.
# ---------------------------------------------------------------------------


def test_http_carves_out_ssl_error_and_proxy_error():
    """The PR's stated reason for extending HttpClient: openai_compat's HPC
    deployment carves out SSLError + ProxyError as config-class (corporate
    cert / corporate proxy misconfigs that retry can't fix). They must end
    up in the per-instance tuple AND remain catchable by HttpClient's
    config-error branch."""
    from autonomous.ai.models.openai_compat import _HTTP

    assert hasattr(_HTTP, "_non_transport_exceptions")
    tup = _HTTP._non_transport_exceptions
    assert requests.exceptions.SSLError in tup, (
        "SSLError must remain in openai_compat's config-error carve-out "
        "— retry-with-translation would misdirect on-call for cert misconfigs"
    )
    assert requests.exceptions.ProxyError in tup, (
        "ProxyError must remain in openai_compat's config-error carve-out "
        "— corporate-proxy misconfigs are config errors, not transient"
    )


def test_http_per_instance_tuple_extends_module_level_constant():
    """The per-instance tuple must be the module-level
    ``_NON_TRANSPORT_REQUESTS_EXCEPTIONS`` PLUS the constructor extras —
    not a replacement. A regression that overrode rather than extended
    would silently drop MissingSchema / InvalidURL / etc. from the
    carve-out for openai_compat and re-introduce retry-spin on
    programmer errors."""
    from autonomous.http.client import _NON_TRANSPORT_REQUESTS_EXCEPTIONS
    from autonomous.ai.models.openai_compat import _HTTP

    for module_level_cls in _NON_TRANSPORT_REQUESTS_EXCEPTIONS:
        assert module_level_cls in _HTTP._non_transport_exceptions, (
            f"per-instance tuple must extend, not replace, the module-level "
            f"constant — missing {module_level_cls.__name__}"
        )


def test_http_content_decoding_error_NOT_in_carve_out():
    """In-source breadcrumb (PR #99 decision, preserved by slice F):
    ContentDecodingError stays OUT of the config-error carve-out because
    malformed-gzip bodies are often transient server bugs that retry
    helps recover. A "let's add all the requests.exceptions.*" PR would
    silently regress this."""
    from autonomous.ai.models.openai_compat import _HTTP

    cls = requests.exceptions.ContentDecodingError
    assert cls not in _HTTP._non_transport_exceptions, (
        "ContentDecodingError must NOT be in the carve-out — retry path "
        "is the safer default for malformed-gzip bodies. See PR #99."
    )


# ---------------------------------------------------------------------------
# Symbol & code removal — _SESSION gone, retry import gone, class attrs gone.
# ---------------------------------------------------------------------------


def test_legacy_session_symbol_is_gone():
    import autonomous.ai.models.openai_compat as oc

    assert not hasattr(oc, "_SESSION"), (
        "_SESSION must be removed — same rationale as slices C/D/E"
    )


def test_retry_import_is_gone_from_module():
    """``from autonomous.ai.retry import retry`` had no remaining callers
    once HttpClient absorbed the pattern. Pin removal so a future PR
    that re-introduces a per-call retry wrapper (bypassing HttpClient's
    budget) surfaces here."""
    import autonomous.ai.models.openai_compat as oc

    assert "retry" not in vars(oc), (
        "the inner ``retry`` symbol from autonomous.ai.retry must be "
        "removed — HttpClient absorbs the pattern, a fresh import "
        "implies a per-call wrapper bypassing the centralized budget"
    )


def test_class_no_longer_carries_retry_class_attrs():
    """``_retry_attempts`` and ``_retry_backoff`` used to live on
    OpenAIClient. The migration moved them to ``_HTTP.max_attempts`` /
    ``_HTTP.retry_backoff`` at module scope. Pin removal so tests that
    used to monkeypatch the class attrs (now silent no-op) surface."""
    from autonomous.ai.models.openai_compat import OpenAIClient

    for cls in OpenAIClient.__mro__:
        if cls.__name__ in ("AutoModel", "Document", "object"):
            break
        assert "_retry_attempts" not in vars(cls), (
            f"{cls.__name__}._retry_attempts must be removed — config "
            f"now lives on _HTTP.max_attempts"
        )
        assert "_retry_backoff" not in vars(cls), (
            f"{cls.__name__}._retry_backoff must be removed — config "
            f"now lives on _HTTP.retry_backoff"
        )


# ---------------------------------------------------------------------------
# _post() collapse — the ~70-line hand-rolled assembly must collapse to a
# single _HTTP.post call site per branch.
# ---------------------------------------------------------------------------


def test_post_no_longer_contains_inner_attempt_closure():
    """Pre-migration ``_post`` defined an inner ``_attempt`` closure. The
    diff explicitly removes that pattern; HttpClient.request absorbs the
    same logic. Pin removal — a regression that re-introduces an inner
    ``_attempt`` would mean someone re-implemented the retry assembly by
    hand and bypassed HttpClient."""
    from autonomous.ai.models.openai_compat import OpenAIClient

    src = inspect.getsource(OpenAIClient._post)
    assert "_attempt" not in src, (
        "_post must NOT contain an inner _attempt closure — HttpClient "
        "absorbs the pattern; re-introducing the closure means someone "
        "bypassed the centralized exception ladder"
    )


def test_post_uses_http_post():
    from autonomous.ai.models.openai_compat import OpenAIClient

    src = inspect.getsource(OpenAIClient._post)
    assert "_HTTP.post" in src, (
        "_post must route through _HTTP.post — the entire migration intent"
    )
    assert "_SESSION" not in src, (
        "_post still references the removed _SESSION seam"
    )


def test_post_no_longer_calls_retry_wrapper():
    """The outer ``retry(_attempt, ...)`` wrapping is gone — HttpClient's
    internal retry budget runs the loop. A regression that re-introduces
    a ``retry(...)`` call here would double-budget the calls."""
    from autonomous.ai.models.openai_compat import OpenAIClient

    src = inspect.getsource(OpenAIClient._post)
    # Allow the *word* "retry" in comments — narrow to a function call.
    assert "retry(" not in src, (
        "_post must NOT wrap with a retry(...) call — HttpClient owns "
        "the retry budget. Double-budgeting silently doubles the call "
        "count under transient transport failure."
    )


# ---------------------------------------------------------------------------
# Pooling preserved.
# ---------------------------------------------------------------------------


def test_http_carries_a_requests_session_underneath():
    from autonomous.ai.models.openai_compat import _HTTP

    assert hasattr(_HTTP, "session")
    assert isinstance(_HTTP.session, requests.Session)
