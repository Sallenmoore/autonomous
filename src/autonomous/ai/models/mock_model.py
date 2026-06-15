import base64
import io
import json

from autonomous import log
from autonomous.model.autoattr import ListAttr, StringAttr
from autonomous.model.automodel import AutoModel


class MockAIModel(AutoModel):
    """
    A Offline Mock Model for development.
    Returns valid, structure-compliant dummy data instantly.
    """

    messages = ListAttr(StringAttr(default=[]))
    name = StringAttr(default="mock_agent")
    instructions = StringAttr(default="You are a Mock AI.")
    description = StringAttr(default="Offline Mock Provider for testing.")

    # A 1x1 Red Pixel PNG (Base64 decoded to bytes)
    # This ensures PIL/Frontend code receives valid image data.
    _MOCK_IMAGE_BYTES = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )

    # A 1-second silent WAV file (Base64 decoded to bytes)
    _MOCK_AUDIO_BYTES = base64.b64decode(
        "UklGRigAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAEA"
    )

    def generate_json(self, message, system_prompt=None, uri="", context=None, temperature=None, _mock_response=None, **kwargs):
        """
        Returns a rich dummy JSON object.
        It attempts to guess the context based on keys found in the prompt,
        otherwise returns a safe default TTRPG object.

        ``_mock_response`` is a test-only override (underscore-prefix marks
        it as not-for-production). When set, the mock returns it verbatim
        — useful for schema-aware tests that need a response conforming to
        a specific ``json_schema`` passed through JSONAgent.generate
        (issue #22). Without this hook, schema-validating tests against
        the mock provider would always fail because the default
        heuristic-built dict rarely matches an arbitrary caller schema.

        Two override paths:
          - Per-call: ``mock.generate_json(prompt, _mock_response={...})``
            — useful when calling the mock directly.
          - Per-instance: ``mock._mock_json_response = {...}`` set on the
            instance — survives across multiple calls and is the right
            choice when test code calls ``JSONAgent.generate`` (which
            doesn't thread per-call test overrides through to providers).

        Per-call wins over per-instance when both are set.
        """
        effective_override = _mock_response
        if effective_override is None:
            effective_override = getattr(self, "_mock_json_response", None)
        if effective_override is not None:
            log(
                f"⚡ [MOCK] Returning override response for prompt: "
                f"{message[:50]}...",
                _print=True,
            )
            return effective_override

        context = context or {}
        log(f"⚡ [MOCK] Generating JSON for prompt: {message[:50]}...", _print=True)

        # 1. Default Mock Object
        mock_response = {}

        # 2. Heuristic: If the user provided a context with 'name', use it.
        # This makes the mock feel slightly responsive.
        if context:
            if "name" in context:
                mock_response["name"] = f"Mock {context['name']}"
            if "title" in context:
                mock_response["name"] = f"Mock {context['title']}"

        return mock_response

    def generate_text(self, message, additional_instructions="", uri="", context=None, temperature=None):
        log(f"⚡ [MOCK] Generating Text...", _print=True)
        return (
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
            "This is MOCK TEXT generated because you are currently offline. "
            "The quick brown fox jumps over the lazy dog."
        )

    def summarize_text(self, text, primer=""):
        log(f"⚡ [MOCK] Summarizing {len(text)} chars...", _print=True)
        return "This is a mock summary of the provided text. It is concise and offline."

    def generate_transcription(self, audio_file, prompt=""):
        log(f"⚡ [MOCK] Transcribing Audio...", _print=True)
        # #47 slice 4 — match the real-adapter shape so consumers using
        # the mock provider see the same return type they'll see in
        # production. Pre-slice-4 this returned a bare string, which
        # silently masked any consumer-side dict-access bugs.
        return {
            "text": "This is a mock transcription of the audio file.",
            "segments": [],
        }

    def generate_audio(self, prompt, voice=None):
        log(f"⚡ [MOCK] Generating Audio...", _print=True)
        return self._MOCK_AUDIO_BYTES

    def generate_image(
        self,
        prompt,
        negative_prompt="",
        files=None,
        aspect_ratio="2KPortrait",
        style=None,
        **kwargs,  # accept fallback_provider, route, and future kwargs
    ):
        log(f"⚡ [MOCK] Generating Image ({aspect_ratio})...", _print=True)
        return self._MOCK_IMAGE_BYTES

    def upscale_image(
        self,
        prompt,
        image_content=None,
        aspect_ratio="2KPortrait",
        style=None,
        **kwargs,
    ):
        log(f"⚡ [MOCK] Upscaling Image ({aspect_ratio})...", _print=True)
        return self._MOCK_IMAGE_BYTES

    def get_embedding(self, text):
        """
        384-dim unit vector. Matches the live Redis vector index dimension
        so RAG plumbing can run end-to-end against the mock without dim-mismatch
        errors. The first dim is 1.0 (unit cosine norm); rest are zero so every
        mock embedding is identical and KNN queries are deterministic.
        """
        return [1.0] + [0.0] * 383

    def list_voices(self, filters=None):
        return ["mock_voice_a", "mock_voice_b"]
