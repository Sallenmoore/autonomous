import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch

import pytest
from autonomous.model.local_model import LocalAIModel


class TestLocalAIModel(unittest.TestCase):
    def setUp(self):
        # Set dummy env vars to ensure we are testing the class defaults/overrides
        os.environ["OLLAMA_API_BASE_URL"] = "http://mock-ollama:11434"
        os.environ["MEDIA_API_BASE_URL"] = "http://mock-media:5000"

        self.model = LocalAIModel()
        # Reset URLs manually in case the class loaded empty env vars at import time
        self.model._ollama_url = "http://mock-ollama:11434"
        self.model._media_url = "http://mock-media:5000"
        self.model._image_url = "http://mock-media:5000"
        self.model._audio_url = "http://mock-media:5000"

    # --- 1. UTILITY TESTS ---

    def test_clean_json_response_parsing(self):
        """Test the robustness of the JSON cleaner against Llama 3 chatter."""
        # Case A: Markdown blocks
        raw_markdown = """Sure, here is the JSON you requested: {
            "name": "Test",
            "value": 10
        }
        Let me know if you need changes."""

        cleaned = self.model._clean_json_response(raw_markdown)
        self.assertEqual(cleaned, '{\n    "name": "Test",\n    "value": 10\n}')

        # Case B: No markdown, just conversational wrapper
        raw_chat = """Sure, here is the JSON you requested: { "key": "value" } Let me know if you need changes."""
        cleaned = self.model._clean_json_response(raw_chat)
        self.assertEqual(cleaned, '{ "key": "value" }')
        # Case C: Malformed/No brackets (Should remain as is, likely failing JSON load later)
        raw_bad = "I couldn't generate that."
        cleaned = self.model._clean_json_response(raw_bad)
        self.assertEqual(cleaned, "I couldn't generate that.")

    @patch("requests.post")
    def test_generate_text_with_context(self, mock_post):
        """Verify context is correctly injected into the system prompt."""
        # Setup Mock
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": "Leonardo da Vinci"}}
        mock_post.return_value = mock_response

        # Inputs
        context = {"Fact": "The sky is green."}
        prompt = "What color is the sky?"

        # Execute
        response = self.model.generate_text(prompt, context=context)

        # Assert
        self.assertEqual(response, "Leonardo da Vinci")

        # Verify Payload Structure
        args, kwargs = mock_post.call_args
        payload = kwargs["json"]

        # Check system prompt contains the context injection
        system_content = payload["messages"][0]["content"]
        self.assertIn("### GROUND TRUTH CONTEXT ###", system_content)
        self.assertIn("The sky is green", system_content)
        self.assertEqual(payload["model"], "llama3")

    @patch("requests.post")
    def test_generate_json_logic(self, mock_post):
        """Test JSON generation, cleaning, and parameter unwrapping."""
        # Setup Mock to return a "messy" valid JSON response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {
                "content": 'Here is the result:\n```json\n{ "parameters": { "setup": "Why?", "punchline": "Because!" } }\n```'
            }
        }
        mock_post.return_value = mock_response

        # Execute
        result = self.model.generate_json("Tell a joke", context={})

        # Assert
        # Should unwrap 'parameters' and clean markdown
        self.assertEqual(result.get("setup"), "Why?")
        self.assertEqual(result.get("punchline"), "Because!")

        # Verify Strict Mode prompt
        args, kwargs = mock_post.call_args
        system_prompt = kwargs["json"]["messages"][0]["content"]
        self.assertIn("strict JSON generator", system_prompt)

    # --- 3. IMAGE AGENT TESTS ---

    def test_dimension_calculation(self):
        """Test the resolution logic for SDXL buckets."""
        # Standard
        base, target = self.model._get_dimensions("1:1")
        self.assertEqual(base, (832, 832))  # Local_model defaults
        self.assertEqual(target, (1024, 1024))

        # 4K Upscale trigger
        base, target = self.model._get_dimensions("4K")
        self.assertEqual(base, (1216, 832))  # Base generation size
        self.assertEqual(target, (3840, 2160))  # Target upscale size

    @patch("requests.post")
    def test_generate_image_upscale_flow(self, mock_post):
        """
        Verify that requesting a '4K' image triggers TWO API calls:
        1. Generate Base Image
        2. Upscale Base Image
        """
        # Setup Mocks
        response_gen = MagicMock()
        response_gen.content = b"base_image_bytes"

        response_upscale = MagicMock()
        response_upscale.content = b"upscaled_image_bytes"

        # Side effect: First call returns gen, second returns upscale
        mock_post.side_effect = [response_gen, response_upscale]

        # Execute
        result = self.model.generate_image("A cat", aspect_ratio="4K")

        # Assert
        self.assertEqual(result, b"upscaled_image_bytes")
        self.assertEqual(mock_post.call_count, 2)

        # Verify first call (Generation)
        call1_kwargs = mock_post.call_args_list[0].kwargs
        self.assertEqual(call1_kwargs["data"]["width"], 1216)  # Base width

        # Verify second call (Upscale)
        call2_kwargs = mock_post.call_args_list[1].kwargs
        self.assertEqual(call2_kwargs["data"]["width"], 3840)  # Target width
        self.assertTrue("file" in call2_kwargs["files"])  # Did we send the file back?

    # --- 4. AUDIO & TRANSCRIPTION TESTS ---

    @patch("requests.post")
    def test_generate_audio_tts(self, mock_post):
        """Test TTS generation."""
        # Setup Mock (Return valid WAV header to satisfy Pydub if needed, or just bytes)
        # Pydub requires actual audio data or it might fail `from_file`.
        # We'll mock AudioSegment to avoid needing real wav bytes.
        with patch("autonomous.model.local_model.AudioSegment") as mock_audio:
            mock_segment = MagicMock()
            mock_buffer = MagicMock()
            mock_buffer.getvalue.return_value = b"opus_bytes"

            mock_audio.from_file.return_value = mock_segment

            # Setup Requests
            response = MagicMock()
            response.content = b"wav_bytes"
            mock_post.return_value = response

            # Execute
            result = self.model.generate_audio("Hello", voice="Zephyr")

            # Assert
            self.assertEqual(result, b"opus_bytes")
            mock_post.assert_called_once()
            self.assertEqual(mock_post.call_args[1]["json"]["voice"], "Zephyr")

    @patch("requests.post")
    def test_transcribe_long_audio_1hour_plus(self, mock_post):
        """
        Test transcribing a large audio file.
        Verifies that the method handles large bytes objects, sends them to the STT endpoint,
        and then passes the result to the cleanup LLM.
        """
        # 1. Simulate a large file (approx 50MB dummy data for 1 hour opus)
        # We don't need real data, just a large bytes object to ensure no overflow errors in logic
        large_audio_data = b"\0" * (
            1024 * 1024 * 5
        )  # 5MB for test speed, logic is identical

        # 2. Setup Responses

        # Response A: The Whisper API returns a massive raw transcript
        raw_transcript_text = "start " + ("bla " * 1000) + " end"  # Long string
        response_whisper = MagicMock()
        response_whisper.json.return_value = {"text": raw_transcript_text}

        # Response B: The LLM Cleanup Step returns formatted markdown
        response_llm = MagicMock()
        response_llm.json.return_value = {"message": {"content": "**Cleaned Script**"}}

        # The code calls requests.post for audio, then requests.post for text (generate_text)
        mock_post.side_effect = [response_whisper, response_llm]

        # 3. Execute
        result = self.model.generate_transcription(
            large_audio_data,
            prompt="Transcribe this long meeting.",
            whisper_context="Previous meeting ended.",
        )

        # 4. Assertions

        # Check Final Result (Markdown processed)
        self.assertIn("<p><strong>Cleaned Script</strong></p>", result)

        # Check Step 1: Whisper Call
        whisper_call = mock_post.call_args_list[0]
        # Verify the endpoint was correct
        self.assertIn("/transcribe", whisper_call[0][0])
        # Verify context was passed to Whisper (Critical for long audio stitching)
        self.assertEqual(whisper_call[1]["data"]["prompt"], "Previous meeting ended.")

        # Check Step 2: Cleanup Call
        llm_call = mock_post.call_args_list[1]
        llm_payload = llm_call[1]["json"]

        # Verify the LLM received the massive transcript
        # We check that the raw transcript text exists in the user content or system prompt
        full_prompt_sent = (
            llm_payload["messages"][0]["content"]
            + llm_payload["messages"][1]["content"]
        )
        self.assertIn("RAW TRANSCRIPT", full_prompt_sent)
        self.assertIn("start bla bla", full_prompt_sent)

    @patch("requests.post")
    def test_summarize_text_chunking(self, mock_post):
        """Test that summarize_text breaks long text into chunks."""
        # Setup Mock
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"message": {"content": "Summary chunk."}}
        mock_post.return_value = mock_resp

        # Create text longer than max_chars (12000 in code)
        long_text = "a" * 13000

        # Execute
        summary = self.model.summarize_text(long_text)

        # Assert
        # Should result in 2 calls (12000 chars + 1000 chars)
        self.assertEqual(mock_post.call_count, 2)
        self.assertEqual(summary.strip(), "Summary chunk.\nSummary chunk.")
