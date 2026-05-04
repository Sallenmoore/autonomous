"""
Unit tests for the local AI model.

All outbound network calls to Ollama / the media service are mocked via
``requests.post``. The ``AutoTasks`` side-effect (which connects to Redis) is
patched so the tests stay pure.
"""

import os
from unittest.mock import MagicMock, patch

import pytest


os.environ.setdefault("OLLAMA_API_BASE_URL", "http://mock-ollama:11434")
os.environ.setdefault("MEDIA_API_BASE_URL", "http://mock-media:5000")
os.environ.setdefault("MEDIA_AUDIO_API_BASE_URL", "http://mock-media:5000")
os.environ.setdefault("MEDIA_IMAGE_API_BASE_URL", "http://mock-media:5000")


@pytest.fixture(autouse=True)
def _silence_autotasks():
    """Prevent Redis connection in LocalAIModel by stubbing AutoTasks."""
    with patch("autonomous.ai.models.local_model.AutoTasks") as mock_tasks:
        mock_tasks.return_value.get_current_task.return_value = None
        yield mock_tasks


@pytest.fixture
def model():
    from autonomous.ai.models.local_model import LocalAIModel

    m = LocalAIModel()
    m._ollama_url = "http://mock-ollama:11434"
    m._media_url = "http://mock-media:5000"
    m._image_url = "http://mock-media:5000"
    m._audio_url = "http://mock-media:5000"
    m._text_model = "gemma4:26b"
    return m


class TestCleanJsonResponse:
    def test_strips_markdown_block(self, model):
        raw = 'Sure: ```json\n{"name": "Test", "value": 10}\n``` done'
        assert (
            model._clean_json_response(raw) == '{"name": "Test", "value": 10}'
        )

    def test_strips_conversational_wrapper(self, model):
        raw = 'Sure, here is the JSON: { "key": "value" } Let me know.'
        assert model._clean_json_response(raw) == '{ "key": "value" }'

    def test_leaves_plain_text_untouched(self, model):
        raw = "I couldn't generate that."
        assert model._clean_json_response(raw) == raw


class TestGenerateText:
    def test_injects_context_into_system_prompt(self, model):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"message": {"content": "blue"}}
        with patch(
            "autonomous.ai.models.local_model.requests.post",
            return_value=mock_resp,
        ) as mock_post:
            response = model.generate_text(
                "What color is the sky?", context={"Fact": "The sky is green."}
            )
        assert response == "blue"
        payload = mock_post.call_args.kwargs["json"]
        assert payload["model"] == "gemma4:26b"
        system_content = payload["messages"][0]["content"]
        assert "### GROUND TRUTH CONTEXT ###" in system_content
        assert "The sky is green" in system_content


class TestGenerateJson:
    def test_cleans_markdown_and_unwraps_parameters(self, model):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "message": {
                "content": (
                    'Here is the result:\n```json\n'
                    '{ "parameters": { "setup": "Why?", "punchline": "Because!" } }\n'
                    '```'
                )
            }
        }
        mock_resp.raise_for_status = MagicMock()
        with patch(
            "autonomous.ai.models.local_model.requests.post",
            return_value=mock_resp,
        ) as mock_post:
            result = model.generate_json("Tell a joke", context={})
        assert result["setup"] == "Why?"
        assert result["punchline"] == "Because!"
        system_prompt = mock_post.call_args.kwargs["json"]["messages"][0]["content"]
        assert "single valid JSON object" in system_prompt


class TestGetDimensions:
    def test_default_square_is_sd15(self, model):
        base, target = model._get_dimensions("1:1")
        assert base == (512, 512)
        assert target == (1024, 1024)

    def test_sdxl_style_square(self, model):
        base, target = model._get_dimensions("1:1", style="atlas")
        assert base == (1024, 1024)
        assert target == (1024, 1024)

    def test_4k_uses_landscape_base_and_4k_target(self, model):
        base, target = model._get_dimensions("4K")
        assert base == (680, 512)
        assert target == (3840, 2880)


class TestGenerateImage:
    def test_generates_base_image(self, model):
        resp = MagicMock()
        resp.content = b"base_image_bytes"
        resp.raise_for_status = MagicMock()
        with patch(
            "autonomous.ai.models.local_model.requests.post",
            return_value=resp,
        ) as mock_post:
            result = model.generate_image("A cat", aspect_ratio="4K")
        assert result == b"base_image_bytes"
        data = mock_post.call_args.kwargs["data"]
        assert data["width"] == 680
        assert data["height"] == 512
        assert data["prompt"] == "A cat"

    def test_upscale_image_posts_target_size(self, model):
        resp = MagicMock()
        resp.content = b"upscaled_image_bytes"
        resp.raise_for_status = MagicMock()
        with patch(
            "autonomous.ai.models.local_model.requests.post",
            return_value=resp,
        ) as mock_post:
            result = model.upscale_image("A cat", b"base_image_bytes", aspect_ratio="4K")
        assert result == b"upscaled_image_bytes"
        data = mock_post.call_args.kwargs["data"]
        assert data["width"] == 3840
        assert data["height"] == 2880
        assert "file" in mock_post.call_args.kwargs["files"]


class TestGenerateAudio:
    def test_tts_encodes_to_opus(self, model):
        with patch("autonomous.ai.models.local_model.AudioSegment") as mock_audio:
            mock_segment = MagicMock()

            def fake_export(buf, format):
                buf.write(b"opus_bytes")

            mock_segment.export.side_effect = fake_export
            mock_audio.from_file.return_value = mock_segment

            resp = MagicMock()
            resp.content = b"wav_bytes"
            resp.raise_for_status = MagicMock()

            with patch(
                "autonomous.ai.models.local_model.requests.post",
                return_value=resp,
            ) as mock_post:
                result = model.generate_audio(
                    "Hello",
                    voice_description="A clear, resonant voice.",
                    voice_id="speaker-zephyr",
                )

            assert result == b"opus_bytes"
            mock_post.assert_called_once()
            payload = mock_post.call_args.kwargs["json"]
            assert payload["voice_id"] == "speaker-zephyr"
            assert payload["voice_description"] == "A clear, resonant voice."
            assert "voice" not in payload


class TestGenerateTranscription:
    def test_returns_structured_json(self, model):
        resp = MagicMock()
        resp.json.return_value = {
            "text": "hello world",
            "segments": [{"start": 0, "end": 1, "text": "hello world"}],
        }
        resp.raise_for_status = MagicMock()
        with patch(
            "autonomous.ai.models.local_model.requests.post",
            return_value=resp,
        ) as mock_post:
            result = model.generate_transcription(
                b"\0" * 1024, prompt="Transcribe this."
            )
        assert result["text"] == "hello world"
        assert result["segments"][0]["text"] == "hello world"
        call = mock_post.call_args
        assert "/transcribe" in call.args[0]
        assert call.kwargs["data"]["prompt"] == "Transcribe this."


class TestSummarizeText:
    def test_chunks_long_text(self, model):
        model._context_limit = 100  # keeps chunks small for the test
        resp = MagicMock()
        resp.json.return_value = {"message": {"content": "Summary chunk."}}
        with patch(
            "autonomous.ai.models.local_model.requests.post",
            return_value=resp,
        ) as mock_post:
            # max_chars = context_limit * 4 = 400
            summary = model.summarize_text("a" * 900)
        # 900 chars / 400 chars-per-chunk = 3 chunks
        assert mock_post.call_count == 3
        assert summary.strip() == "Summary chunk.\nSummary chunk.\nSummary chunk."
