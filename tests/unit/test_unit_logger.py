"""Unit tests for the logger (item 4 rewrite).

The logger must not touch the filesystem at import time and must remain
swappable for tests without breaking ``from autonomous import log``.
"""

import importlib
import os
from pathlib import Path

import pytest


@pytest.fixture
def isolated_logger(monkeypatch, tmp_path):
    """Reimport the logger module with cwd pointing at tmp_path.

    Ensures any ``os.makedirs("logs")`` lands inside the tmp dir and gets
    auto-cleaned, and that the default-logger proxy gets a fresh instance.
    """
    monkeypatch.chdir(tmp_path)
    import autonomous.logger as logger_mod

    logger_mod._default_logger = None
    yield logger_mod
    logger_mod._default_logger = None


def test_import_does_not_create_logs_dir(tmp_path, monkeypatch):
    """Just importing the logger must not create ``logs/``."""
    monkeypatch.chdir(tmp_path)
    # Reimport to run import-time code fresh.
    import autonomous.logger as logger_mod

    importlib.reload(logger_mod)
    assert not (tmp_path / "logs").exists()


def test_constructing_logger_does_not_create_logs_dir(isolated_logger, tmp_path):
    isolated_logger.Logger()
    assert not (tmp_path / "logs").exists()


def test_first_call_creates_logs_dir_and_writes(isolated_logger, tmp_path):
    logger = isolated_logger.Logger()
    logger("hello")
    assert (tmp_path / "logs").is_dir()
    assert (tmp_path / "logs" / "current_run_error_log.log").is_file()


def test_disabled_logger_skips_io(isolated_logger, tmp_path):
    logger = isolated_logger.Logger()
    logger.enable(False)
    logger("should not be written")
    assert not (tmp_path / "logs").exists()


def test_file_logging_env_var_disables_disk_io(
    isolated_logger, tmp_path, monkeypatch
):
    monkeypatch.setenv("LOG_TO_FILES", "0")
    logger = isolated_logger.Logger()
    logger("nope")
    assert not (tmp_path / "logs").exists()


def test_enable_file_logging_toggles(isolated_logger, tmp_path):
    logger = isolated_logger.Logger()
    logger.enable_file_logging(False)
    logger("one")
    assert not (tmp_path / "logs").exists()
    logger.enable_file_logging(True)
    logger("two")
    assert (tmp_path / "logs").is_dir()


def test_get_logger_returns_independent_instance(isolated_logger, tmp_path):
    a = isolated_logger.get_logger("a")
    b = isolated_logger.get_logger("b")
    assert a is not b
    a.enable(False)
    assert b.enabled is True


def test_default_log_proxy_still_callable(isolated_logger, tmp_path):
    # Simulates the 20+ modules that do `from autonomous import log`.
    from autonomous import log

    log.enable_file_logging(False)  # keep the test hermetic
    log("proxy call works")
    # And as an attribute, too.
    assert callable(log.enable)


def test_log_proxy_attribute_passthrough(isolated_logger):
    from autonomous import log

    log.enable(False)
    assert log.enabled is False
    log.enable(True)
    assert log.enabled is True


def test_file_error_does_not_crash(isolated_logger, tmp_path, monkeypatch):
    """If the disk is read-only, logging must not raise."""
    logger = isolated_logger.Logger()

    def _raise(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", _raise)
    # Must not raise.
    logger("this should be swallowed")
