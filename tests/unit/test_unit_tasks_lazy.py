"""Item 12: lazy Redis connection in AutoTasks.

The previous implementation built a Redis client in ``__init__`` from
env vars baked at class-definition time. Tests couldn't construct an
AutoTasks without Redis being up, and config changes required a process
restart.

The new contract:
- Construction is socket-free.
- The first method that needs Redis triggers ``_get_connection``, which
  builds a process-wide singleton from current env (or per-instance
  overrides).
- Tests can inject a client via ``AutoTasks(redis_client=...)``.
- ``AutoTasks.reset_connection()`` drops the singleton between tests.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_singleton():
    from autonomous.taskrunner.autotasks import AutoTasks

    AutoTasks.reset_connection()
    yield
    AutoTasks.reset_connection()


class TestNoConnectionAtConstruction:
    def test_construction_does_not_open_socket(self):
        from autonomous.taskrunner.autotasks import AutoTasks

        with patch("autonomous.taskrunner.autotasks.Redis") as mock_redis:
            AutoTasks()
        mock_redis.assert_not_called()
        assert AutoTasks._process_connection is None

    def test_method_triggers_lazy_connect(self):
        from autonomous.taskrunner.autotasks import AutoTasks

        with patch("autonomous.taskrunner.autotasks.Redis") as mock_redis:
            tasks = AutoTasks()
            assert mock_redis.call_count == 0
            tasks._get_connection()
            assert mock_redis.call_count == 1

    def test_singleton_built_once_across_instances(self):
        from autonomous.taskrunner.autotasks import AutoTasks

        with patch("autonomous.taskrunner.autotasks.Redis") as mock_redis:
            mock_redis.return_value = MagicMock()
            AutoTasks()._get_connection()
            AutoTasks()._get_connection()
            AutoTasks()._get_connection()
        assert mock_redis.call_count == 1


class TestInjectedClient:
    def test_injected_client_is_used(self):
        from autonomous.taskrunner.autotasks import AutoTasks

        client = MagicMock(name="injected")
        tasks = AutoTasks(redis_client=client)
        assert tasks._get_connection() is client

    def test_injected_client_does_not_pollute_singleton(self):
        from autonomous.taskrunner.autotasks import AutoTasks

        client = MagicMock(name="injected")
        AutoTasks(redis_client=client)._get_connection()
        # Singleton wasn't built — a later non-injected instance should
        # build its own.
        with patch("autonomous.taskrunner.autotasks.Redis") as mock_redis:
            AutoTasks()._get_connection()
        mock_redis.assert_called_once()

    def test_per_instance_overrides_passed_to_redis(self):
        from autonomous.taskrunner.autotasks import AutoTasks

        with patch("autonomous.taskrunner.autotasks.Redis") as mock_redis:
            mock_redis.return_value = MagicMock()
            AutoTasks(host="custom-host", port=6390, db=2)._get_connection()
        kwargs = mock_redis.call_args.kwargs
        assert kwargs["host"] == "custom-host"
        assert kwargs["port"] == 6390
        assert kwargs["db"] == 2


class TestEnvAtFirstUseNotImport:
    def test_env_change_after_import_is_picked_up(self, monkeypatch):
        """If REDIS_HOST changes between import and first call, the new
        value wins — proving env is read lazily, not at import.
        """
        from autonomous.taskrunner.autotasks import AutoTasks

        monkeypatch.setenv("REDIS_HOST", "new-host-from-env")
        with patch("autonomous.taskrunner.autotasks.Redis") as mock_redis:
            mock_redis.return_value = MagicMock()
            AutoTasks()._get_connection()
        assert mock_redis.call_args.kwargs["host"] == "new-host-from-env"


class TestResetConnection:
    def test_reset_drops_singleton(self):
        from autonomous.taskrunner.autotasks import AutoTasks

        with patch("autonomous.taskrunner.autotasks.Redis") as mock_redis:
            mock_redis.return_value = MagicMock()
            AutoTasks()._get_connection()
            assert AutoTasks._process_connection is not None
            AutoTasks.reset_connection()
            assert AutoTasks._process_connection is None
            AutoTasks()._get_connection()
        # Two calls = singleton was rebuilt after reset.
        assert mock_redis.call_count == 2
