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


import requests


class _FakeHTTPError(requests.HTTPError):
    """HTTPError with a controllable response attached, mimicking what
    requests.Response.raise_for_status() produces."""

    def __init__(self, status, body):
        class _Resp:
            status_code = status
            text = body
        super().__init__(f"HTTP {status}")
        self.response = _Resp()


class TestStrictModeFallback:
    SAMPLE_SCHEMA = {
        "type": "object",
        "properties": {"v": {"type": "string"}},
        "required": ["v"],
    }

    def setup_method(self):
        _reset_unsupported_cache()

    def _client(self, monkeypatch, chat_side_effects):
        """Build a client whose _chat raises or returns per the side-effect list."""
        from autonomous.ai.models.openai_compat import OpenAIClient

        client = OpenAIClient.__new__(OpenAIClient)
        # Match the descriptor-state init pattern that TestStrictModePayload uses.
        # If TestStrictModePayload's _client uses object.__setattr__ for _data,
        # _initialised, etc., do the same here. Inspect TestStrictModePayload
        # (above in this file) and mirror its setup.
        try:
            object.__setattr__(client, "_data", {})
            object.__setattr__(client, "_dynamic_fields", {})
            object.__setattr__(client, "_changed_fields", [])
            object.__setattr__(client, "_initialised", False)
            object.__setattr__(client, "_created", True)
        except AttributeError:
            pass
        client._json_model = "fallback-model"
        client._base_url = "https://fallback-endpoint/api"
        client._api_key = "k"
        client.instructions = "Be a helpful AI."

        calls = {"count": 0, "response_formats": []}
        effects = list(chat_side_effects)

        def fake_chat(model, system, user, response_format=None, temperature=0.7):
            calls["count"] += 1
            calls["response_formats"].append(response_format)
            effect = effects.pop(0) if effects else None
            if isinstance(effect, Exception):
                raise effect
            return effect

        monkeypatch.setattr(client, "_chat", fake_chat)
        return client, calls

    def test_400_with_marker_falls_back_to_loose(self, monkeypatch):
        from autonomous.ai.models.openai_compat import OpenAIClient
        client, calls = self._client(
            monkeypatch,
            chat_side_effects=[
                _FakeHTTPError(400, "Invalid response_format type 'json_schema'"),
                '{"v": "ok"}',
            ],
        )

        result = OpenAIClient.generate_json(
            client, "prompt", json_schema=self.SAMPLE_SCHEMA
        )

        assert result == {"v": "ok"}
        assert calls["count"] == 2
        # First attempt was strict
        assert calls["response_formats"][0]["type"] == "json_schema"
        # Retry was loose
        assert calls["response_formats"][1] == {"type": "json_object"}
        # Endpoint cached
        assert (
            "fallback-model",
            "https://fallback-endpoint/api",
        ) in _UNSUPPORTED_STRICT_MODE

    def test_400_with_unsupported_parameter_marker_falls_back(self, monkeypatch):
        from autonomous.ai.models.openai_compat import OpenAIClient
        client, calls = self._client(
            monkeypatch,
            chat_side_effects=[
                _FakeHTTPError(
                    400,
                    '{"error":{"code":"unsupported_parameter","message":"x"}}',
                ),
                '{"v": "ok"}',
            ],
        )

        result = OpenAIClient.generate_json(
            client, "prompt", json_schema=self.SAMPLE_SCHEMA
        )

        assert result == {"v": "ok"}
        assert calls["count"] == 2

    def test_422_with_marker_falls_back(self, monkeypatch):
        from autonomous.ai.models.openai_compat import OpenAIClient
        client, calls = self._client(
            monkeypatch,
            chat_side_effects=[
                _FakeHTTPError(422, "json_schema validation error"),
                '{"v": "ok"}',
            ],
        )

        result = OpenAIClient.generate_json(
            client, "prompt", json_schema=self.SAMPLE_SCHEMA
        )
        assert result == {"v": "ok"}
        assert calls["count"] == 2

    def test_400_without_marker_propagates(self, monkeypatch):
        from autonomous.ai.models.openai_compat import OpenAIClient
        client, calls = self._client(
            monkeypatch,
            chat_side_effects=[
                _FakeHTTPError(400, "Model 'fallback-model' not found"),
            ],
        )

        with pytest.raises(requests.HTTPError, match="HTTP 400"):
            OpenAIClient.generate_json(
                client, "prompt", json_schema=self.SAMPLE_SCHEMA
            )

        # Only the strict attempt was made; no fallback.
        assert calls["count"] == 1
        # NOT cached — this is a real client bug, not unsupported strict mode.
        assert (
            "fallback-model",
            "https://fallback-endpoint/api",
        ) not in _UNSUPPORTED_STRICT_MODE

    def test_no_fallback_when_json_schema_none(self, monkeypatch):
        """If we didn't ask for strict mode in the first place, an HTTPError
        from _chat is a real error, not an unsupported-mode signal."""
        from autonomous.ai.models.openai_compat import OpenAIClient
        client, calls = self._client(
            monkeypatch,
            chat_side_effects=[
                _FakeHTTPError(400, "json_schema mentioned somehow"),
            ],
        )

        with pytest.raises(requests.HTTPError):
            OpenAIClient.generate_json(client, "prompt")  # no json_schema

        assert calls["count"] == 1


class TestStrictModeCacheShortCircuit:
    SAMPLE_SCHEMA = {
        "type": "object",
        "properties": {"v": {"type": "string"}},
        "required": ["v"],
    }

    def setup_method(self):
        _reset_unsupported_cache()

    def _client(self, monkeypatch, captured):
        from autonomous.ai.models.openai_compat import OpenAIClient

        client = OpenAIClient.__new__(OpenAIClient)
        # Mirror the descriptor-state initialization used by other test classes
        # in this file (see TestStrictModePayload._client and
        # TestStrictModeFallback._client — same pattern).
        try:
            object.__setattr__(client, "_data", {})
            object.__setattr__(client, "_dynamic_fields", {})
            object.__setattr__(client, "_changed_fields", [])
            object.__setattr__(client, "_initialised", False)
            object.__setattr__(client, "_created", True)
        except AttributeError:
            pass
        client._json_model = "cache-model"
        client._base_url = "https://cache-endpoint/api"
        client._api_key = "k"
        client.instructions = "Be a helpful AI."

        def fake_chat(model, system, user, response_format=None, temperature=0.7):
            captured["response_formats"].append(response_format)
            return '{"v": "cached"}'

        monkeypatch.setattr(client, "_chat", fake_chat)
        captured.setdefault("response_formats", [])
        return client

    def test_pre_populated_cache_skips_strict(self, monkeypatch):
        from autonomous.ai.models.openai_compat import OpenAIClient
        # Simulate "we already discovered this combo doesn't support strict."
        _UNSUPPORTED_STRICT_MODE.add(("cache-model", "https://cache-endpoint/api"))

        captured = {}
        client = self._client(monkeypatch, captured)

        OpenAIClient.generate_json(
            client, "prompt", json_schema=self.SAMPLE_SCHEMA
        )

        # Only ONE call — went directly to loose mode, no strict attempt.
        assert len(captured["response_formats"]) == 1
        assert captured["response_formats"][0] == {"type": "json_object"}

    def test_different_endpoint_still_tries_strict(self, monkeypatch):
        """Cache is per (model, endpoint). A different endpoint isn't
        short-circuited just because some other combo failed."""
        from autonomous.ai.models.openai_compat import OpenAIClient
        _UNSUPPORTED_STRICT_MODE.add(("other-model", "https://other-endpoint/api"))

        captured = {}
        client = self._client(monkeypatch, captured)
        # Our client is ("cache-model", "https://cache-endpoint/api")

        OpenAIClient.generate_json(
            client, "prompt", json_schema=self.SAMPLE_SCHEMA
        )

        assert len(captured["response_formats"]) == 1
        assert captured["response_formats"][0]["type"] == "json_schema"

    def test_cache_persists_across_generate_json_calls(self, monkeypatch):
        """Once cached, every subsequent call to the same combo
        short-circuits — no per-call wasted attempts."""
        from autonomous.ai.models.openai_compat import OpenAIClient
        captured = {"response_formats": []}
        client = self._client(monkeypatch, captured)

        # Pre-populate as if a previous fallback discovered unsupported-ness.
        _UNSUPPORTED_STRICT_MODE.add(("cache-model", "https://cache-endpoint/api"))

        for _ in range(3):
            OpenAIClient.generate_json(
                client, "prompt", json_schema=self.SAMPLE_SCHEMA
            )

        assert len(captured["response_formats"]) == 3
        for rf in captured["response_formats"]:
            assert rf == {"type": "json_object"}
