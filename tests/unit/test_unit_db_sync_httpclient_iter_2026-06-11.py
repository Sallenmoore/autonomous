"""Independent coverage for PR #71 (#50 slice D).

PR #71 migrates ``db.db_sync._HTTP_SESSION`` (a ``requests.Session``)
to ``_HTTP`` (an ``HttpClient``). The migration carries a documented
**signature change** for the ``[HPC-UNREACHABLE]`` marker on production
5xx responses (was ``local:http:{code}``, now ``local:exc:RequestException``)
plus a new ``except requests.HTTPError`` branch that preserves the
``local:http:{code}`` signature on 4xx production responses.

Independent perspective: pin the constructor params (same shape as
slice C — timeout=None, max_attempts=1, RequestException wrapper), the
removal of the ``_HTTP_SESSION`` symbol (honest break — no alias), and
the four observable signatures the call site emits:

1. ``local:http:{code}`` on a mock 4xx ``HTTPError`` (new HTTPError branch)
2. ``local:exc:ConnectionError`` when HttpClient wraps a transport
   ConnectionError into RequestException (``__cause__`` unwrap)
3. ``local:exc:RequestException`` on a bare wrapped 5xx (no ``__cause__`` —
   the documented signature change)
4. ``local:http:{code}`` on mock non-200 (in-flow defense-in-depth path)
"""

from unittest.mock import MagicMock, patch

import pytest
import requests


# ---------------------------------------------------------------------------
# Module-level _HTTP — same shape as slice C (autoauth, local_model) but a
# distinct singleton.
# ---------------------------------------------------------------------------


def test_http_module_seam_exists():
    import autonomous.db.db_sync as db_sync

    assert hasattr(db_sync, "_HTTP")


def test_http_is_httpclient_instance():
    from autonomous.db.db_sync import _HTTP
    from autonomous.http import HttpClient

    assert isinstance(_HTTP, HttpClient)


def test_http_timeout_is_none():
    """``_get_vector_local`` passes ``timeout=30`` per-call. A client-level
    cap on top would be redundant or actively conflicting."""
    from autonomous.db.db_sync import _HTTP

    assert _HTTP.timeout is None


def test_http_max_attempts_is_one_no_retry():
    """Embedding sync is best-effort — the RQ taskrunner re-queues failed
    jobs at its own layer. Pin no-retry; a regression that flips this to
    3 would double-spend the media_ai compute budget on transient errors."""
    from autonomous.db.db_sync import _HTTP

    assert _HTTP.max_attempts == 1


def test_http_transport_error_cls_is_requests_request_exception():
    """The slice D /code-review finding: HttpClient's default TransportError
    is a RuntimeError subclass; consumer code writing
    ``except requests.RequestException`` would bypass it silently. Pin
    the wrapper to keep the catch contract intact."""
    from autonomous.db.db_sync import _HTTP

    assert _HTTP.transport_error_cls is requests.RequestException


# ---------------------------------------------------------------------------
# _HTTP_SESSION removed — no back-compat alias.
# ---------------------------------------------------------------------------


def test_legacy_http_session_symbol_is_gone():
    """The PR commits to NOT preserving ``_HTTP_SESSION`` as an alias.
    A stale ``_HTTP_SESSION.post`` monkeypatch from an external consumer
    would silently fail to intercept HttpClient's
    ``session.request(...)`` routing — an honest AttributeError beats a
    silent miss."""
    import autonomous.db.db_sync as db_sync

    assert not hasattr(db_sync, "_HTTP_SESSION"), (
        "_HTTP_SESSION must be removed (not aliased) so stale "
        "monkeypatches AttributeError loudly"
    )


# ---------------------------------------------------------------------------
# Observable [HPC-UNREACHABLE] signatures — the documented contract for
# consumer dashboards. Each branch of _get_vector_local's exception ladder
# produces a distinct signature.
# ---------------------------------------------------------------------------


def _patched_emit():
    """Patch the ``_emit_hpc_unreachable`` callable so we can inspect the
    signature string the call site picked."""
    return patch("autonomous.db.db_sync._emit_hpc_unreachable")


def test_signature_for_mock_non_200_in_flow_path():
    """The defense-in-depth in-flow check (``resp.status_code != 200``)
    must still emit ``local:http:{code}`` for tests that patch
    ``_HTTP.post`` directly with a mock response. The MIGRATIONS.md entry
    explicitly commits to this signature shape for the mock path."""
    from autonomous.db import db_sync

    fake_resp = MagicMock()
    fake_resp.status_code = 503
    with patch.object(db_sync._HTTP, "post", return_value=fake_resp), \
         patch.object(db_sync, "record_embedding_sync_event"), \
         _patched_emit() as emit:
        result = db_sync._get_vector_local("test text")

    assert result is None
    assert emit.called
    signature = emit.call_args[0][0]
    assert signature == "local:http:503", (
        f"mock non-200 must emit local:http:{{code}}; got {signature!r}"
    )


def test_signature_for_production_http_error_branch():
    """A `requests.HTTPError` (the production 4xx path through HttpClient's
    raise_for_status) must emit ``local:http:{code}`` — pulled from
    ``e.response.status_code``. This preserves the pre-migration
    per-status-code signature for 4xx tier counting on consumer dashboards."""
    from autonomous.db import db_sync

    fake_resp = MagicMock()
    fake_resp.status_code = 404
    http_err = requests.HTTPError(response=fake_resp)
    with patch.object(db_sync._HTTP, "post", side_effect=http_err), \
         patch.object(db_sync, "record_embedding_sync_event"), \
         _patched_emit() as emit:
        result = db_sync._get_vector_local("test text")

    assert result is None
    signature = emit.call_args[0][0]
    assert signature == "local:http:404", (
        f"production HTTPError must emit local:http:{{code}} from "
        f"response.status_code; got {signature!r}"
    )


def test_signature_unwraps_cause_to_underlying_connection_error():
    """When HttpClient wraps a transport ConnectionError into the
    configured ``RequestException`` wrapper, ``__cause__`` carries the
    underlying ConnectionError. The except branch unwraps one level so
    the signature reports the underlying class — preserves the
    pre-migration ``local:exc:ConnectionError`` shape for connection
    failures so consumer dashboards don't see a regression."""
    from autonomous.db import db_sync

    underlying = requests.ConnectionError("refused")
    wrapper = requests.RequestException("transport wrapped")
    wrapper.__cause__ = underlying

    with patch.object(db_sync._HTTP, "post", side_effect=wrapper), \
         patch.object(db_sync, "record_embedding_sync_event"), \
         _patched_emit() as emit:
        result = db_sync._get_vector_local("test text")

    assert result is None
    signature = emit.call_args[0][0]
    assert signature == "local:exc:ConnectionError", (
        f"wrapped transport error must unwrap __cause__ to the underlying "
        f"class; got {signature!r}"
    )


def test_signature_for_bare_wrapped_request_exception_no_cause():
    """The DOCUMENTED behavior change: a production 5xx flows through
    HttpClient's raise_for_status path, gets wrapped to RequestException
    with NO ``__cause__`` (the 5xx-from-status raise isn't a wrapped
    transport call). The except branch keeps the wrapper class. Pin the
    new ``local:exc:RequestException`` shape — MIGRATIONS.md commits to
    it and a regression that re-introduces ``local:http:5xx`` would
    drift back toward the pre-migration shape."""
    from autonomous.db import db_sync

    # Simulate the bare-wrapper case: side_effect raises a RequestException
    # with no underlying cause (mimics HttpClient's raise_for_status path
    # after wrapping a 5xx as the transport_error_cls).
    plain = requests.RequestException("5xx wrapped, no cause")
    # Defensive: in some Python versions a freshly-raised exception may
    # acquire a context but no cause; ensure both are None to mimic the
    # documented "no __cause__" condition.
    plain.__cause__ = None

    with patch.object(db_sync._HTTP, "post", side_effect=plain), \
         patch.object(db_sync, "record_embedding_sync_event"), \
         _patched_emit() as emit:
        result = db_sync._get_vector_local("test text")

    assert result is None
    signature = emit.call_args[0][0]
    assert signature == "local:exc:RequestException", (
        f"bare wrapped RequestException (no __cause__) must surface the "
        f"wrapper class — this is the documented #50 slice D change; "
        f"got {signature!r}"
    )


def test_happy_path_no_marker_no_failure_recorded():
    """Regression guard: PR #71 must not break the success path. A 200
    response with a valid embedding must return the embedding and emit
    NO ``[HPC-UNREACHABLE]`` marker."""
    from autonomous.db import db_sync

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
    with patch.object(db_sync._HTTP, "post", return_value=fake_resp), \
         patch.object(db_sync, "record_embedding_sync_event") as record, \
         _patched_emit() as emit:
        result = db_sync._get_vector_local("test text")

    assert result == [0.1, 0.2, 0.3]
    emit.assert_not_called()
    record.assert_not_called()


# ---------------------------------------------------------------------------
# Pooling preserved — HttpClient must hold a real requests.Session
# underneath so the long-running RQ-worker process keeps a warm connection
# to media_ai.
# ---------------------------------------------------------------------------


def test_http_carries_a_requests_session_underneath():
    from autonomous.db.db_sync import _HTTP

    assert hasattr(_HTTP, "session")
    assert isinstance(_HTTP.session, requests.Session)


def test_http_is_a_singleton_within_module():
    """Pool-reuse contract: repeated access must return the same
    HttpClient instance, not a freshly-built one. A property/factory
    that re-instantiates on each access would defeat pooling and
    silently double the per-call socket setup cost."""
    from autonomous.db import db_sync

    a = db_sync._HTTP
    b = db_sync._HTTP
    assert a is b
