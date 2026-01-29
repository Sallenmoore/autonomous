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

    def generate_json(self, message, system_prompt=None, uri="", context={}):
        """
        Returns a rich dummy JSON object.
        It attempts to guess the context based on keys found in the prompt,
        otherwise returns a safe default TTRPG object.
        """
        log(f"⚡ [MOCK] Generating JSON for prompt: {message[:50]}...", _print=True)

        # 1. Default Mock Object
        mock_response = {
            "name": "The Mockingbird Tavern",
            "description": "A glitchy, holographic tavern that only exists in offline mode. The ale tastes like static.",
            "backstory": "Created by a developer at 30,000 feet, this tavern serves as a placeholder for real content. It was built on the ruins of a NullReferenceException.",
            "appearance": "Wireframe walls with textures that haven't loaded yet.",
            "secrets": "If you look closely at the bartender, you can see he is just a looping IF statement.",
            "tags": ["offline", "dev-mode", "test"],
            "type": "Location",
        }

        # 2. Heuristic: If the user provided a context with 'name', use it.
        # This makes the mock feel slightly responsive.
        if context:
            if "name" in context:
                mock_response["name"] = f"Mock {context['name']}"
            if "title" in context:
                mock_response["name"] = f"Mock {context['title']}"

        return mock_response

    def generate_text(self, message, additional_instructions="", uri="", context={}):
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
        return "This is a mock transcription of the audio file."

    def generate_audio(self, prompt, voice=None):
        log(f"⚡ [MOCK] Generating Audio...", _print=True)
        return self._MOCK_AUDIO_BYTES

    def generate_image(
        self, prompt, negative_prompt="", files=None, aspect_ratio="2KPortrait"
    ):
        log(f"⚡ [MOCK] Generating Image ({aspect_ratio})...", _print=True)
        # Returns a valid 1x1 pixel PNG so your UI displays something red instead of crashing
        return self._MOCK_IMAGE_BYTES
