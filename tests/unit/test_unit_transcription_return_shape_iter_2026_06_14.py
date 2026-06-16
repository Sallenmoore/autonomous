"""Independent coverage for PR #127 — generate_transcription return
shape pins on mock + gemini (#47 slice 4, closes #47).

Dev's committed test (`TestSlice4ReturnShapes` appended to
`test_unit_ai_protocol_conformance.py`) verifies per-adapter that
the return is a dict with `{"text", "segments"}`, that mock's
generate_image/upscale_image return bytes, that mock's generate_json
returns a dict, and that gemini's transcription handles None text.

What's NOT covered:

- **Consumer access-pattern compatibility.** A return-shape change
  matters because the consumer code that depends on the shape
  changes too. Pin the access patterns
  (``result["text"].split()``, ``for seg in result["segments"]``,
  ``result.get("text", "")``) that audioagent.transcribe and
  consumer screenplay code actually use. A change that returned
  `{"text": ..., "segments": None}` would pass dev's "key present"
  check but break consumer iteration.
- **Identity preservation of the mock sentinel.** Pre-slice-4 the
  mock returned ``"This is a mock transcription of the audio file."``
  as a bare string. Existing tests grep that exact string. Verify
  the sentinel survives the wrapper change so unrelated tests don't
  silently break.
- **Cross-adapter homogeneity.** Dev tests each adapter on its own.
  Pin set-equality of keys across mock + gemini so a future slice
  adding "language" to gemini only gets caught.
- **Gemini's upload-then-transcribe call order.** Wrapping the
  return shouldn't have disturbed the upload step. Verify the
  ``client.files.upload`` happens BEFORE ``generate_content`` and
  the uploaded file lands in ``contents``.
- **`display_name` kwarg (extra-but-tolerated).** Protocol only
  requires `(audio_file, prompt="")`. Gemini accepts an extra
  `display_name=` — verify it's preserved (a regression that
  dropped it would break callers that customize the upload).
- **Mock determinism.** Same input → same output. Snapshot tests
  + integration tests using mock depend on this.
- **`generate_transcription` doesn't silently accept extra kwargs
  on mock.** Mock has its own signature `(audio_file, prompt="")`.
  A regression that loosened it to **kwargs would silently swallow
  bugs.

If any of those regress, dev's per-adapter shape check stays green
and mine catches it.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest

from autonomous.ai.models.gemini import GeminiAIModel
from autonomous.ai.models.mock_model import MockAIModel


# ---------------------------------------------------------------------------
# Mock-adapter coverage
# ---------------------------------------------------------------------------


class TestMockTranscriptionConsumerCompatibility:
    """Consumer code uses the result in specific ways — verify all
    of them work against the new dict shape.

    The mock provider is the offline test escape hatch — when
    integration tests substitute it for the real adapter, the
    consumer code path under test must run the same way. Common
    consumer patterns from `autonomous.ai.audioagent` and downstream
    screenplay code:
        - ``result["text"]`` (subscript access)
        - ``result.get("text", "")`` (default-fallback access)
        - ``len(result["segments"])`` (segments size)
        - ``for seg in result["segments"]:`` (iteration)
        - ``"".join(s["text"] for s in result["segments"])`` (join)
    """

    def _result(self) -> dict:
        mock = MockAIModel.__new__(MockAIModel)
        return mock.generate_transcription(b"audio-bytes")

    def test_subscript_access_returns_string(self):
        assert self._result()["text"] == \
            "This is a mock transcription of the audio file."

    def test_default_fallback_access_returns_string(self):
        result = self._result()
        # If a regression switched the value to None, .get("text", "")
        # would still return None — the assertion below catches it.
        assert result.get("text", "FALLBACK") != "FALLBACK"
        assert isinstance(result.get("text"), str)

    def test_segments_iteration_does_not_raise(self):
        # `for seg in result["segments"]` over None / a non-iterable
        # would raise TypeError. Iterating an empty list is a no-op
        # — that's the contract.
        result = self._result()
        for _seg in result["segments"]:
            pass  # no body — just verify no TypeError

    def test_segments_supports_len(self):
        result = self._result()
        assert len(result["segments"]) == 0

    def test_segments_supports_append_mutation(self):
        # Consumers may mutate the list (e.g. post-process to add
        # heuristic segments). Tuple/frozen list would break this.
        result = self._result()
        result["segments"].append({"text": "hello"})
        assert result["segments"] == [{"text": "hello"}]


class TestMockSentinelIdentityPreserved:
    """The exact mock text string is referenced in other tests and
    fixtures. Wrapping it in a dict shouldn't have changed the text.
    """

    def test_text_contains_mock_marker(self):
        # Any test grepping for "mock transcription" still works.
        mock = MockAIModel.__new__(MockAIModel)
        result = mock.generate_transcription(b"x")
        assert "mock transcription" in result["text"].lower()

    def test_text_exact_pre_slice_4_string(self):
        # Snapshot/fixture tests that hard-code the previous string
        # would silently drift if the wrapper rewording changed it.
        mock = MockAIModel.__new__(MockAIModel)
        result = mock.generate_transcription(b"x")
        assert result["text"] == \
            "This is a mock transcription of the audio file."


class TestMockSignaturePreserved:
    """Mock's generate_transcription signature is
    ``(self, audio_file, prompt="")`` — slice 4 wrapped the return
    but should NOT have loosened the signature to *args/**kwargs.
    """

    def test_audio_file_is_positional_or_keyword(self):
        sig = inspect.signature(MockAIModel.generate_transcription)
        assert "audio_file" in sig.parameters

    def test_prompt_defaults_to_empty_string(self):
        sig = inspect.signature(MockAIModel.generate_transcription)
        assert sig.parameters["prompt"].default == ""

    def test_no_var_args_or_kwargs(self):
        # A regression switching to **kwargs would silently accept
        # unknown args — the explicit signature is part of the
        # conformance promise.
        sig = inspect.signature(MockAIModel.generate_transcription)
        kinds = {p.kind for p in sig.parameters.values() if p.name != "self"}
        assert inspect.Parameter.VAR_KEYWORD not in kinds
        assert inspect.Parameter.VAR_POSITIONAL not in kinds


class TestMockDeterminism:
    """Same inputs → same output. Snapshot tests rely on this."""

    def test_identical_calls_return_equal(self):
        mock = MockAIModel.__new__(MockAIModel)
        a = mock.generate_transcription(b"audio-1")
        b = mock.generate_transcription(b"audio-2")  # different input
        # Mock ignores the audio bytes — both calls return the same
        # text. That's the offline-stub contract.
        assert a["text"] == b["text"]
        assert a["segments"] == b["segments"]

    def test_returns_fresh_dict_each_call(self):
        # Each call must return a fresh dict — otherwise a consumer
        # mutating `result["segments"]` would leak to the next call.
        mock = MockAIModel.__new__(MockAIModel)
        a = mock.generate_transcription(b"x")
        b = mock.generate_transcription(b"x")
        assert a is not b
        # Same for the segments list — fresh list, not a shared module
        # constant.
        assert a["segments"] is not b["segments"]


# ---------------------------------------------------------------------------
# Gemini-adapter coverage
# ---------------------------------------------------------------------------


def _make_gemini_transcription_stub(text_value):
    """Hand-built stub aliasing the real `generate_transcription` —
    same composition pattern dev uses for `_make_gemini_stub`, but
    set up specifically for transcription's upload + generate
    sequence.
    """
    class _Stub:
        _stt_model = "gemini-test"
        generate_transcription = GeminiAIModel.generate_transcription

    stub = _Stub()
    stub.client = MagicMock()

    response = MagicMock()
    response.text = text_value
    stub.client.models.generate_content.return_value = response

    return stub


class TestGeminiUploadCallOrder:
    """The wrapping shouldn't have disturbed the upload-then-transcribe
    flow. If a refactor accidentally bypassed the upload, gemini
    would try to transcribe a raw audio_file object the SDK doesn't
    understand.
    """

    def test_upload_happens_exactly_once_per_call(self):
        stub = _make_gemini_transcription_stub("hello")
        stub.generate_transcription(b"audio-bytes")
        assert stub.client.files.upload.call_count == 1

    def test_generate_content_receives_uploaded_file_in_contents(self):
        # `contents=[prompt, myfile]` — verify the uploaded handle
        # (not the raw bytes) ends up in the second contents slot.
        stub = _make_gemini_transcription_stub("hello")
        uploaded_handle = stub.client.files.upload.return_value

        stub.generate_transcription(b"audio-bytes")

        call_kwargs = stub.client.models.generate_content.call_args.kwargs
        contents = call_kwargs["contents"]
        assert len(contents) == 2
        assert contents[1] is uploaded_handle

    def test_prompt_is_first_in_contents(self):
        stub = _make_gemini_transcription_stub("hello")
        stub.generate_transcription(b"audio-bytes", prompt="be terse")
        contents = stub.client.models.generate_content.call_args.kwargs["contents"]
        assert contents[0] == "be terse"

    def test_default_prompt_when_omitted(self):
        # gemini's default is "Transcribe this audio clip" — verify
        # it's still passed when caller omits the kwarg.
        stub = _make_gemini_transcription_stub("hello")
        stub.generate_transcription(b"audio-bytes")
        contents = stub.client.models.generate_content.call_args.kwargs["contents"]
        assert "Transcribe" in contents[0]


class TestGeminiDisplayNameKwarg:
    """Gemini accepts an extra `display_name=` kwarg beyond the
    Protocol's two. Slice 4 shouldn't have dropped it — callers
    customizing the upload metadata depend on it.
    """

    def test_display_name_default_used_when_omitted(self):
        stub = _make_gemini_transcription_stub("ok")
        stub.generate_transcription(b"audio-bytes")
        # Default is "audio.mp3" per the gemini.py signature.
        upload_kwargs = stub.client.files.upload.call_args.kwargs
        assert upload_kwargs["config"]["display_name"] == "audio.mp3"

    def test_display_name_kwarg_forwards_to_upload(self):
        stub = _make_gemini_transcription_stub("ok")
        stub.generate_transcription(
            b"audio-bytes", display_name="podcast-ep-42.mp3"
        )
        upload_kwargs = stub.client.files.upload.call_args.kwargs
        assert upload_kwargs["config"]["display_name"] == "podcast-ep-42.mp3"


class TestGeminiFalsyTextEdgeCases:
    """The `response.text or ""` defensive default handles None +
    empty string the same way. Verify each falsy case lands on the
    canonical empty-string contract.
    """

    @pytest.mark.parametrize(
        "raw_text, expected_text",
        [
            (None, ""),         # filter-blocked content
            ("", ""),           # empty transcription
            ("hello", "hello"), # normal case
            ("  spaces  ", "  spaces  "),  # whitespace preserved (no .strip())
        ],
    )
    def test_text_normalization(self, raw_text, expected_text):
        stub = _make_gemini_transcription_stub(raw_text)
        result = stub.generate_transcription(b"audio-bytes")
        assert result["text"] == expected_text

    def test_text_value_is_always_a_string(self):
        # Even on None, the `.text` value MUST be a str — consumers
        # call `.split()` and `len()` without a None guard.
        for raw in (None, "", "ok"):
            stub = _make_gemini_transcription_stub(raw)
            result = stub.generate_transcription(b"audio-bytes")
            assert isinstance(result["text"], str)


# ---------------------------------------------------------------------------
# Cross-adapter homogeneity
# ---------------------------------------------------------------------------


class TestCrossAdapterHomogeneity:
    """Both mock and gemini return the SAME key set. A future slice
    adding ``language`` to gemini only would split the contract.

    Dev's tests check each adapter individually. Pinning equality at
    the same time forces homogeneity to be a deliberate property.
    """

    def _mock_result(self):
        mock = MockAIModel.__new__(MockAIModel)
        return mock.generate_transcription(b"audio-bytes")

    def _gemini_result(self):
        stub = _make_gemini_transcription_stub("hi")
        return stub.generate_transcription(b"audio-bytes")

    def test_same_key_set(self):
        mock_keys = set(self._mock_result().keys())
        gemini_keys = set(self._gemini_result().keys())
        assert mock_keys == gemini_keys == {"text", "segments"}

    def test_same_value_types(self):
        mock_r = self._mock_result()
        gemini_r = self._gemini_result()
        assert type(mock_r["text"]) is type(gemini_r["text"])
        assert type(mock_r["segments"]) is type(gemini_r["segments"])

    def test_segments_is_list_not_tuple_or_dict(self):
        # Critical: `result["segments"].append(...)` must work for
        # consumers post-processing the segments. A tuple/dict would
        # break the contract silently in tests that don't try to
        # mutate.
        for result in (self._mock_result(), self._gemini_result()):
            assert isinstance(result["segments"], list)
            assert not isinstance(result["segments"], tuple)

    def test_text_is_str_not_bytes(self):
        # Pre-slice-4 mock returned a str; an over-eager rewrite that
        # encoded the bytes-in/str-out flow as a bytes return would
        # break consumers calling `.split()` / `.lower()`.
        for result in (self._mock_result(), self._gemini_result()):
            assert isinstance(result["text"], str)
            assert not isinstance(result["text"], bytes)
