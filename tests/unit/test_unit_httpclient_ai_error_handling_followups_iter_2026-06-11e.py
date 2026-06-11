"""Independent committed coverage for PR #110 (dev ``iter/2026-06-11e-batch``).

PR #110 bundles 13 review-pr follow-ups clustered on the HttpClient /
AI-model error-handling theme. These tests are written from a fresh read
of the PR diff (the test-agent's independent second perspective) — the
dev agent's gitignored ``tests/_dev_local/`` ephemerals are NOT consulted
and never appear in the PR diff anyway.

Scope is the GENUINELY NEW behavior this PR introduces, deliberately not
re-testing what prior cycles' committed suites already pin:

* **#102** ``autonomous.ai.exceptions.MALFORMED_2XX_EXCEPTIONS`` — the
  single-source-of-truth catch tuple constant.
* **#90** ``MalformedResponseError.from_response`` — defensive
  ``response.text`` read that survives an undecodable 2xx body instead of
  re-raising ``UnicodeDecodeError`` inside the constructor arg.
* **#104** ``body_excerpt`` coercion now accepts ``memoryview``.
* **#88** ``_normalize_transcription_body`` — null-safe transcription
  shape (a legal ``{"text": null, "segments": null}`` 2xx body no longer
  leaks ``None`` past the contract). This is the headline bug: prior
  coverage exercised *missing* keys, not *null-valued* ones, so the real
  ``.get(k, default)``-returns-stored-None trigger was uncovered.
* **#92** ``_extract_or_malformed`` — the shared parse+walk+translate
  helper; the walk stays inside the protected block so an empty
  ``{"choices": []}`` still translates instead of leaking ``IndexError``.
* **#89** ``FluxAIModel`` retries 408/429 again
  (``transport_failure_codes={408, 429}``) while every other 4xx fails
  fast.
* **#96** ``HttpClient`` fires ``on_failure`` on the transport-STATUS
  (5xx + configured-extras) branch, for parity with the exception /
  HTTPError branches.
* **#98** ``HttpClient.__init__`` rejects an over-broad
  ``transport_error_cls`` (``Exception`` / ``BaseException``) that would
  catch the #91 ``_NonTransportHTTPError`` marker.
* **#93** ``GeminiAIModel`` orphan-cleanup delete failures are now LOGGED
  (was a silent ``except: pass``).
* **#94** ``GeminiAIModel`` orphan-cleanup runs on a bounded
  ``ThreadPoolExecutor(max_workers=4)`` — ALL N orphans are attempted
  even when some deletes fail (``_delete_orphan`` swallows so
  ``executor.map`` materialization doesn't short-circuit), and
  ``list(...)`` forces every delete to finish before the original poll
  exception re-raises.
* Defensive ``.text`` read on the 5xx transport-failure branch: an
  undecodable 5xx body would have re-raised ``UnicodeDecodeError``
  inside the ``transport_error_cls(...)`` constructor arg, masking the
  typed exception and bypassing ``on_failure``. Same defect class #90
  fixed in ``MalformedResponseError.from_response``; #96 made the 5xx
  branch's construction observable for the first time, surfacing it
  for the test agent to close in this same bundle.

Doc-only (#100, #101) and the unreachable ``# pragma: no cover`` marker
escape guard (#103) are intentionally not unit-tested here.

Hermetic — no MongoDB / Redis / Ollama. The pure helpers take a
duck-typed response; HttpClient takes an injected mock session; the
gemini test drives ``_add_files`` against a MagicMock client.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

from autonomous.ai.exceptions import (
    MALFORMED_2XX_EXCEPTIONS,
    MalformedResponseError,
)
from autonomous.ai.models.openai_compat import (
    _CHAT_ENDPOINT,
    _EMBEDDINGS_ENDPOINT,
    _TRANSCRIPTION_ENDPOINT,
    _extract_or_malformed,
    _normalize_transcription_body,
)
from autonomous.http import HttpClient, TransportError


# ---------------------------------------------------------------------------
# Helpers — a minimal duck-typed response and a mock session, matching the
# shapes the production code touches (``.json()`` / ``.text`` / ``.content``
# / ``.status_code``). Kept local so these tests don't lean on a shared
# fixture the dev agent could have shaped.
# ---------------------------------------------------------------------------


class _FakeResponse:
    """``requests.Response``-shaped stand-in.

    ``json_value`` is returned by ``.json()``; if ``json_exc`` is set,
    ``.json()`` raises it instead (the non-JSON-body path). ``.text``
    raises ``text_exc`` when set (the undecodable-charset path)."""

    def __init__(
        self,
        *,
        json_value=None,
        json_exc=None,
        text="",
        text_exc=None,
        content=b"",
        status_code=200,
    ):
        self._json_value = json_value
        self._json_exc = json_exc
        self._text = text
        self._text_exc = text_exc
        self.content = content
        self.status_code = status_code

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._json_value

    @property
    def text(self):
        if self._text_exc is not None:
            raise self._text_exc
        return self._text


def _mock_response(status_code: int, text: str = "") -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} error", response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def _mock_session(*side_effects) -> MagicMock:
    session = MagicMock(spec=requests.Session)
    session.request.side_effect = side_effects
    return session


def _undecodable_error() -> UnicodeDecodeError:
    # A real UnicodeDecodeError as ``response.text`` would raise when the
    # declared charset can't decode the bytes (0xFF is an invalid utf-8
    # start byte).
    return UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")


class _UndecodableResponse:
    """``requests.Response``-shaped object whose ``.text`` raises
    ``UnicodeDecodeError`` (the declared-charset-can't-decode failure
    mode) but whose ``.content`` is readable. Backs the 5xx-branch
    defensive-read test. A dedicated class avoids stubbing PropertyMock
    onto the shared ``MagicMock`` type, which would leak across other
    tests in the file."""

    def __init__(self, status_code: int = 503, content: bytes = b"latin-1 \xff"):
        self.status_code = status_code
        self.content = content

    @property
    def text(self) -> str:
        raise _undecodable_error()

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"{self.status_code} error", response=self
            )


# ---------------------------------------------------------------------------
# #102 — MALFORMED_2XX_EXCEPTIONS single source of truth
# ---------------------------------------------------------------------------


class TestMalformed2xxExceptionsConstant:
    def test_is_the_exact_documented_five_tuple_in_order(self):
        assert MALFORMED_2XX_EXCEPTIONS == (
            AttributeError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        )

    def test_every_member_is_an_exception_type(self):
        assert all(isinstance(t, type) for t in MALFORMED_2XX_EXCEPTIONS)
        assert all(issubclass(t, BaseException) for t in MALFORMED_2XX_EXCEPTIONS)

    def test_value_error_membership_covers_json_decode_error(self):
        """``response.json()`` raises ``json.JSONDecodeError`` on a non-JSON
        body — it's a ``ValueError`` subclass, so the constant catches it."""
        import json

        assert issubclass(json.JSONDecodeError, ValueError)
        assert any(
            issubclass(json.JSONDecodeError, t) for t in MALFORMED_2XX_EXCEPTIONS
        )


# ---------------------------------------------------------------------------
# #90 — MalformedResponseError.from_response defensive read
# ---------------------------------------------------------------------------


class TestMalformedResponseErrorFromResponse:
    def test_reads_text_status_and_endpoint_on_a_normal_response(self):
        resp = _FakeResponse(text="oops body", status_code=503)
        err = MalformedResponseError.from_response(
            resp, "bad shape", endpoint="/chat/completions"
        )
        assert isinstance(err, MalformedResponseError)
        assert err.endpoint == "/chat/completions"
        assert err.status == 503
        assert err.body_excerpt == "oops body"
        assert "bad shape" in str(err)

    def test_undecodable_text_falls_back_to_lenient_content_decode(self):
        """The whole point of #90: a body whose declared charset can't
        decode must NOT re-raise ``UnicodeDecodeError`` inside the
        constructor arg. ``from_response`` reads ``response.content``
        leniently (``errors="replace"``) so the typed exception still
        raises."""
        raw = b"latin-1 bytes \xff\xfe here"
        resp = _FakeResponse(
            text_exc=_undecodable_error(), content=raw, status_code=200
        )
        # Must not raise UnicodeDecodeError — must return the typed error.
        err = MalformedResponseError.from_response(resp, "undecodable", endpoint="/x")
        assert isinstance(err, MalformedResponseError)
        assert err.endpoint == "/x"
        # U+FFFD replacement char survives instead of a crash.
        assert "�" in err.body_excerpt

    def test_undecodable_fallback_excerpt_is_bounded(self):
        raw = b"\xff" * 5000
        resp = _FakeResponse(text_exc=_undecodable_error(), content=raw)
        err = MalformedResponseError.from_response(resp, "big", endpoint="/x")
        assert len(err.body_excerpt) <= MalformedResponseError._EXCERPT_MAX

    def test_missing_status_code_attribute_degrades_to_none(self):
        """``getattr(response, "status_code", None)`` — a response object
        that doesn't carry ``status_code`` yields ``status=None`` rather
        than an AttributeError."""
        resp = SimpleNamespace(text="body", content=b"body")  # no status_code
        err = MalformedResponseError.from_response(resp, "msg", endpoint="/y")
        assert err.status is None
        assert err.body_excerpt == "body"


# ---------------------------------------------------------------------------
# #104 — body_excerpt coercion accepts memoryview
# ---------------------------------------------------------------------------


class TestBodyExcerptMemoryview:
    def test_memoryview_of_bytes_is_decoded(self):
        err = MalformedResponseError(
            "m", body_excerpt=memoryview(b"hello view")
        )
        assert err.body_excerpt == "hello view"

    def test_memoryview_slice_is_materialized_then_decoded(self):
        err = MalformedResponseError(
            "m", body_excerpt=memoryview(b"abcdefgh")[2:5]
        )
        assert err.body_excerpt == "cde"

    def test_memoryview_with_invalid_utf8_uses_replacement_not_crash(self):
        err = MalformedResponseError(
            "m", body_excerpt=memoryview(b"ok\xffno")
        )
        assert "�" in err.body_excerpt
        assert err.body_excerpt.startswith("ok")


# ---------------------------------------------------------------------------
# #88 — null-safe transcription normalization (THE headline bug)
# ---------------------------------------------------------------------------


class TestNormalizeTranscriptionBody:
    def test_null_text_and_segments_collapse_to_documented_defaults(self):
        """``{"text": null, "segments": null}`` is legal JSON a server
        returns when nothing was transcribed. ``dict.get(k, default)``
        returns the STORED None (default only fires on an absent key), so
        pre-#88 a caller doing ``result["text"].strip()`` hit
        ``AttributeError: 'NoneType'``. Normalize to ``str`` / ``list``."""
        assert _normalize_transcription_body({"text": None, "segments": None}) == {
            "text": "",
            "segments": [],
        }

    def test_valid_body_passes_through_unchanged(self):
        body = {"text": "hello world", "segments": [{"id": 0, "text": "hello world"}]}
        assert _normalize_transcription_body(body) == body

    def test_wrong_typed_values_collapse_to_defaults(self):
        # text as int, segments as dict — neither matches the documented
        # str/list contract, so both collapse.
        assert _normalize_transcription_body({"text": 42, "segments": {"x": 1}}) == {
            "text": "",
            "segments": [],
        }

    def test_absent_keys_use_defaults(self):
        assert _normalize_transcription_body({}) == {"text": "", "segments": []}

    def test_only_text_and_segments_are_returned(self):
        out = _normalize_transcription_body(
            {"text": "hi", "segments": [], "language": "en", "duration": 1.2}
        )
        assert out == {"text": "hi", "segments": []}

    def test_non_dict_body_raises_attributeerror_for_helper_to_translate(self):
        """``body.get`` against a non-dict raises ``AttributeError`` — which
        is in ``MALFORMED_2XX_EXCEPTIONS`` so ``_extract_or_malformed``
        translates it. Pin that the raw stdlib type escapes the normalizer
        (the translation happens one level up)."""
        with pytest.raises(AttributeError):
            _normalize_transcription_body(["not", "a", "dict"])


# ---------------------------------------------------------------------------
# #92 — _extract_or_malformed shared parse + walk + translate
# ---------------------------------------------------------------------------


class TestExtractOrMalformed:
    def test_extractor_success_returns_walked_value(self):
        resp = _FakeResponse(json_value={"choices": [{"message": {"content": "hi"}}]})
        out = _extract_or_malformed(
            resp,
            _CHAT_ENDPOINT,
            lambda body: body["choices"][0]["message"]["content"],
        )
        assert out == "hi"

    def test_empty_choices_index_error_is_translated_not_leaked(self):
        """The walk is passed as a callable so it runs INSIDE the protected
        block — an empty ``{"choices": []}`` raises ``IndexError`` which is
        caught and translated, never leaked raw to the caller (#92's stated
        guarantee)."""
        resp = _FakeResponse(json_value={"choices": []}, text="{}", status_code=200)
        with pytest.raises(MalformedResponseError) as ei:
            _extract_or_malformed(
                resp,
                _CHAT_ENDPOINT,
                lambda body: body["choices"][0]["message"]["content"],
            )
        assert ei.value.endpoint == _CHAT_ENDPOINT
        assert ei.value.status == 200
        # cause chain preserved (raise ... from exc)
        assert isinstance(ei.value.__cause__, IndexError)

    def test_missing_key_is_translated(self):
        resp = _FakeResponse(json_value={"data": [{}]}, text="{}")
        with pytest.raises(MalformedResponseError):
            _extract_or_malformed(
                resp,
                _EMBEDDINGS_ENDPOINT,
                lambda body: body["data"][0]["embedding"],
            )

    def test_non_json_body_value_error_is_translated(self):
        resp = _FakeResponse(
            json_exc=ValueError("Expecting value: line 1 column 1"),
            text="<html>nope</html>",
            content=b"<html>nope</html>",
            status_code=200,
        )
        with pytest.raises(MalformedResponseError) as ei:
            _extract_or_malformed(resp, _CHAT_ENDPOINT, lambda b: b["x"])
        assert isinstance(ei.value.__cause__, ValueError)
        assert ei.value.body_excerpt == "<html>nope</html>"

    def test_translation_uses_from_response_defensive_read(self):
        """Even when the malformed body is also undecodable, the translation
        must not crash — proves the helper routes through ``from_response``
        (#90), not a bare ``body_excerpt=response.text``."""
        resp = _FakeResponse(
            json_exc=ValueError("boom"),
            text_exc=_undecodable_error(),
            content=b"\xff\xfe raw",
            status_code=200,
        )
        with pytest.raises(MalformedResponseError) as ei:
            _extract_or_malformed(resp, _TRANSCRIPTION_ENDPOINT, lambda b: b)
        assert "�" in ei.value.body_excerpt


class TestEndpointConstants:
    def test_endpoint_constants_match_documented_paths(self):
        assert _CHAT_ENDPOINT == "/chat/completions"
        assert _TRANSCRIPTION_ENDPOINT == "/audio/transcriptions"
        assert _EMBEDDINGS_ENDPOINT == "/embeddings"


# ---------------------------------------------------------------------------
# #96 — HttpClient fires on_failure on the transport-STATUS branch
# ---------------------------------------------------------------------------


class TestOnFailureFiresOnTransportStatus:
    def test_5xx_fires_on_failure_with_transport_error(self):
        """Pre-#96 the 5xx branch raised WITHOUT notifying on_failure, so a
        transport-degradation counter saw 4xx (via #91) but missed 5xx —
        inverted. Now all three failure paths notify the hook."""
        on_failure = MagicMock()
        session = _mock_session(_mock_response(503, "down"))
        c = HttpClient(session=session, max_attempts=1, on_failure=on_failure)
        with pytest.raises(TransportError):
            c.request("GET", "http://x/y")
        on_failure.assert_called_once()
        method, url, exc, attempt = on_failure.call_args.args
        assert method == "GET"
        assert url == "http://x/y"
        assert isinstance(exc, TransportError)
        assert attempt == 1

    def test_configured_extra_code_also_fires_on_failure(self):
        """A 429 routed through ``transport_failure_codes`` is a
        transport-status failure too — it must fire the hook."""
        on_failure = MagicMock()
        session = _mock_session(_mock_response(429, "slow down"))
        c = HttpClient(
            session=session,
            max_attempts=1,
            transport_failure_codes={429},
            on_failure=on_failure,
        )
        with pytest.raises(TransportError):
            c.request("GET", "http://x")
        on_failure.assert_called_once()
        assert isinstance(on_failure.call_args.args[2], TransportError)

    def test_on_failure_fires_once_per_attempt_on_retried_5xx(self):
        on_failure = MagicMock()
        session = _mock_session(_mock_response(500, "a"), _mock_response(500, "b"))
        c = HttpClient(
            session=session,
            max_attempts=2,
            retry_backoff=0,
            on_failure=on_failure,
        )
        with pytest.raises(TransportError):
            c.request("GET", "http://x")
        assert on_failure.call_count == 2
        # 1-indexed attempt numbers across the two failures
        assert [call.args[3] for call in on_failure.call_args_list] == [1, 2]

    def test_2xx_success_does_not_fire_on_failure(self):
        on_failure = MagicMock()
        session = _mock_session(_mock_response(200, "ok"))
        c = HttpClient(session=session, on_failure=on_failure)
        c.request("GET", "http://x")
        on_failure.assert_not_called()

    def test_undecodable_5xx_body_does_not_mask_transport_error_or_skip_hook(self):
        """Defensive .text read on the 5xx branch: a body whose declared
        charset can't decode used to re-raise ``UnicodeDecodeError`` inside
        the ``transport_error_cls(...)`` constructor arg, before
        ``on_failure`` could fire. Caller saw the raw ``UnicodeDecodeError``,
        not the configured ``transport_error_cls``; the hook never observed
        the 5xx. Same defect class #90 fixed in
        ``MalformedResponseError.from_response`` — #96 made this branch's
        error construction observable for the first time, surfacing the
        latent hole."""
        on_failure = MagicMock()
        session = _mock_session(_UndecodableResponse(status_code=503))
        c = HttpClient(session=session, max_attempts=1, on_failure=on_failure)
        # Must raise the typed TransportError, NOT the raw UnicodeDecodeError.
        with pytest.raises(TransportError) as ei:
            c.request("GET", "http://x/y")
        # Hook still fires with the typed exception.
        on_failure.assert_called_once()
        assert isinstance(on_failure.call_args.args[2], TransportError)
        # Excerpt fell back to lenient content decode — status + replacement
        # char both survive in the message.
        msg = str(ei.value)
        assert "503" in msg
        assert "�" in msg  # U+FFFD REPLACEMENT CHARACTER


# ---------------------------------------------------------------------------
# #98 — HttpClient rejects an over-broad transport_error_cls
# ---------------------------------------------------------------------------


class TestRejectOverBroadTransportErrorCls:
    def test_exception_is_rejected(self):
        with pytest.raises(ValueError, match="too broad"):
            HttpClient(transport_error_cls=Exception)

    def test_base_exception_is_rejected(self):
        with pytest.raises(ValueError, match="too broad"):
            HttpClient(transport_error_cls=BaseException)

    @pytest.mark.parametrize(
        "cls",
        [
            requests.RequestException,
            requests.ConnectionError,
            TransportError,
        ],
    )
    def test_narrow_classes_are_accepted(self, cls):
        # Must construct without raising.
        c = HttpClient(transport_error_cls=cls)
        assert c.transport_error_cls is cls

    def test_runtime_error_subclass_is_accepted(self):
        class HPCUnreachableError(RuntimeError):
            pass

        c = HttpClient(transport_error_cls=HPCUnreachableError)
        assert c.transport_error_cls is HPCUnreachableError

    def test_default_construction_is_unaffected(self):
        # The default transport_error_cls (TransportError) is narrow.
        assert HttpClient().transport_error_cls is TransportError


# ---------------------------------------------------------------------------
# #89 — FluxAIModel retries 408 / 429 throttling again
# ---------------------------------------------------------------------------


class TestFluxThrottlingRetry:
    def test_flux_http_classifies_408_and_429_as_transport(self):
        from autonomous.ai.models import flux

        assert {408, 429} <= flux._HTTP.transport_failure_codes

    def test_flux_http_keeps_narrowed_connection_error_cls(self):
        """#85's narrowing to ConnectionError (fail-fast on permanent 4xx)
        is preserved — #89 only ADDS 408/429 routing, it doesn't widen the
        error class back."""
        from autonomous.ai.models import flux

        assert flux._HTTP.transport_error_cls is requests.ConnectionError

    def test_429_is_retried_while_404_fails_fast_under_same_config(self):
        """Behavioral proof of the #89 routing on a client built with flux's
        exact transport config: a 429 retries (transport-class), a 404 fails
        fast as a raw HTTPError (permanent client error)."""
        # 429 twice → retried, then raises the configured ConnectionError.
        throttled = _mock_session(_mock_response(429, "rate"), _mock_response(429, "rate"))
        c1 = HttpClient(
            session=throttled,
            max_attempts=2,
            retry_backoff=0,
            transport_error_cls=requests.ConnectionError,
            transport_failure_codes={408, 429},
        )
        with pytest.raises(requests.ConnectionError):
            c1.request("GET", "http://fal/run")
        assert throttled.request.call_count == 2  # the 429 burned the retry budget

        # 404 → permanent; fails fast as HTTPError, no retry budget spent.
        missing = _mock_session(_mock_response(404, "gone"))
        c2 = HttpClient(
            session=missing,
            max_attempts=3,
            retry_backoff=0,
            transport_error_cls=requests.ConnectionError,
            transport_failure_codes={408, 429},
        )
        with pytest.raises(requests.HTTPError):
            c2.request("GET", "http://fal/result")
        assert missing.request.call_count == 1


# ---------------------------------------------------------------------------
# #93 — Gemini orphan-cleanup delete failures are logged (was silent pass)
# ---------------------------------------------------------------------------


class _GeminiAPIError(Exception):
    """Stand-in for ``google.genai.errors.APIError`` on the delete leg."""


def _gemini_stub(poll_states):
    """Minimal ``GeminiAIModel``-shaped stub driving ``_add_files``. Mirrors
    the harness in the PR #81 orphan-cleanup suite but kept independent.

    ``poll_states[0]`` is the upload handle's initial ``state.name``;
    ``poll_states[1:]`` are the states ``files.get`` returns on each poll.
    The poll loop reads ``uploaded_file.state.name``, so both the upload
    handle and each ``files.get`` result must be a HANDLE carrying a
    ``.state`` (with ``.name``) plus its own ``.name``."""

    class _Stub:
        MAX_FILES = 10

        def save(self):
            pass

    def _handle(state_name):
        h = MagicMock()
        h.name = "files/upload-0"
        state = MagicMock()
        state.name = state_name
        h.state = state
        return h

    stub = _Stub()
    stub.client = MagicMock()
    upload_h = _handle(poll_states[0])
    poll_handles = [_handle(s) for s in poll_states[1:]]
    stub.client.files.upload = MagicMock(side_effect=[upload_h])
    stub.client.files.get = MagicMock(side_effect=poll_handles or [upload_h])
    stub.client.files.list = MagicMock(return_value=[])
    return stub


class TestGeminiOrphanCleanupLogged:
    def test_delete_failure_is_logged_and_original_exception_re_raised(self, monkeypatch):
        """Pre-#93 a cleanup-delete failure was swallowed by a bare
        ``except: pass`` — invisible. A future SDK change rejecting some
        ``orphan.name`` format would leak Gemini file quota with zero
        operator signal. The delete failure must now be logged (file only,
        ``_print=False``) while the ORIGINAL poll timeout still propagates."""
        from autonomous.ai.exceptions import GeminiFileUploadTimeoutError
        from autonomous.ai.models import gemini

        monkeypatch.setattr(
            gemini.genai.errors, "APIError", _GeminiAPIError, raising=False
        )
        monkeypatch.setenv("GEMINI_UPLOAD_POLL_TIMEOUT", "1")

        stub = _gemini_stub(["PROCESSING", "PROCESSING", "PROCESSING"])

        # The orphan-handle delete fails; the pre-upload (filename-keyed)
        # delete is unaffected.
        def fake_delete(name=None):
            if name and name.startswith("files/upload-"):
                raise _GeminiAPIError("delete outage")
            return None

        stub.client.files.delete = MagicMock(side_effect=fake_delete)

        logged: list[tuple] = []

        def fake_log(line, *args, _print=True, **kwargs):
            logged.append((line, _print))

        monkeypatch.setattr(gemini, "log", fake_log)

        times = iter([0.0, 0.0, 1.5, 3.0])
        with patch(
            "autonomous.ai.models.gemini.time.monotonic", side_effect=lambda: next(times)
        ), patch("autonomous.ai.models.gemini.time.sleep"):
            with pytest.raises(GeminiFileUploadTimeoutError):
                gemini.GeminiAIModel._add_files(
                    stub, [{"name": "file_0.json", "file": b"{}"}]
                )

        cleanup_lines = [
            (line, printed)
            for (line, printed) in logged
            if "orphan-cleanup delete failed" in line
        ]
        assert cleanup_lines, (
            f"the cleanup-delete failure must be logged (#93); logged={logged!r}"
        )
        line, printed = cleanup_lines[0]
        # the failing orphan handle name appears in the line for traceability
        assert "files/upload-0" in line
        # log file only — the user sees the original poll exception, not this
        assert printed is False


# ---------------------------------------------------------------------------
# #94 — bounded ThreadPoolExecutor orphan cleanup, all-orphans-attempted
# ---------------------------------------------------------------------------


class TestGeminiOrphanCleanupParallelization:
    def test_all_orphans_attempted_when_some_deletes_fail(self, monkeypatch):
        """#94: bounded ``ThreadPoolExecutor`` must process ALL N orphans
        even when some deletes raise. ``_delete_orphan`` swallows its own
        exceptions so ``executor.map`` materialization can't short-circuit
        on the first failure (which would leak Gemini file quota for the
        remaining orphans). ``list(...)`` forces every delete to finish
        BEFORE the original poll exception re-raises.

        Regression coverage:
        * Pre-#94 N serial blocking deletes could sum past the RQ job
          deadline, replacing ``GeminiFileUploadTimeoutError`` with
          ``rq.exceptions.JobTimeoutError``. A refactor reverting to
          ``for orphan in uploaded_files: _delete_orphan(orphan)``
          would only fail at integration; this test catches it at unit.
        * A refactor dropping ``list(...)`` (turning the executor.map
          into a generator that's never consumed) would let some deletes
          race the ``raise`` and never fire — this test's per-orphan
          attempt count catches that too.

        Setup uploads four files. The first three transition to ACTIVE
        immediately (poll loop never enters); the fourth stays
        PROCESSING and trips the deadline. The cleanup therefore runs
        on all four ``uploaded_files``. Two of the four orphan deletes
        fail (at non-adjacent positions, so a "stop on first failure"
        regression can't pass by accident). The test asserts all four
        delete attempts fired AND both failure log lines emitted.
        """
        from autonomous.ai.exceptions import GeminiFileUploadTimeoutError
        from autonomous.ai.models import gemini

        monkeypatch.setattr(
            gemini.genai.errors, "APIError", _GeminiAPIError, raising=False
        )
        monkeypatch.setenv("GEMINI_UPLOAD_POLL_TIMEOUT", "1")

        class _Stub:
            MAX_FILES = 10

            def save(self):
                pass

        def _handle(idx, state_name):
            h = MagicMock()
            h.name = f"files/upload-{idx}"
            state = MagicMock()
            state.name = state_name
            h.state = state
            return h

        # First three uploads return ACTIVE handles (poll skipped);
        # the fourth returns a PROCESSING handle (poll enters → times out).
        upload_handles = [_handle(i, "ACTIVE") for i in range(3)] + [
            _handle(3, "PROCESSING")
        ]

        stub = _Stub()
        stub.client = MagicMock()
        stub.client.files.upload = MagicMock(side_effect=upload_handles)
        # files.get only fires for the fourth handle's poll iterations.
        stub.client.files.get = MagicMock(
            side_effect=[_handle(3, "PROCESSING")] * 5
        )
        stub.client.files.list = MagicMock(return_value=[])

        delete_attempts: list[str | None] = []

        def fake_delete(name=None):
            delete_attempts.append(name)
            # Failures at positions 1 and 3 (non-adjacent) defeat a
            # "stop on first error" regression.
            if name in ("files/upload-1", "files/upload-3"):
                raise _GeminiAPIError(f"delete failed for {name}")
            return None

        stub.client.files.delete = MagicMock(side_effect=fake_delete)

        logged: list[tuple[str, bool]] = []

        def fake_log(line, *args, _print=True, **kwargs):
            logged.append((line, _print))

        monkeypatch.setattr(gemini, "log", fake_log)

        # 4 deadline-set calls (one per file) + 1 deadline-check call on
        # the fourth file's poll = 5 monotonic invocations.
        times = iter([0.0, 0.0, 0.0, 0.0, 100.0])
        with patch(
            "autonomous.ai.models.gemini.time.monotonic",
            side_effect=lambda: next(times),
        ), patch("autonomous.ai.models.gemini.time.sleep"):
            with pytest.raises(GeminiFileUploadTimeoutError):
                gemini.GeminiAIModel._add_files(
                    stub,
                    [{"name": f"file_{i}.json", "file": b"{}"} for i in range(4)],
                )

        # Filter pre-upload deletes (filename-keyed, e.g. "file_0.json")
        # from orphan deletes (handle-name-keyed, "files/upload-*").
        orphan_attempts = sorted(
            n for n in delete_attempts if n and n.startswith("files/upload-")
        )
        assert orphan_attempts == [
            "files/upload-0",
            "files/upload-1",
            "files/upload-2",
            "files/upload-3",
        ], (
            f"#94 invariant: ALL 4 orphan deletes must be attempted "
            f"regardless of intermediate failures; got {orphan_attempts}"
        )

        # Both failures are logged (#93); the two successes have no
        # cleanup-failure log line.
        failure_lines = [line for (line, _) in logged if "orphan-cleanup delete failed" in line]
        assert len(failure_lines) == 2, (
            f"expected 2 cleanup-failure log lines (deletes 1 and 3); "
            f"got {failure_lines!r}"
        )
        all_failure_text = "\n".join(failure_lines)
        assert "files/upload-1" in all_failure_text
        assert "files/upload-3" in all_failure_text


# ---------------------------------------------------------------------------
# #105 — the autouse _UNSUPPORTED_STRICT_MODE isolation fixture (test agent's
# exclusive surface; the fixture lives in tests/unit/conftest.py). These two
# tests are ORDER-DEPENDENT BY DESIGN: part1 pollutes the process-global
# cache, part2 asserts the pollution did not leak. part2 passing is exactly
# the evidence the autouse snapshot/restore fixture works — if the fixture
# regressed, the sentinel would survive into part2 and it would fail.
# ---------------------------------------------------------------------------


_STRICT_CACHE_SENTINEL = ("__iter_2026_06_11e_sentinel_model__", "/__sentinel__")


class TestStrictModeCacheIsolation:
    def test_part1_pollutes_the_strict_mode_cache(self):
        from autonomous.ai.models import openai_compat

        assert _STRICT_CACHE_SENTINEL not in openai_compat._UNSUPPORTED_STRICT_MODE
        openai_compat._UNSUPPORTED_STRICT_MODE.add(_STRICT_CACHE_SENTINEL)
        assert _STRICT_CACHE_SENTINEL in openai_compat._UNSUPPORTED_STRICT_MODE

    def test_part2_does_not_see_part1s_pollution(self):
        """Runs after part1 in definition order. The autouse fixture in
        ``tests/unit/conftest.py`` must have restored the cache at part1's
        teardown — so the sentinel is gone. A failure here means the #105
        isolation fixture regressed (process-global state leaking across
        tests)."""
        from autonomous.ai.models import openai_compat

        assert _STRICT_CACHE_SENTINEL not in openai_compat._UNSUPPORTED_STRICT_MODE
