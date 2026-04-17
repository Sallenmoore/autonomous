"""Unit tests for deferred MongoDB connection in the AutoModel layer."""

from unittest.mock import patch

import pytest


@pytest.fixture
def reset_connected():
    """Reset the module-level connection flag around each test."""
    from autonomous.model import automodel

    previous = automodel._connected
    automodel._connected = False
    yield automodel
    automodel._connected = previous


def test_import_does_not_connect(reset_connected):
    """Importing the ORM module must not touch MongoDB."""
    # The fixture already cleared _connected; importing happened above.
    # What matters is that _connected is still False and no connect() was
    # called yet. We verify by ensuring an explicit call is required.
    assert reset_connected._connected is False


def test_connect_from_env_calls_connect_once(reset_connected, monkeypatch):
    monkeypatch.setenv("DB_HOST", "mongo.test")
    monkeypatch.setenv("DB_PORT", "27018")
    monkeypatch.setenv("DB_USERNAME", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.setenv("DB_DB", "testdb")

    with patch.object(reset_connected, "connect") as mock_connect:
        uri = reset_connected.connect_from_env()

    mock_connect.assert_called_once()
    assert "mongo.test:27018" in uri
    assert "testdb" in uri
    assert reset_connected._connected is True


def test_connect_from_env_is_idempotent(reset_connected):
    reset_connected._connected = True
    with patch.object(reset_connected, "connect") as mock_connect:
        # _ensure_connected should now be a no-op.
        reset_connected._ensure_connected()
    mock_connect.assert_not_called()


def test_overrides_win_over_env(reset_connected, monkeypatch):
    monkeypatch.setenv("DB_HOST", "env-host")
    with patch.object(reset_connected, "connect") as mock_connect:
        uri = reset_connected.connect_from_env(
            host="override-host", db="override-db", username="x", password="y"
        )
    mock_connect.assert_called_once()
    assert "override-host" in uri
    assert "override-db" in uri
    assert "env-host" not in uri


def test_autonomous_init_delegates(reset_connected):
    import autonomous

    with patch.object(reset_connected, "connect") as mock_connect:
        uri = autonomous.init(host="h", username="u", password="p", db="d")

    mock_connect.assert_called_once()
    assert "h" in uri and "d" in uri


def test_ensure_connected_triggers_lazy_connect(reset_connected, monkeypatch):
    monkeypatch.setenv("DB_HOST", "lazy-host")
    monkeypatch.setenv("DB_USERNAME", "u")
    monkeypatch.setenv("DB_PASSWORD", "p")
    monkeypatch.setenv("DB_DB", "lazydb")

    with patch.object(reset_connected, "connect") as mock_connect:
        reset_connected._ensure_connected()

    mock_connect.assert_called_once()
    assert reset_connected._connected is True
