"""Independent coverage for PR #115 (orin-voice bearer header + ogg passthrough).

PR #115 wires the consumer side of the orin-voice integration into
``LocalAIModel.generate_transcription`` and ``LocalAIModel.generate_audio``.
Three contracts are introduced:

1. **Bearer header.** Both methods now send
   ``Authorization: Bearer <ORIN_VOICE_TOKEN>``. The token is sourced
   from ``env_str('ORIN_VOICE_TOKEN', '')`` with NO special-casing of
   the empty case — the literal string ``"Bearer "`` is sent so a
   misconfigured deploy fails as a server-visible 401 rather than a
   silent header omission (loud-misconfig contract).

2. **Accept header.** ``generate_audio`` sends
   ``Accept: audio/ogg, audio/wav;q=0.5`` — orin-voice native is
   opus-in-ogg, but a legacy wav-only ``MEDIA_AUDIO_API_BASE_URL``
   still works as a fallback.

3. **Content-Type branching.** ``generate_audio`` keys passthrough
   vs. transcode on the RESPONSE's Content-Type (not the request
   preference). ``"ogg"`` or ``"opus"`` substring in the lower-cased
   header → return ``response.content`` verbatim (no wav decode +
   opus re-encode). Anything else (``audio/wav``, unset) goes
   through the historical ``AudioSegment.from_file(..., 'wav')`` →
   ``export(..., 'opus')`` path.

Independent perspective: pin the request shape (headers correctly
formed, env-sourcing happens with no special-casing, other kwargs
pass through unmodified), the response branching (every documented
Content-Type case, plus uppercase to enforce ``.lower()``), and
source-level revert canaries.
"""

from unittest.mock import MagicMock

import pytest

from autonomous.ai.models import local_model
from autonomous.ai.models.local_model import LocalAIModel


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def model():
    """LocalAIModel with media URL pinned to a sentinel so endpoint
    assertions stay stable regardless of env."""
    m = LocalAIModel()
    m._audio_url = "http://orin-voice:8000"
    m._media_timeout = 5
    return m


@pytest.fixture
def patch_autotasks(monkeypatch):
    """Bypass the rq/Redis side of AutoTasks().get_current_task() — unit
    tests must never touch Redis."""

    class _Stub:
        def get_current_task(self):
            return None

    monkeypatch.setattr(local_model, "AutoTasks", lambda: _Stub())


def _make_response(content=b"", content_type=None, status=200):
    """Stub Response with the headers + body the call sites read."""
    resp = MagicMock()
    resp.status_code = status
    resp.content = content
    resp.headers = {} if content_type is None else {"Content-Type": content_type}
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value={"segments": [], "text": ""})
    return resp


def _patch_post(monkeypatch, response):
    """Replace local_model._HTTP.post with a recorder returning ``response``.
    Returns the call log: each entry is ``(args, kwargs)``."""
    calls = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return response

    monkeypatch.setattr(local_model._HTTP, "post", fake_post)
    return calls


# ---------------------------------------------------------------------------
# A. generate_transcription request shape
# ---------------------------------------------------------------------------


class TestTranscriptionRequestShape:
    def test_authorization_header_sent(self, model, monkeypatch, patch_autotasks):
        """generate_transcription must wire ``Authorization: Bearer <token>``
        through to ``_HTTP.post(..., headers=...)``. Regression if the
        headers dict is built but never reaches the call."""
        monkeypatch.setenv("ORIN_VOICE_TOKEN", "test-token-123")
        calls = _patch_post(monkeypatch, _make_response())

        model.generate_transcription(b"audio bytes")

        assert len(calls) == 1
        _, kwargs = calls[0]
        assert "headers" in kwargs, "headers kwarg missing — bearer wiring not reaching _HTTP.post"
        assert kwargs["headers"].get("Authorization") == "Bearer test-token-123"

    def test_token_sourced_from_env_var(self, model, monkeypatch, patch_autotasks):
        """The token MUST come from the ORIN_VOICE_TOKEN env var at
        call-time via env_str(...). Hard-coding or settings-lookup
        would defeat consumer-side rotation."""
        monkeypatch.setenv("ORIN_VOICE_TOKEN", "rotated-token-xyz")
        calls = _patch_post(monkeypatch, _make_response())

        model.generate_transcription(b"audio bytes")

        assert calls[0][1]["headers"]["Authorization"] == "Bearer rotated-token-xyz"

    def test_unset_token_emits_literal_bearer_space(self, model, monkeypatch, patch_autotasks):
        """Loud-misconfig contract: an unset ORIN_VOICE_TOKEN must produce
        ``Authorization: Bearer `` (literal trailing space, no value).
        No fallback, no header omission — the misconfigured deploy MUST
        surface as a server-visible 401."""
        monkeypatch.delenv("ORIN_VOICE_TOKEN", raising=False)
        calls = _patch_post(monkeypatch, _make_response())

        model.generate_transcription(b"audio bytes")

        assert calls[0][1]["headers"]["Authorization"] == "Bearer "

    def test_existing_kwargs_still_passed_through(self, model, monkeypatch, patch_autotasks):
        """Header insertion must not drop files= / data= / timeout=
        or rewrite the endpoint."""
        monkeypatch.setenv("ORIN_VOICE_TOKEN", "tk")
        calls = _patch_post(monkeypatch, _make_response())

        model.generate_transcription(b"audio bytes", prompt="hi", beam_size=7)

        args, kwargs = calls[0]
        assert "files" in kwargs and "file" in kwargs["files"]
        assert kwargs["data"] == {"prompt": "hi", "beam_size": 7}
        assert kwargs["timeout"] == 5  # _media_timeout
        assert args[0] == "http://orin-voice:8000/transcribe"


# ---------------------------------------------------------------------------
# B. generate_audio request shape
# ---------------------------------------------------------------------------


class TestAudioRequestShape:
    def test_authorization_header_sent(self, model, monkeypatch, patch_autotasks):
        monkeypatch.setenv("ORIN_VOICE_TOKEN", "tts-token")
        calls = _patch_post(monkeypatch, _make_response(b"\x00", "audio/ogg"))

        model.generate_audio("hello")

        _, kwargs = calls[0]
        assert kwargs["headers"]["Authorization"] == "Bearer tts-token"

    def test_accept_header_exact_format(self, model, monkeypatch, patch_autotasks):
        """Accept header pins q-value ordering — ogg/opus preferred,
        wav as q=0.5 fallback. Regression if either dimension drifts
        without bumping the documented spec."""
        monkeypatch.setenv("ORIN_VOICE_TOKEN", "tk")
        calls = _patch_post(monkeypatch, _make_response(b"\x00", "audio/ogg"))

        model.generate_audio("hi")

        assert calls[0][1]["headers"]["Accept"] == "audio/ogg, audio/wav;q=0.5"

    def test_payload_and_endpoint_unchanged(self, model, monkeypatch, patch_autotasks):
        """json= payload and /tts endpoint must survive the header insertion."""
        monkeypatch.setenv("ORIN_VOICE_TOKEN", "tk")
        calls = _patch_post(monkeypatch, _make_response(b"\x00", "audio/ogg"))

        model.generate_audio("hello", voice_id="alice", voice_description="warm")

        args, kwargs = calls[0]
        assert args[0] == "http://orin-voice:8000/tts"
        assert kwargs["json"] == {
            "text": "hello",
            "voice_id": "alice",
            "voice_description": "warm",
        }
        assert kwargs["timeout"] == 5


# ---------------------------------------------------------------------------
# C. generate_audio response Content-Type branching
# ---------------------------------------------------------------------------


class TestAudioContentTypeBranching:
    def test_audio_ogg_passthrough_no_transcode(self, model, monkeypatch, patch_autotasks):
        """audio/ogg → return response.content verbatim. AudioSegment.from_file
        MUST NOT be called (the passthrough IS the value — avoids
        server-decoded → client re-encoded round-trip)."""
        monkeypatch.setenv("ORIN_VOICE_TOKEN", "tk")
        ogg_bytes = b"\x4f\x67\x67\x53fake-opus-data"
        _patch_post(monkeypatch, _make_response(ogg_bytes, "audio/ogg"))

        from_file_called = []
        monkeypatch.setattr(
            local_model.AudioSegment,
            "from_file",
            lambda *a, **k: from_file_called.append((a, k)) or MagicMock(),
        )

        result = model.generate_audio("hello")

        assert result == ogg_bytes
        assert from_file_called == [], "wav transcode path taken despite audio/ogg Content-Type"

    def test_audio_opus_passthrough_no_transcode(self, model, monkeypatch, patch_autotasks):
        """audio/opus → also passthrough (the substring check is ``in``,
        so audio/opus, audio/ogg, audio/x-ogg-stream all bypass transcode)."""
        monkeypatch.setenv("ORIN_VOICE_TOKEN", "tk")
        opus_bytes = b"opus-frame-bytes"
        _patch_post(monkeypatch, _make_response(opus_bytes, "audio/opus"))

        from_file_called = []
        monkeypatch.setattr(
            local_model.AudioSegment,
            "from_file",
            lambda *a, **k: from_file_called.append((a, k)) or MagicMock(),
        )

        result = model.generate_audio("hello")

        assert result == opus_bytes
        assert from_file_called == []

    def test_content_type_match_is_case_insensitive(self, model, monkeypatch, patch_autotasks):
        """The branch uses .lower() — a server returning ``Audio/OGG``
        (or any other casing) MUST still take the passthrough path.
        A regression that drops .lower() would silently divert
        legitimate ogg responses through the wav-decoder, exploding
        downstream on "not a wav header"."""
        monkeypatch.setenv("ORIN_VOICE_TOKEN", "tk")
        ogg_bytes = b"oggbytes"
        _patch_post(monkeypatch, _make_response(ogg_bytes, "AUDIO/OGG"))

        from_file_called = []
        monkeypatch.setattr(
            local_model.AudioSegment,
            "from_file",
            lambda *a, **k: from_file_called.append((a, k)) or MagicMock(),
        )

        result = model.generate_audio("hello")

        assert result == ogg_bytes
        assert from_file_called == []

    def test_audio_wav_goes_through_transcode(self, model, monkeypatch, patch_autotasks):
        """audio/wav → AudioSegment.from_file(buf, format='wav') →
        export(..., format='opus'). The historical path stays intact
        for legacy ``media_ai`` CPU sidecar servers."""
        monkeypatch.setenv("ORIN_VOICE_TOKEN", "tk")
        wav_bytes = b"RIFFfake-wav-bytes"
        _patch_post(monkeypatch, _make_response(wav_bytes, "audio/wav"))

        transcoded_bytes = b"opus-transcoded-output"
        from_file_calls = []
        export_calls = []

        class _StubAudio:
            def export(self, buf, format):
                export_calls.append(format)
                buf.write(transcoded_bytes)

        def fake_from_file(buf, format):
            from_file_calls.append((buf.read(), format))
            return _StubAudio()

        monkeypatch.setattr(local_model.AudioSegment, "from_file", fake_from_file)

        result = model.generate_audio("hello")

        assert from_file_calls, "wav Content-Type should go through AudioSegment.from_file"
        assert from_file_calls[0][0] == wav_bytes  # the response bytes wrapped in BytesIO
        assert from_file_calls[0][1] == "wav"
        assert export_calls == ["opus"]
        assert result == transcoded_bytes

    def test_unset_content_type_defaults_to_wav_path(self, model, monkeypatch, patch_autotasks):
        """Response with no Content-Type header at all goes through the
        wav path (response.headers.get('Content-Type', '') → '' → neither
        'ogg' nor 'opus' is in ''). Defensive default documented in the
        implementation comment."""
        monkeypatch.setenv("ORIN_VOICE_TOKEN", "tk")
        _patch_post(monkeypatch, _make_response(b"\x00\x01\x02", content_type=None))

        from_file_called = []

        class _StubAudio:
            def export(self, buf, format):
                buf.write(b"transcoded")

        def fake_from_file(buf, format):
            from_file_called.append(format)
            return _StubAudio()

        monkeypatch.setattr(local_model.AudioSegment, "from_file", fake_from_file)

        result = model.generate_audio("hello")

        assert from_file_called == ["wav"]
        assert result == b"transcoded"


# ---------------------------------------------------------------------------
# D. Error-return contracts (caller-visible failure shape)
# ---------------------------------------------------------------------------


class TestErrorReturnContracts:
    """Callers depend on the methods returning sentinel values rather than
    raising. ``generate_transcription`` must return
    ``{"segments": [], "text": ""}`` so callers iterating ``result["segments"]``
    don't TypeError. ``generate_audio`` must return ``None`` so callers can
    distinguish "speech failed" from "speech succeeded with empty bytes".
    A future refactor narrowing the catch tuple, or letting an exception
    escape the wav-decode path, would silently break TTS/STT callers."""

    def test_transcription_returns_empty_shape_on_http_error(self, model, monkeypatch, patch_autotasks):
        """401/403/5xx (anything that raises via ``raise_for_status``) must
        come back as the empty-segments dict, not raise and not None."""
        import requests as _requests

        monkeypatch.setenv("ORIN_VOICE_TOKEN", "tk")
        resp = _make_response()
        resp.raise_for_status = MagicMock(side_effect=_requests.HTTPError("401 Unauthorized"))
        _patch_post(monkeypatch, resp)

        result = model.generate_transcription(b"audio bytes")

        assert result == {"segments": [], "text": ""}

    def test_audio_returns_none_on_http_error(self, model, monkeypatch, patch_autotasks):
        """A 401 from a bad ORIN_VOICE_TOKEN (or any 5xx) must surface as
        ``None`` — the loud-misconfig contract holds via the log line, but
        callers see a typed sentinel."""
        import requests as _requests

        monkeypatch.setenv("ORIN_VOICE_TOKEN", "stale-token")
        resp = _make_response()
        resp.raise_for_status = MagicMock(side_effect=_requests.HTTPError("401 Unauthorized"))
        _patch_post(monkeypatch, resp)

        assert model.generate_audio("hello") is None

    def test_audio_returns_none_on_pydub_decode_failure(self, model, monkeypatch, patch_autotasks):
        """The wav-path's ``AudioSegment.from_file(..., "wav")`` raises
        ``pydub.exceptions.CouldntDecodeError`` on non-wav bytes. That
        class inherits from ``PydubException``, NOT ``OSError`` —
        regression catch-tuple narrowing would let it escape. Pinned
        here so the contract stays explicit."""
        from pydub.exceptions import CouldntDecodeError

        monkeypatch.setenv("ORIN_VOICE_TOKEN", "tk")
        # Empty Content-Type → wav defensive path → pydub explodes on non-wav body.
        _patch_post(monkeypatch, _make_response(b"\x00\x01\x02not-wav", content_type=None))

        def fake_from_file(buf, format):
            raise CouldntDecodeError("Decoding failed: not a wav stream")

        monkeypatch.setattr(local_model.AudioSegment, "from_file", fake_from_file)

        assert model.generate_audio("hello") is None


# ---------------------------------------------------------------------------
# E. Source-level revert canaries
# ---------------------------------------------------------------------------


class TestSourcePins:
    """Brittle-by-design source pins that catch silent revert. A
    refactor that legitimately respells the contract will need to
    update both the implementation and these pins together."""

    def test_transcription_source_passes_headers_kwarg(self):
        import inspect

        src = inspect.getsource(LocalAIModel.generate_transcription)
        assert "ORIN_VOICE_TOKEN" in src, (
            "generate_transcription source dropped ORIN_VOICE_TOKEN env reference"
        )
        assert "headers=headers" in src or "headers = headers" in src, (
            "generate_transcription must pass headers= to _HTTP.post"
        )

    def test_audio_source_branches_on_content_type(self):
        import inspect

        src = inspect.getsource(LocalAIModel.generate_audio)
        assert "ORIN_VOICE_TOKEN" in src
        assert "Accept" in src, "generate_audio dropped Accept header"
        assert "Content-Type" in src, "generate_audio dropped Content-Type branching"
        assert "ogg" in src and "opus" in src, (
            "generate_audio passthrough substring check missing"
        )
