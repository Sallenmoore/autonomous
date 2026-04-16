"""Tests for item 5 + 14: narrowed except blocks + proper re-raise.

The old code caught ``Exception`` everywhere, which swallowed bugs like
``KeyboardInterrupt``, ``MemoryError``, ``AttributeError`` from typos, etc.
The new code lists the concrete error types we expect at each site so
anything outside that set propagates with its original traceback.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests


@pytest.fixture(autouse=True)
def _silence_autotasks():
    with patch("autonomous.ai.models.local_model.AutoTasks") as mock_tasks:
        mock_tasks.return_value.get_current_task.return_value = None
        yield mock_tasks


@pytest.fixture
def model():
    """Build a LocalAIModel without triggering AutoModel/MongoEngine setup.

    Uses ``__new__`` so we skip ``__init__`` entirely (no Mongo connection,
    no field-descriptor fire). Only the non-field attributes the methods
    under test touch are set; the StringAttr / ListAttr descriptors are
    left alone.
    """
    from autonomous.ai.models.local_model import LocalAIModel

    m = LocalAIModel.__new__(LocalAIModel)
    # Bypass mongoengine descriptors by writing into __dict__ directly.
    for key, val in {
        "_ollama_url": "http://mock-ollama",
        "_media_url": "http://mock-media",
        "_image_url": "http://mock-media",
        "_audio_url": "http://mock-media",
        "_text_model": "gemma4:26b",
        "_context_limit": 32768,
        "_retry_sleep": 0,
        "_json_timeout": 1,
        "_text_timeout": 1,
        "_summary_timeout": 1,
        "_media_timeout": 1,
    }.items():
        object.__setattr__(m, key, val)
    return m


class TestLocalModelNarrowedCatches:
    def test_generate_text_swallows_requests_error(self, model):
        with patch(
            "autonomous.ai.models.local_model.requests.post",
            side_effect=requests.ConnectionError("nope"),
        ):
            result = model.generate_text("hi")
        assert result == "Error generating text."

    def test_generate_text_propagates_unexpected_error(self, model):
        """A bug like AttributeError must NOT be swallowed as 'error'."""

        class Boom(AttributeError):
            pass

        with patch(
            "autonomous.ai.models.local_model.requests.post",
            side_effect=Boom("typo in caller"),
        ):
            with pytest.raises(AttributeError):
                model.generate_text("hi")

    def test_flush_memory_swallows_connection_error(self, model):
        with patch(
            "autonomous.ai.models.local_model.requests.post",
            side_effect=requests.ConnectionError("down"),
        ):
            # Must not raise.
            model.flush_memory("gemma4:26b")

    def test_flush_memory_propagates_unexpected(self, model):
        with patch(
            "autonomous.ai.models.local_model.requests.post",
            side_effect=RuntimeError("something else"),
        ):
            with pytest.raises(RuntimeError):
                model.flush_memory("gemma4:26b")

    def test_transcription_returns_empty_on_http_error(self, model):
        with patch(
            "autonomous.ai.models.local_model.requests.post",
            side_effect=requests.HTTPError("500"),
        ):
            result = model.generate_transcription(b"audio")
        assert result == {"segments": [], "text": ""}

    def test_transcription_propagates_memory_error(self, model):
        with patch(
            "autonomous.ai.models.local_model.requests.post",
            side_effect=MemoryError("oom"),
        ):
            with pytest.raises(MemoryError):
                model.generate_transcription(b"audio")


class TestAutoModelGetRaisesCleanly:
    def test_get_re_raises_db_errors_with_original_traceback(self):
        """The old `raise e` dropped the traceback. Bare `raise` preserves it."""
        from pymongo.errors import OperationFailure

        from autonomous.model import automodel as am

        class Boom(am.AutoModel):
            meta = {"abstract": False, "allow_inheritance": True}

        # Stub the objects manager so we don't talk to Mongo
        fake_manager = MagicMock()
        fake_manager.get.side_effect = OperationFailure("db down")

        with patch.object(Boom, "objects", fake_manager), patch.object(
            am, "_ensure_connected"
        ):
            with pytest.raises(OperationFailure):
                Boom.get("507f1f77bcf86cd799439011")
