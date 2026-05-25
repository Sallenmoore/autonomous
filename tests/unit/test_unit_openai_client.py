"""Tests for autonomous.ai.models.openai_compat.OpenAIClient.

The client targets OpenAI-compatible endpoints (Open WebUI / vLLM / etc.).
Goals:

- Generate text/JSON/embeddings/transcription against the right paths.
- Raise HPCUnreachableError on transport problems (connection refused,
  timeout, 401, 5xx) so callers can map to a UI toast.
- response_format=json_object is sent for generate_json; if the server
  ignores it, the cleaner falls through correctly.
- generate_image / upscale_image / generate_audio raise NotImplementedError —
  those routes belong to GeminiAIModel or LocalAIModel.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests


@pytest.fixture(autouse=True)
def _silence_autotasks():
    with patch("autonomous.ai.models.openai_compat.AutoTasks") as mock_tasks:
        mock_tasks.return_value.get_current_task.return_value = None
        yield mock_tasks


@pytest.fixture
def client():
    """Build an OpenAIClient bypassing AutoModel/MongoEngine setup.

    We construct with __new__ to skip Mongo connection, then prime the bare
    minimum MongoEngine descriptor state (_data, _initialised, _changed_fields)
    so that field reads like ``self.instructions`` work in the methods under
    test.
    """
    from autonomous.ai.models.openai_compat import OpenAIClient

    c = OpenAIClient.__new__(OpenAIClient)
    object.__setattr__(c, "_data", {"instructions": "You are a test agent."})
    object.__setattr__(c, "_dynamic_fields", {})
    object.__setattr__(c, "_changed_fields", [])
    object.__setattr__(c, "_initialised", True)
    object.__setattr__(c, "_created", False)
    for key, val in {
        "_base_url": "http://mock-hpc/api",
        "_api_key": "test-key",
        "_text_model": "gpt-oss:20b",
        "_json_model": "gpt-oss:20b",
        "_summary_model": "gemma3:4b",
        "_embedding_model": "qwen3-embedding",
        "_stt_model": "whisper-1",
        "_timeout": 1,
        "_retry_attempts": 3,
        "_retry_backoff": 0,  # don't actually sleep in tests
    }.items():
        object.__setattr__(c, key, val)
    return c


def _mock_chat_response(content):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"choices": [{"message": {"content": content}}]}
    response.raise_for_status.return_value = None
    return response


class TestGenerateText:
    def test_posts_to_chat_completions(self, client):
        with patch(
            "autonomous.ai.models.openai_compat._SESSION.post",
            return_value=_mock_chat_response("hello world"),
        ) as mock_post:
            result = client.generate_text("hi")

        assert result == "hello world"
        # Confirm path + auth header
        url = mock_post.call_args.args[0]
        assert url == "http://mock-hpc/api/chat/completions"
        headers = mock_post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer test-key"
        # Body shape
        body = mock_post.call_args.kwargs["json"]
        assert body["model"] == "gpt-oss:20b"
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][1]["content"] == "hi"

    def test_appends_context_and_uri(self, client):
        with patch(
            "autonomous.ai.models.openai_compat._SESSION.post",
            return_value=_mock_chat_response("ok"),
        ) as mock_post:
            client.generate_text(
                "main message", context={"k": "v"}, uri="https://example/x.json"
            )
        user_msg = mock_post.call_args.kwargs["json"]["messages"][1]["content"]
        assert "main message" in user_msg
        assert '"k"' in user_msg and '"v"' in user_msg
        assert "https://example/x.json" in user_msg


class TestGenerateJson:
    def test_sends_response_format_json_object(self, client):
        with patch(
            "autonomous.ai.models.openai_compat._SESSION.post",
            return_value=_mock_chat_response('{"name": "Aria"}'),
        ) as mock_post:
            result = client.generate_json("describe a character")

        assert result == {"name": "Aria"}
        body = mock_post.call_args.kwargs["json"]
        assert body["response_format"] == {"type": "json_object"}

    def test_falls_back_to_cleaner_when_server_ignores_response_format(self, client):
        # Some open models echo markdown despite response_format. The cleaner
        # should rescue the JSON.
        wrapped = '```json\n{"name": "Aria"}\n```'
        with patch(
            "autonomous.ai.models.openai_compat._SESSION.post",
            return_value=_mock_chat_response(wrapped),
        ):
            result = client.generate_json("describe a character")
        assert result == {"name": "Aria"}

    def test_raises_parse_error_on_unparseable_response(self, client):
        from autonomous.ai.exceptions import GenerateJSONParseError

        with patch(
            "autonomous.ai.models.openai_compat._SESSION.post",
            return_value=_mock_chat_response("I cannot help with that."),
        ):
            with pytest.raises(GenerateJSONParseError) as ctx:
                client.generate_json("anything")
        assert "I cannot help" in ctx.value.raw


class TestEmbeddings:
    def test_posts_to_embeddings_path(self, client):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
        response.raise_for_status.return_value = None

        with patch(
            "autonomous.ai.models.openai_compat._SESSION.post",
            return_value=response,
        ) as mock_post:
            vec = client.get_embedding("a bit of text")

        assert vec == [0.1, 0.2, 0.3]
        url = mock_post.call_args.args[0]
        assert url == "http://mock-hpc/api/embeddings"
        body = mock_post.call_args.kwargs["json"]
        assert body == {"model": "qwen3-embedding", "input": "a bit of text"}


class TestTranscription:
    def test_returns_text_and_segments_shape(self, client):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "text": "hello world",
            "segments": [{"id": 0, "text": "hello"}, {"id": 1, "text": "world"}],
        }
        response.raise_for_status.return_value = None

        with patch(
            "autonomous.ai.models.openai_compat._SESSION.post",
            return_value=response,
        ) as mock_post:
            result = client.generate_transcription(b"fake audio bytes")

        assert result["text"] == "hello world"
        assert len(result["segments"]) == 2
        url = mock_post.call_args.args[0]
        assert url == "http://mock-hpc/api/audio/transcriptions"
        # Multipart upload, not JSON body
        assert "files" in mock_post.call_args.kwargs
        assert mock_post.call_args.kwargs["data"]["model"] == "whisper-1"

    def test_normalizes_missing_segments(self, client):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"text": "just text"}  # no segments key
        response.raise_for_status.return_value = None

        with patch(
            "autonomous.ai.models.openai_compat._SESSION.post",
            return_value=response,
        ):
            result = client.generate_transcription(b"audio")
        assert result == {"text": "just text", "segments": []}


class TestUnreachableErrors:
    """Transport-layer failures must surface as HPCUnreachableError so callers
    can convert them into a clear toast rather than a generic 500."""

    def test_connection_error_becomes_hpc_unreachable(self, client):
        from autonomous.ai.models.openai_compat import HPCUnreachableError

        with patch(
            "autonomous.ai.models.openai_compat._SESSION.post",
            side_effect=requests.ConnectionError("VPN down"),
        ):
            with pytest.raises(HPCUnreachableError):
                client.generate_text("hi")

    def test_timeout_becomes_hpc_unreachable(self, client):
        from autonomous.ai.models.openai_compat import HPCUnreachableError

        with patch(
            "autonomous.ai.models.openai_compat._SESSION.post",
            side_effect=requests.Timeout("slow"),
        ):
            with pytest.raises(HPCUnreachableError):
                client.generate_text("hi")

    @pytest.mark.parametrize("code", [401, 502, 503, 504])
    def test_transport_failure_codes_become_hpc_unreachable(self, client, code):
        from autonomous.ai.models.openai_compat import HPCUnreachableError

        bad = MagicMock()
        bad.status_code = code
        bad.text = "denied"

        with patch(
            "autonomous.ai.models.openai_compat._SESSION.post", return_value=bad
        ):
            with pytest.raises(HPCUnreachableError):
                client.generate_text("hi")

    def test_retries_then_raises_after_exhaustion(self, client):
        from autonomous.ai.models.openai_compat import HPCUnreachableError

        with patch(
            "autonomous.ai.models.openai_compat._SESSION.post",
            side_effect=requests.ConnectionError("nope"),
        ) as mock_post:
            with pytest.raises(HPCUnreachableError):
                client.generate_text("hi")
        assert mock_post.call_count == 3  # _retry_attempts


class TestNotImplemented:
    def test_generate_image_not_implemented(self, client):
        with pytest.raises(NotImplementedError):
            client.generate_image("a sword")

    def test_upscale_image_not_implemented(self, client):
        with pytest.raises(NotImplementedError):
            client.upscale_image("a sword")

    def test_generate_audio_not_implemented(self, client):
        with pytest.raises(NotImplementedError):
            client.generate_audio("hello")


class TestUnconfigured:
    def test_missing_base_url_raises_hpc_unreachable(self, client):
        from autonomous.ai.models.openai_compat import HPCUnreachableError

        object.__setattr__(client, "_base_url", "")
        with pytest.raises(HPCUnreachableError):
            client.generate_text("hi")
