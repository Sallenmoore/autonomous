"""Independent regression tests for logger severity vs. threshold.

Companion to PR #27 / issue #20. The fix replaced
``self.logger.log(self.logger.level, msg)`` with
``self.logger.log(logging.DEBUG, msg)`` so that bare ``log(obj)``
calls always emit at DEBUG severity, decoupled from the
``LOG_LEVEL`` threshold. These tests capture the level argument
passed to the underlying stdlib logger directly, which pins the
contract the PR establishes without coupling to stdlib filtering.

Hermetic: no MongoDB, no network. Runs under ``pytest tests/unit``.
"""

from __future__ import annotations

import logging

import pytest


@pytest.fixture
def isolated_logger(monkeypatch, tmp_path):
    """Reimport the logger module with cwd pointing at tmp_path.

    Mirrors the fixture in ``test_unit_logger.py`` so file IO from
    bare calls lands inside the tmp dir and gets auto-cleaned.
    """
    monkeypatch.chdir(tmp_path)
    import autonomous.logger as logger_mod

    logger_mod._default_logger = None
    yield logger_mod
    logger_mod._default_logger = None


def _capture_emit_level(monkeypatch, logger):
    """Replace ``logger.logger.log`` with a recorder that returns the
    severity each bare call emitted at."""
    captured: list[int] = []

    def fake_log(level, msg):
        captured.append(level)

    monkeypatch.setattr(logger.logger, "log", fake_log)
    return captured


def test_bare_call_emits_at_debug_with_default_threshold(
    isolated_logger, monkeypatch
):
    """With LOG_LEVEL unset (defaults to WARNING), bare ``log(obj)``
    must still emit at DEBUG severity."""
    logger = isolated_logger.Logger()
    captured = _capture_emit_level(monkeypatch, logger)

    logger("dev probe")

    assert captured == [logging.DEBUG]


def test_bare_call_emits_at_debug_when_threshold_is_error(
    isolated_logger, monkeypatch
):
    """The regression case from issue #20: storyteller-prod ran with
    ``LOG_LEVEL=ERROR``, and pre-fix every bare call appeared as
    [ERROR] in gunicorn logs because severity tracked the threshold.
    Post-fix, severity is DEBUG regardless of threshold."""
    logger = isolated_logger.Logger()
    logger.set_level("ERROR")
    captured = _capture_emit_level(monkeypatch, logger)

    logger("error-threshold probe")

    assert captured == [logging.DEBUG], (
        "bare log(obj) must emit at DEBUG even when threshold is ERROR; "
        "got severity=%s" % captured
    )


def test_bare_call_severity_is_invariant_under_threshold_changes(
    isolated_logger, monkeypatch
):
    """Across the full LOG_LEVEL range, severity stays at DEBUG.
    A regression that re-couples severity to threshold (e.g. by
    passing ``self.logger.level`` again) would show varying values
    here; this test pins the invariant."""
    logger = isolated_logger.Logger()
    captured = _capture_emit_level(monkeypatch, logger)

    for level_name in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        logger.set_level(level_name)
        logger(f"probe at threshold={level_name}")

    assert captured == [logging.DEBUG] * 5, (
        "severity must be DEBUG for every threshold; got %s" % captured
    )


def test_bare_call_severity_is_not_self_logger_level(
    isolated_logger, monkeypatch
):
    """Direct contradiction of the pre-fix behavior. If someone
    re-introduces ``self.logger.log(self.logger.level, ...)``, the
    severity captured here would be ERROR (40), not DEBUG (10)."""
    logger = isolated_logger.Logger()
    logger.set_level("ERROR")
    captured = _capture_emit_level(monkeypatch, logger)

    logger("regression sentinel")

    [emitted_severity] = captured
    assert emitted_severity != logger.logger.level, (
        "bare call severity must not equal threshold "
        "(threshold=%s, emitted=%s) — that was the pre-fix bug"
        % (logger.logger.level, emitted_severity)
    )
    assert emitted_severity == logging.DEBUG


def test_disabled_logger_does_not_emit_at_any_severity(
    isolated_logger, monkeypatch
):
    """Sanity: disabling the logger short-circuits before the
    ``self.logger.log`` call, so no severity is emitted at all.
    Guards against a future change that moves the disable check
    to after the log call."""
    logger = isolated_logger.Logger()
    logger.enable(False)
    captured = _capture_emit_level(monkeypatch, logger)

    logger("should be suppressed")

    assert captured == []
