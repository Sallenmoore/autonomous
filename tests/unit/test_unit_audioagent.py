"""Tests for the split-out AudioAgent.transcribe / .dramatize.

Pre-split, AudioAgent.transcribe ran Whisper AND an LLM screenplay-format
pass in one call, threading rolling context across chunks. The new shape
hard-separates the two — transcribe() is Whisper-only, dramatize() runs
the LLM over the COMPLETE transcript with no rolling-context crutch.

These tests pin:
- transcribe() returns the raw provider response (not a string)
- transcribe() doesn't invoke generate_text (no LLM pass)
- dramatize() invokes generate_text with the world-context dict
- dramatize() returns "" on empty input (no provider call)
- DRAMATIZE_PROMPT no longer contains the rolling-context paragraph
- env-driven provider routing: transcribe uses TRANSCRIBE_AI_AGENT,
  dramatize uses TEXT_AI_AGENT
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def agent(monkeypatch):
    """Build an AudioAgent without triggering AutoModel/MongoEngine setup."""
    from autonomous.ai.audioagent import AudioAgent

    a = AudioAgent.__new__(AudioAgent)
    object.__setattr__(a, "_data", {
        "name": "audioagent",
        "provider": "local",
        "instructions": "test",
        "description": "test",
    })
    object.__setattr__(a, "_dynamic_fields", {})
    object.__setattr__(a, "_changed_fields", [])
    object.__setattr__(a, "_initialised", True)
    object.__setattr__(a, "_created", False)
    return a


# --------------------------------------------------------------------- #
# transcribe()                                                          #
# --------------------------------------------------------------------- #

class TestTranscribe:
    def test_returns_raw_provider_response_unchanged(self, agent):
        verbose_json = {
            "text": "hello world",
            "segments": [{"start": 0.0, "end": 1.0, "text": "hello world"}],
        }
        client = MagicMock()
        client.generate_transcription.return_value = verbose_json

        with patch.object(agent, "get_client", return_value=client):
            result = agent.transcribe(b"opus bytes")

        assert result is verbose_json
        client.generate_transcription.assert_called_once_with(b"opus bytes")

    def test_does_not_invoke_generate_text(self, agent):
        """The whole point of the split: no LLM pass during transcribe."""
        client = MagicMock()
        client.generate_transcription.return_value = {"text": "x", "segments": []}

        with patch.object(agent, "get_client", return_value=client):
            agent.transcribe(b"opus bytes")

        client.generate_text.assert_not_called()

    def test_uses_transcribe_ai_agent_env_var(self, agent, monkeypatch):
        monkeypatch.setenv("TRANSCRIBE_AI_AGENT", "openai")
        client = MagicMock()
        client.generate_transcription.return_value = {"text": "", "segments": []}

        with patch.object(agent, "get_client", return_value=client) as m:
            agent.transcribe(b"opus bytes")

        m.assert_called_once_with("openai")


# --------------------------------------------------------------------- #
# dramatize()                                                           #
# --------------------------------------------------------------------- #

class TestDramatize:
    def test_invokes_generate_text_with_world_context(self, agent):
        client = MagicMock()
        client.generate_text.return_value = "DM: Welcome.\nPLAYER: I attack."

        ctx = {"Players": "Alice, Bob", "Campaign": "Foo"}
        with patch.object(agent, "get_client", return_value=client):
            result = agent.dramatize("alice says hi bob says yo", world_context=ctx)

        assert "PLAYER: I attack." in result
        kwargs = client.generate_text.call_args.kwargs
        assert kwargs["context"] == ctx
        assert kwargs["temperature"] == 0.3
        # The transcript MUST be substituted into the prompt.
        assert "alice says hi bob says yo" in kwargs["message"]

    def test_empty_transcript_skips_provider_call(self, agent):
        """No transcript → don't pay for an LLM call to format nothing."""
        client = MagicMock()

        with patch.object(agent, "get_client", return_value=client):
            result = agent.dramatize("")

        assert result == ""
        client.generate_text.assert_not_called()

    def test_world_context_defaults_to_empty_dict(self, agent):
        """Caller can omit context and the LLM still runs (with no grounding)."""
        client = MagicMock()
        client.generate_text.return_value = "ok"

        with patch.object(agent, "get_client", return_value=client):
            agent.dramatize("some transcript")

        kwargs = client.generate_text.call_args.kwargs
        assert kwargs["context"] == {}

    def test_uses_text_ai_agent_env_var(self, agent, monkeypatch):
        monkeypatch.setenv("TEXT_AI_AGENT", "gemini")
        client = MagicMock()
        client.generate_text.return_value = "ok"

        with patch.object(agent, "get_client", return_value=client) as m:
            agent.dramatize("some transcript")

        m.assert_called_once_with("gemini")


# --------------------------------------------------------------------- #
# Prompt content                                                        #
# --------------------------------------------------------------------- #

class TestDramatizePrompt:
    def test_no_rolling_context_paragraph(self):
        """The pre-split prompt had a `### PREVIOUS CHUNK ENDING ###`
        section threaded between chunks. The full-transcript design makes
        that crutch unnecessary; the prompt must not still reference it."""
        from autonomous.ai.audioagent import DRAMATIZE_PROMPT

        assert "ROLLING" not in DRAMATIZE_PROMPT.upper()
        assert "PREVIOUS CHUNK" not in DRAMATIZE_PROMPT.upper()

    def test_prompt_has_transcript_placeholder(self):
        """Format string must accept transcript= so the caller can inject."""
        from autonomous.ai.audioagent import DRAMATIZE_PROMPT

        out = DRAMATIZE_PROMPT.format(transcript="HELLO")
        assert "HELLO" in out
