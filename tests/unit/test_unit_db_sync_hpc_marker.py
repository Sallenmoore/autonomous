"""Tests for the HPC failure marker normalization in db_sync._get_vector_openai.

The function is the OpenAI-compatible embedding path used by the RQ worker.
It must:

1. Return the embedding when the upstream client succeeds.
2. Return None and emit a stable "[HPC-UNREACHABLE]" marker when the
   client raises HPCUnreachableError (the documented degrade path).
3. Return None and emit the same marker family for any other unexpected
   exception, with the exception class name surfaced for triage.

The "[HPC-UNREACHABLE]" prefix is an observability contract — log scrapers
match on it. Renaming requires consumer coordination, so these tests pin
the marker spelling.
"""

from unittest.mock import patch

import pytest

from autonomous.ai.models.openai_compat import HPCUnreachableError, OpenAIClient
from autonomous.db.db_sync import _get_vector_openai


@pytest.fixture(autouse=True)
def _silence_autotasks():
    # openai_compat imports AutoTasks at module level; neutralize it so
    # the lazy import inside _get_vector_openai doesn't try to reach Redis.
    with patch("autonomous.ai.models.openai_compat.AutoTasks") as mock_tasks:
        mock_tasks.return_value.get_current_task.return_value = None
        yield mock_tasks


class TestSuccess:
    def test_returns_embedding_on_success(self):
        with patch.object(
            OpenAIClient, "get_embedding", return_value=[0.1, 0.2, 0.3]
        ):
            result = _get_vector_openai("some text")
        assert result == [0.1, 0.2, 0.3]


class TestHPCUnreachable:
    def test_returns_none_on_hpc_unreachable(self):
        with patch.object(
            OpenAIClient,
            "get_embedding",
            side_effect=HPCUnreachableError("connection refused"),
        ):
            assert _get_vector_openai("some text") is None

    def test_emits_marker_on_hpc_unreachable(self, capsys):
        with patch.object(
            OpenAIClient,
            "get_embedding",
            side_effect=HPCUnreachableError("connection refused"),
        ):
            _get_vector_openai("some text")
        out = capsys.readouterr().out
        assert "[HPC-UNREACHABLE]" in out
        assert "connection refused" in out
        # The dedicated branch for HPCUnreachableError must NOT mark itself
        # as "(unexpected ...)" — that wording is reserved for the catch-all.
        assert "unexpected" not in out


class TestUnexpectedException:
    def test_returns_none_on_unexpected_exception(self):
        with patch.object(
            OpenAIClient,
            "get_embedding",
            side_effect=ValueError("malformed response"),
        ):
            assert _get_vector_openai("some text") is None

    def test_emits_marker_with_class_name_on_unexpected_exception(self, capsys):
        with patch.object(
            OpenAIClient,
            "get_embedding",
            side_effect=ValueError("malformed response"),
        ):
            _get_vector_openai("some text")
        out = capsys.readouterr().out
        assert "[HPC-UNREACHABLE]" in out
        assert "(unexpected ValueError)" in out
        assert "malformed response" in out

    def test_runtime_error_subclass_other_than_hpc_takes_unexpected_branch(
        self, capsys
    ):
        # A RuntimeError that is NOT HPCUnreachableError must hit the
        # generic branch, since HPCUnreachableError is a RuntimeError
        # subclass — verify ordering of except clauses is correct.
        class OtherRuntimeError(RuntimeError):
            pass

        with patch.object(
            OpenAIClient,
            "get_embedding",
            side_effect=OtherRuntimeError("boom"),
        ):
            assert _get_vector_openai("some text") is None
        out = capsys.readouterr().out
        assert "[HPC-UNREACHABLE]" in out
        assert "(unexpected OtherRuntimeError)" in out


class TestMarkerStability:
    """Pin the marker spelling — renames break log scrapers."""

    def test_marker_is_exactly_hpc_unreachable_in_brackets(self, capsys):
        with patch.object(
            OpenAIClient,
            "get_embedding",
            side_effect=HPCUnreachableError("x"),
        ):
            _get_vector_openai("t")
        captured = capsys.readouterr()
        # Exact bracket form, leading position, no leading whitespace.
        assert captured.out.startswith("[HPC-UNREACHABLE]")
        # Pin stdout (not stderr) — log scrapers tail one stream; if this
        # ever moves to stderr it must be a deliberate, coordinated change.
        assert captured.err == ""
