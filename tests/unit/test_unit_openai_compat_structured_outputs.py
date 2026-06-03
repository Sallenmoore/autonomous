"""OpenAIClient strict-mode structured-outputs coverage.

Test classes (across Tasks 5-8):
- TestUnsupportedDetectionHelpers (this task): heuristic + cache reset
- TestStrictModePayload (Task 6): generate_json builds strict response_format
- TestStrictModeFallback (Task 7): conservative 400 → cache + retry loose
- TestStrictModeCacheShortCircuit (Task 8): second call skips strict"""

import pytest

from autonomous.ai.models import openai_compat
from autonomous.ai.models.openai_compat import (
    _UNSUPPORTED_STRICT_MODE,
    _looks_like_unsupported_strict_mode,
    _reset_unsupported_cache,
)


class TestUnsupportedDetectionHelpers:
    """Pure-function helpers — no network, no instance state."""

    def setup_method(self):
        _reset_unsupported_cache()

    @pytest.mark.parametrize(
        "status,body,expected",
        [
            # Conservative: only the explicit markers trigger True.
            (400, "Invalid response_format type 'json_schema'", True),
            (400, "{'error':{'code':'unsupported_parameter'}}", True),
            (400, "Structured output not implemented", True),
            (400, "json_schema not supported", True),
            (422, "json_schema validation error", True),  # 422 also accepted

            # Bare 400 with unrelated error: False (real client bug).
            (400, "Model not found", False),
            (400, "Bad request", False),
            (400, "Authentication required", False),

            # Non-4xx: always False (transport / success).
            (200, "json_schema mentioned but 200 status", False),
            (500, "json_schema unsupported", False),
            (503, "Service unavailable", False),
        ],
    )
    def test_heuristic_matches_only_strict_mode_signals(
        self, status, body, expected
    ):
        assert _looks_like_unsupported_strict_mode(status, body) is expected

    def test_reset_empties_cache(self):
        _UNSUPPORTED_STRICT_MODE.add(("model-x", "http://endpoint-y"))
        assert len(_UNSUPPORTED_STRICT_MODE) == 1
        _reset_unsupported_cache()
        assert len(_UNSUPPORTED_STRICT_MODE) == 0

    def test_cache_uses_tuple_keys(self):
        # Verifies the cache discriminates on (model, endpoint) — not just one.
        _UNSUPPORTED_STRICT_MODE.add(("model-a", "http://host-1"))
        _UNSUPPORTED_STRICT_MODE.add(("model-a", "http://host-2"))
        _UNSUPPORTED_STRICT_MODE.add(("model-b", "http://host-1"))
        assert len(_UNSUPPORTED_STRICT_MODE) == 3
        _reset_unsupported_cache()


class TestStrictModePayload:
    """generate_json with json_schema= set builds the OpenAI strict-mode
    response_format payload. Without json_schema, the existing loose-mode
    payload is preserved (regression guard)."""

    SAMPLE_SCHEMA = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }

    def setup_method(self):
        _reset_unsupported_cache()

    def _client(self, monkeypatch, captured):
        """Build a bare OpenAIClient and stub _chat to capture the
        response_format that generate_json builds."""
        from autonomous.ai.models.openai_compat import OpenAIClient

        client = OpenAIClient.__new__(OpenAIClient)
        # Prime MongoEngine descriptor state so field reads work without Mongo.
        object.__setattr__(client, "_data", {"instructions": "Be a helpful AI."})
        object.__setattr__(client, "_dynamic_fields", {})
        object.__setattr__(client, "_changed_fields", [])
        object.__setattr__(client, "_initialised", True)
        object.__setattr__(client, "_created", False)
        client._json_model = "test-model"
        client._base_url = "https://test-endpoint/api"
        client._api_key = "test-key"

        def fake_chat(model, system, user, response_format=None, temperature=0.7):
            captured["response_format"] = response_format
            captured["model"] = model
            return '{"value": "ok"}'

        monkeypatch.setattr(client, "_chat", fake_chat)
        return client

    def test_json_schema_none_uses_loose_mode(self, monkeypatch):
        """Regression guard: backward compatibility when json_schema not set."""
        captured = {}
        from autonomous.ai.models.openai_compat import OpenAIClient
        client = self._client(monkeypatch, captured)

        result = OpenAIClient.generate_json(client, "prompt")

        assert captured["response_format"] == {"type": "json_object"}
        assert result == {"value": "ok"}

    def test_json_schema_set_uses_strict_mode(self, monkeypatch):
        captured = {}
        from autonomous.ai.models.openai_compat import OpenAIClient
        client = self._client(monkeypatch, captured)

        OpenAIClient.generate_json(
            client, "prompt", json_schema=self.SAMPLE_SCHEMA
        )

        assert captured["response_format"] == {
            "type": "json_schema",
            "json_schema": {
                "name": "response",  # default schema_name
                "schema": self.SAMPLE_SCHEMA,
                "strict": True,
            },
        }

    def test_schema_name_kwarg_threads_through(self, monkeypatch):
        captured = {}
        from autonomous.ai.models.openai_compat import OpenAIClient
        client = self._client(monkeypatch, captured)

        OpenAIClient.generate_json(
            client,
            "prompt",
            json_schema=self.SAMPLE_SCHEMA,
            schema_name="party_reactions",
        )

        assert captured["response_format"]["json_schema"]["name"] == "party_reactions"
        assert captured["response_format"]["json_schema"]["strict"] is True
