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

    def test_invalid_string_raises_parse_error(self, monkeypatch):
        """Post test-agent fix: bare ValueError replaced by typed
        GenerateJSONParseError so callers can catch the typed
        hierarchy per MIGRATIONS' contract."""
        from autonomous.ai.exceptions import GenerateJSONParseError

        client = _StubProviderClient("not valid json")
        agent = _patched_agent(monkeypatch, "openai", client)

        with pytest.raises(GenerateJSONParseError, match="Invalid JSON response"):
            JSONAgent.generate(agent, "prompt")

    def test_non_dict_non_string_raises_parse_error(self, monkeypatch):
        """Wrong-type response also surfaces as the typed exception."""
        from autonomous.ai.exceptions import GenerateJSONParseError

        client = _StubProviderClient(42)   # provider returns int
        agent = _patched_agent(monkeypatch, "openai", client)

        with pytest.raises(GenerateJSONParseError, match="Invalid JSON response"):
            JSONAgent.generate(agent, "prompt")


class _GeminiStubClient:
    """Captures gemini's distinct call signature: generate_json(message, function, ...)"""

    def __init__(self, return_value):
        self.return_value = return_value
        self.calls = []

    def generate_json(self, message, function=None, **kwargs):
        self.calls.append({"message": message, "function": function, **kwargs})
        return self.return_value


class TestDispatchGeminiTranslation:
    def test_json_schema_synthesizes_function_dict(self, monkeypatch):
        client = _GeminiStubClient({"value": "ok"})
        agent = _patched_agent(monkeypatch, "gemini", client)

        JSONAgent.generate(
            agent, "prompt",
            json_schema=SAMPLE_SCHEMA,
            schema_name="lore_blueprint",
        )

        assert len(client.calls) == 1
        call = client.calls[0]
        # Function dict synthesized with the schema as parameters.
        assert call["function"] == {
            "name": "lore_blueprint",
            "description": "Structured response shape.",
            "parameters": SAMPLE_SCHEMA,
        }
        # Should NOT have json_schema= or schema_name= leaked through
        # to gemini (it doesn't accept them).
        assert "json_schema" not in call
        assert "schema_name" not in call

    def test_default_schema_name_used_in_function_dict(self, monkeypatch):
        client = _GeminiStubClient({"value": "ok"})
        agent = _patched_agent(monkeypatch, "gemini", client)

        JSONAgent.generate(agent, "prompt", json_schema=SAMPLE_SCHEMA)

        assert client.calls[0]["function"]["name"] == "response"

    def test_no_schema_passes_no_function(self, monkeypatch):
        """When json_schema is None, gemini call MUST NOT receive a
        synthesized function dict — leaving caller free to use gemini's
        existing function= parameter directly (which JSONAgent doesn't
        forward today; this is preserved no-function behavior)."""
        client = _GeminiStubClient({"value": "ok"})
        agent = _patched_agent(monkeypatch, "gemini", client)

        JSONAgent.generate(agent, "prompt")

        # Gemini got called WITHOUT a function= kwarg.
        # (Hidden caveat: existing JSONAgent has a latent
        # signature-mismatch bug routing to gemini without function. This
        # test pins the new behavior: when json_schema is None, we do
        # NOT manufacture a function dict.)
        assert client.calls[0]["function"] is None

    def test_additional_instructions_passes_system_prompt(self, monkeypatch):
        """Gemini's signature: generate_json(message, function, additional_instructions, ...)
        Our system_prompt kwarg maps to additional_instructions on gemini."""
        client = _GeminiStubClient({"value": "ok"})
        agent = _patched_agent(monkeypatch, "gemini", client)

        JSONAgent.generate(
            agent, "prompt",
            system_prompt="you are concise",
            json_schema=SAMPLE_SCHEMA,
        )

        assert client.calls[0].get("additional_instructions") == "you are concise"


from autonomous.ai.exceptions import GenerateJSONParseError


class TestCentralizedValidation:
    """The centralized _schema_validate call runs after every provider's
    response is parsed to a dict. Catches drift even when the provider
    claims strict-mode compliance — defense in depth."""

    def test_conforming_response_passes(self, monkeypatch):
        client = _StubProviderClient({"value": "ok"})
        agent = _patched_agent(monkeypatch, "openai", client)

        result = JSONAgent.generate(
            agent, "prompt", json_schema=SAMPLE_SCHEMA
        )
        assert result == {"value": "ok"}

    def test_missing_required_raises_parse_error(self, monkeypatch):
        # Provider returns dict missing required "value" field.
        client = _StubProviderClient({"other": "field"})
        agent = _patched_agent(monkeypatch, "openai", client)

        with pytest.raises(GenerateJSONParseError):
            JSONAgent.generate(agent, "prompt", json_schema=SAMPLE_SCHEMA)

    def test_extra_property_raises_parse_error(self, monkeypatch):
        # additionalProperties=False on SAMPLE_SCHEMA forbids extras.
        client = _StubProviderClient({"value": "ok", "unexpected": True})
        agent = _patched_agent(monkeypatch, "openai", client)

        with pytest.raises(GenerateJSONParseError):
            JSONAgent.generate(agent, "prompt", json_schema=SAMPLE_SCHEMA)

    def test_validation_skipped_when_no_schema(self, monkeypatch):
        # Non-conforming would-be result — but no schema → no validation.
        client = _StubProviderClient({"anything": "goes"})
        agent = _patched_agent(monkeypatch, "openai", client)

        result = JSONAgent.generate(agent, "prompt")  # no json_schema
        assert result == {"anything": "goes"}

    def test_validation_runs_for_gemini_too(self, monkeypatch):
        """Defense in depth: gemini's strict function-calling can still
        produce wrong-shape output (provider bugs); validate it too."""
        client = _GeminiStubClient({"other": "field"})  # missing "value"
        agent = _patched_agent(monkeypatch, "gemini", client)

        with pytest.raises(GenerateJSONParseError):
            JSONAgent.generate(agent, "prompt", json_schema=SAMPLE_SCHEMA)

    def test_validation_error_raw_populated(self, monkeypatch):
        client = _StubProviderClient({"other": "field"})
        agent = _patched_agent(monkeypatch, "openai", client)

        with pytest.raises(GenerateJSONParseError) as exc_info:
            JSONAgent.generate(agent, "prompt", json_schema=SAMPLE_SCHEMA)
        # raw should contain (at least a prefix of) the failing response
        assert "other" in exc_info.value.raw or "field" in exc_info.value.raw
