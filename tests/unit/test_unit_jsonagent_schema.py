"""JSONAgent.generate dispatch + centralized validation tests.

Covers (across Tasks 9-11):
- Task 9: openai/local/mock providers get json_schema= passed through
- Task 10: gemini provider gets json_schema= translated to function= dict
- Task 11: every provider's response runs through _schema_validate"""

import pytest

from autonomous.ai.jsonagent import JSONAgent


SAMPLE_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
    "additionalProperties": False,
}


def _agent():
    """Bare JSONAgent that bypasses AutoModel persistence."""
    agent = JSONAgent.__new__(JSONAgent)
    # Initialize MongoEngine descriptor state — mirrors the pattern used
    # in tests/unit/test_unit_openai_compat_structured_outputs.py
    object.__setattr__(agent, "_data", {})
    object.__setattr__(agent, "_dynamic_fields", {})
    object.__setattr__(agent, "_changed_fields", [])
    object.__setattr__(agent, "_initialised", False)
    object.__setattr__(agent, "_created", True)
    agent._data["provider"] = "openai"   # default for these dispatch tests
    return agent


class _StubProviderClient:
    """Captures the call signature; returns deterministic JSON."""

    def __init__(self, return_value):
        self.return_value = return_value
        self.calls = []

    def generate_json(self, message, **kwargs):
        self.calls.append({"message": message, **kwargs})
        return self.return_value


def _patched_agent(monkeypatch, provider, client):
    agent = _agent()
    agent._data["provider"] = provider
    agent._meta_log = []
    monkeypatch.setattr(agent, "get_client", lambda _p=None: client)
    monkeypatch.setattr(
        agent, "add_to_job_meta",
        lambda k, v: agent._meta_log.append((k, v)),
    )
    monkeypatch.delenv("JSON_AI_AGENT", raising=False)
    return agent


class TestDispatchOpenAI:
    def test_json_schema_passed_to_openai_provider(self, monkeypatch):
        client = _StubProviderClient({"value": "x"})
        agent = _patched_agent(monkeypatch, "openai", client)

        JSONAgent.generate(
            agent, "prompt", json_schema=SAMPLE_SCHEMA, schema_name="my_resp"
        )

        assert len(client.calls) == 1
        assert client.calls[0]["json_schema"] == SAMPLE_SCHEMA
        assert client.calls[0]["schema_name"] == "my_resp"

    def test_default_schema_name_is_response(self, monkeypatch):
        client = _StubProviderClient({"value": "x"})
        agent = _patched_agent(monkeypatch, "openai", client)

        JSONAgent.generate(agent, "prompt", json_schema=SAMPLE_SCHEMA)

        assert client.calls[0]["schema_name"] == "response"

    def test_none_schema_passes_none(self, monkeypatch):
        """Backward compat: when no schema, json_schema=None reaches provider."""
        client = _StubProviderClient({"value": "x"})
        agent = _patched_agent(monkeypatch, "openai", client)

        JSONAgent.generate(agent, "prompt")

        assert client.calls[0]["json_schema"] is None


class TestDispatchLocal:
    def test_json_schema_passed_to_local_provider(self, monkeypatch):
        client = _StubProviderClient({"value": "x"})
        agent = _patched_agent(monkeypatch, "local", client)

        JSONAgent.generate(agent, "prompt", json_schema=SAMPLE_SCHEMA)

        assert client.calls[0]["json_schema"] == SAMPLE_SCHEMA


class TestDispatchMock:
    def test_json_schema_passed_to_mock_provider(self, monkeypatch):
        client = _StubProviderClient({"value": "ok"})
        agent = _patched_agent(monkeypatch, "mock", client)

        result = JSONAgent.generate(
            agent, "prompt", json_schema=SAMPLE_SCHEMA
        )

        assert client.calls[0]["json_schema"] == SAMPLE_SCHEMA
        assert result == {"value": "ok"}


class TestStringResponseParsing:
    """Existing behavior preserved: provider returning a JSON string
    gets parsed before validation/return."""

    def test_string_response_parsed(self, monkeypatch):
        client = _StubProviderClient('{"value": "ok"}')   # provider returns str
        agent = _patched_agent(monkeypatch, "openai", client)

        result = JSONAgent.generate(agent, "prompt")

        assert result == {"value": "ok"}

    def test_invalid_string_raises_value_error(self, monkeypatch):
        client = _StubProviderClient("not valid json")
        agent = _patched_agent(monkeypatch, "openai", client)

        with pytest.raises(ValueError, match="Invalid JSON response"):
            JSONAgent.generate(agent, "prompt")

    def test_non_dict_non_string_raises_value_error(self, monkeypatch):
        client = _StubProviderClient(42)   # provider returns int
        agent = _patched_agent(monkeypatch, "openai", client)

        with pytest.raises(ValueError, match="Invalid JSON response"):
            JSONAgent.generate(agent, "prompt")
