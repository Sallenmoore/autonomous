"""Tests for per-call temperature override on TextAgent / JSONAgent / ImageAgent.

The generate() method on each agent now accepts an optional ``temperature``
keyword argument. When provided it is forwarded to the underlying model
client; when omitted, the client's own default is used (non-breaking).

Pins:
- TextAgent.generate() forwards temperature to client.generate_text()
- TextAgent.generate() omits temperature kwarg when not supplied (uses client default)
- JSONAgent.generate() forwards temperature to client.generate_json()
- JSONAgent.generate() omits temperature kwarg when not supplied
- ImageAgent.generate() accepts temperature without error (stored but not threaded,
  since image models do not use a temperature parameter)
- LocalAIModel.generate_json() accepts and uses temperature in the payload
- LocalAIModel.generate_text() already accepted temperature; still works
- GeminiAIModel.generate_text() forwards temperature into GenerateContentConfig
- GeminiAIModel.generate_json() forwards temperature into GenerateContentConfig
- GeminiAIModel omits temperature from config when not supplied
- OpenAIClient.generate_json() forwards temperature to _chat()
- MockAIModel.generate_text/generate_json() accept temperature without error
"""

from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — build agents without triggering AutoModel / MongoEngine setup
# ---------------------------------------------------------------------------

def _make_agent(agent_class, provider="mock"):
    a = agent_class.__new__(agent_class)
    object.__setattr__(a, "_data", {
        "name": "test-agent",
        "provider": provider,
        "instructions": "test instructions",
        "description": "test description",
    })
    object.__setattr__(a, "_dynamic_fields", {})
    object.__setattr__(a, "_changed_fields", [])
    object.__setattr__(a, "_initialised", True)
    object.__setattr__(a, "_created", False)
    return a


# ---------------------------------------------------------------------------
# TextAgent
# ---------------------------------------------------------------------------

class TestTextAgentTemperature:
    @pytest.fixture
    def agent(self):
        from autonomous.ai.textagent import TextAgent
        return _make_agent(TextAgent)

    def test_temperature_forwarded_to_client(self, agent):
        client = MagicMock()
        client.generate_text.return_value = "result"

        with patch.object(agent, "get_client", return_value=client):
            with patch.object(agent, "add_to_job_meta"):
                agent.generate("hello", temperature=0.0)

        _, kwargs = client.generate_text.call_args
        assert kwargs["temperature"] == 0.0

    def test_temperature_not_in_call_when_omitted(self, agent):
        """When temperature is not supplied the kwarg must not be forwarded,
        so the client uses its own default."""
        client = MagicMock()
        client.generate_text.return_value = "result"

        with patch.object(agent, "get_client", return_value=client):
            with patch.object(agent, "add_to_job_meta"):
                agent.generate("hello")

        _, kwargs = client.generate_text.call_args
        assert "temperature" not in kwargs

    def test_temperature_zero_point_nine_forwarded(self, agent):
        client = MagicMock()
        client.generate_text.return_value = "creative"

        with patch.object(agent, "get_client", return_value=client):
            with patch.object(agent, "add_to_job_meta"):
                agent.generate("write a story", temperature=0.9)

        _, kwargs = client.generate_text.call_args
        assert kwargs["temperature"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# JSONAgent
# ---------------------------------------------------------------------------

class TestJSONAgentTemperature:
    @pytest.fixture
    def agent(self):
        from autonomous.ai.jsonagent import JSONAgent
        return _make_agent(JSONAgent)

    def test_temperature_forwarded_to_client(self, agent):
        client = MagicMock()
        client.generate_json.return_value = {"key": "value"}

        with patch.object(agent, "get_client", return_value=client):
            with patch.object(agent, "add_to_job_meta"):
                agent.generate("build json", temperature=0.2)

        _, kwargs = client.generate_json.call_args
        assert kwargs["temperature"] == pytest.approx(0.2)

    def test_temperature_not_in_call_when_omitted(self, agent):
        client = MagicMock()
        client.generate_json.return_value = {"key": "value"}

        with patch.object(agent, "get_client", return_value=client):
            with patch.object(agent, "add_to_job_meta"):
                agent.generate("build json")

        _, kwargs = client.generate_json.call_args
        assert "temperature" not in kwargs

    def test_temperature_zero_for_deterministic_fields(self, agent):
        client = MagicMock()
        client.generate_json.return_value = {"hitpoints": 12}

        with patch.object(agent, "get_client", return_value=client):
            with patch.object(agent, "add_to_job_meta"):
                result = agent.generate("generate hitpoints", temperature=0.0)

        assert result == {"hitpoints": 12}
        _, kwargs = client.generate_json.call_args
        assert kwargs["temperature"] == 0.0


# ---------------------------------------------------------------------------
# ImageAgent
# ---------------------------------------------------------------------------

class TestImageAgentTemperature:
    @pytest.fixture
    def agent(self):
        from autonomous.ai.imageagent import ImageAgent
        return _make_agent(ImageAgent)

    def test_temperature_accepted_without_error(self, agent):
        """ImageAgent.generate() must accept temperature= without raising,
        even though image models do not thread it through."""
        client = MagicMock()
        client.generate_image.return_value = b"\x89PNG"

        with patch.object(agent, "get_client", return_value=client):
            with patch.object(agent, "add_to_job_meta"):
                result = agent.generate("a sword", temperature=0.5)

        assert result == b"\x89PNG"

    def test_temperature_none_still_works(self, agent):
        client = MagicMock()
        client.generate_image.return_value = b"\x89PNG"

        with patch.object(agent, "get_client", return_value=client):
            with patch.object(agent, "add_to_job_meta"):
                result = agent.generate("a castle")

        assert result == b"\x89PNG"


# ---------------------------------------------------------------------------
# LocalAIModel — generate_json temperature in payload
# ---------------------------------------------------------------------------

class TestLocalAIModelJsonTemperature:
    @pytest.fixture(autouse=True)
    def _silence_autotasks(self):
        with patch("autonomous.ai.models.local_model.AutoTasks") as m:
            m.return_value.get_current_task.return_value = None
            yield

    @pytest.fixture
    def model(self):
        from autonomous.ai.models.local_model import LocalAIModel

        m = LocalAIModel.__new__(LocalAIModel)
        object.__setattr__(m, "_data", {"instructions": "You are a test AI.", "name": "test"})
        object.__setattr__(m, "_dynamic_fields", {})
        object.__setattr__(m, "_changed_fields", [])
        object.__setattr__(m, "_initialised", True)
        object.__setattr__(m, "_created", False)
        object.__setattr__(m, "_ollama_url", "http://ollama-test")
        object.__setattr__(m, "_text_model", "test-model")
        object.__setattr__(m, "_context_limit", 4096)
        object.__setattr__(m, "_json_timeout", 10)
        object.__setattr__(m, "_retry_sleep", 0)
        return m

    def _make_ok_response(self, content='{"result": "ok"}'):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"message": {"content": content}}
        r.raise_for_status.return_value = None
        return r

    def test_default_temperature_is_0_7(self, model):
        with patch(
            "autonomous.ai.models.local_model._SESSION.post",
            return_value=self._make_ok_response(),
        ) as mock_post:
            model.generate_json("give me json")

        payload = mock_post.call_args.kwargs["json"]
        assert payload["options"]["temperature"] == pytest.approx(0.7)

    def test_custom_temperature_propagated_to_payload(self, model):
        with patch(
            "autonomous.ai.models.local_model._SESSION.post",
            return_value=self._make_ok_response(),
        ) as mock_post:
            model.generate_json("deterministic", temperature=0.0)

        payload = mock_post.call_args.kwargs["json"]
        assert payload["options"]["temperature"] == pytest.approx(0.0)

    def test_high_temperature_propagated(self, model):
        with patch(
            "autonomous.ai.models.local_model._SESSION.post",
            return_value=self._make_ok_response('{"story": "once upon a time"}'),
        ) as mock_post:
            model.generate_json("creative json", temperature=0.9)

        payload = mock_post.call_args.kwargs["json"]
        assert payload["options"]["temperature"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# GeminiAIModel — temperature threaded into GenerateContentConfig
# ---------------------------------------------------------------------------

class TestGeminiAIModelTemperature:
    @pytest.fixture
    def model(self):
        from autonomous.ai.models.gemini import GeminiAIModel

        m = GeminiAIModel.__new__(GeminiAIModel)
        object.__setattr__(m, "_data", {
            "instructions": "test instructions",
            "name": "gemini-test",
        })
        object.__setattr__(m, "_dynamic_fields", {})
        object.__setattr__(m, "_changed_fields", [])
        object.__setattr__(m, "_initialised", True)
        object.__setattr__(m, "_created", False)
        object.__setattr__(m, "_client", MagicMock())
        object.__setattr__(m, "pk", "test-pk")
        object.__setattr__(m, "_text_model", "gemini-2.5-pro")
        object.__setattr__(m, "_json_model", "gemini-2.5-pro")
        return m

    def test_generate_text_temperature_in_config(self, model):
        from google.genai import types as genai_types

        mock_response = MagicMock()
        mock_response.text = "hello"
        model._client.models.generate_content.return_value = mock_response

        model.generate_text("hi", temperature=0.1)

        call_kwargs = model._client.models.generate_content.call_args.kwargs
        config = call_kwargs["config"]
        assert config.temperature == pytest.approx(0.1)

    def test_generate_text_no_temperature_when_omitted(self, model):
        """When temperature is not supplied, the config must not carry it
        (None means 'use Gemini default')."""
        mock_response = MagicMock()
        mock_response.text = "hello"
        model._client.models.generate_content.return_value = mock_response

        model.generate_text("hi")

        call_kwargs = model._client.models.generate_content.call_args.kwargs
        config = call_kwargs["config"]
        # temperature attribute should either be absent or None
        temp = getattr(config, "temperature", None)
        assert temp is None

    def test_generate_text_high_temperature(self, model):
        mock_response = MagicMock()
        mock_response.text = "creative output"
        model._client.models.generate_content.return_value = mock_response

        model.generate_text("write something", temperature=0.9)

        call_kwargs = model._client.models.generate_content.call_args.kwargs
        config = call_kwargs["config"]
        assert config.temperature == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# OpenAIClient — generate_json temperature forwarded to _chat
# ---------------------------------------------------------------------------

class TestOpenAIClientJsonTemperature:
    @pytest.fixture(autouse=True)
    def _silence_autotasks(self):
        with patch("autonomous.ai.models.openai_compat.AutoTasks") as m:
            m.return_value.get_current_task.return_value = None
            yield

    @pytest.fixture
    def client(self):
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
            "_json_model": "gpt-oss:20b",
            "_timeout": 1,
            "_retry_attempts": 1,
            "_retry_backoff": 0,
        }.items():
            object.__setattr__(c, key, val)
        return c

    def _mock_chat_response(self, content):
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"choices": [{"message": {"content": content}}]}
        r.raise_for_status.return_value = None
        return r

    def test_default_temperature_used_in_payload(self, client):
        with patch(
            "autonomous.ai.models.openai_compat._SESSION.post",
            return_value=self._mock_chat_response('{"k": "v"}'),
        ) as mock_post:
            client.generate_json("get json")

        body = mock_post.call_args.kwargs["json"]
        assert body["temperature"] == pytest.approx(0.7)

    def test_custom_temperature_propagated(self, client):
        with patch(
            "autonomous.ai.models.openai_compat._SESSION.post",
            return_value=self._mock_chat_response('{"k": "v"}'),
        ) as mock_post:
            client.generate_json("deterministic field", temperature=0.0)

        body = mock_post.call_args.kwargs["json"]
        assert body["temperature"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# MockAIModel — temperature accepted without error
# ---------------------------------------------------------------------------

class TestMockAIModelTemperature:
    @pytest.fixture
    def model(self):
        from autonomous.ai.models.mock_model import MockAIModel

        m = MockAIModel.__new__(MockAIModel)
        object.__setattr__(m, "_data", {"instructions": "mock", "name": "mock"})
        object.__setattr__(m, "_dynamic_fields", {})
        object.__setattr__(m, "_changed_fields", [])
        object.__setattr__(m, "_initialised", True)
        object.__setattr__(m, "_created", False)
        return m

    def test_generate_text_accepts_temperature(self, model):
        result = model.generate_text("prompt", temperature=0.5)
        assert isinstance(result, str)

    def test_generate_json_accepts_temperature(self, model):
        result = model.generate_json("prompt", temperature=0.0)
        assert isinstance(result, dict)

    def test_generate_text_works_without_temperature(self, model):
        result = model.generate_text("prompt")
        assert isinstance(result, str)

    def test_generate_json_works_without_temperature(self, model):
        result = model.generate_json("prompt")
        assert isinstance(result, dict)
