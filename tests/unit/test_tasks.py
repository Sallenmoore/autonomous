from autonomous import log
from autonomous.tasks import Task
import time


class MockTask(Task):
    def __init__(self):
        super().__init__()
        self.startup_called = False
        self.shutdown_called = False
        self.handle_called_count = 0

    def startup(self):
        self.startup_called = True
        time.sleep(1)

    def shutdown(self):
        self.shutdown_called = True
        time.sleep(1)

    def task(self):
        time.sleep(1)
        self.handle_called_count += 1


class LongMockTask(MockTask):
    def task(self):
        time.sleep(30)
        self.handle_called_count += 1


class ErrorMockTask(MockTask):
    def task(self):
        raise Exception("ErrorMockTask")


class TestTasks:
    def test_base_task_startup_shutdown_handle(self):
        task = MockTask()

        # The task should not be running initially
        assert not task.is_alive()
        assert not task.startup_called
        assert not task.shutdown_called
        assert task.handle_called_count == 0
        assert Task.runningtasks[task.name] == "initialized"

        # Start the task and let it run for a while
        task.start()
        assert Task.runningtasks[task.name] == "starting"
        assert task.is_alive()
        assert task.startup_called
        assert not task.shutdown_called
        assert task.handle_called_count == 0

        # Wait for the task to stop
        task.join()
        assert Task.runningtasks[task.name] == "complete"
        assert not task.is_alive()
        assert task.startup_called
        assert task.shutdown_called

        # Ensure that handle was called at least once
        assert task.handle_called_count > 0

    def test_base_task_queue_interaction(self):
        pretask = MockTask()
        task = MockTask()

        # The task should not be running initially
        assert not pretask.is_alive()
        assert not pretask.startup_called
        assert not pretask.shutdown_called
        assert pretask.handle_called_count == 0
        assert not task.is_alive()
        assert not task.startup_called
        assert not task.shutdown_called
        assert task.handle_called_count == 0

        pretask.start()
        pretask.join()
        assert not pretask.is_alive()

        task.start()
        task.join()
        assert not task.is_alive()

        # Ensure that startup and shutdown were called
        assert pretask.startup_called
        assert pretask.shutdown_called
        assert task.startup_called
        assert task.shutdown_called

        # Ensure that handle was called at least once
        assert pretask.handle_called_count > 0
        assert task.handle_called_count > 0

    def test_base_long_task(self):
        task = LongMockTask()

        # The task should not be running initially
        assert not task.is_alive()
        assert not task.startup_called
        assert not task.shutdown_called
        assert task.handle_called_count == 0

        # Enqueue the task and wait for it to start
        task.start()
        time.sleep(3)
        # The task should be running after enqueuing
        assert task.is_alive()
        assert Task.runningtasks[task.name] == "running"
        # Wait for the task to stop
        task.join()

        # The task should have stopped after stopping
        assert not task.is_alive()

        # Ensure that startup and shutdown were called
        assert task.startup_called
        assert task.shutdown_called

        # Ensure that handle was called at least once
        assert task.handle_called_count > 0

    def test_error_task(self):
        task = ErrorMockTask()
        try:
            task.start()
        except Exception as e:
            assert str(e) == "ErrorMockTask"
