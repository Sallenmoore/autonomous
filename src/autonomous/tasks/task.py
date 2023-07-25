import threading
from autonomous import log
import signal


class TaskInterruptHandler:
    def __init__(self, task):
        self.task = task
        self.interrupt_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self.handler)

    def handler(self, signum, frame):
        # wait until thread is finished
        if self.task.is_alive():
            self.task.join()
        self.interrupt_handler(signum, frame)


class Task(threading.Thread):
    """
    Create a task to run in a seperate thread.

    ### Usage

    ```python
    class MyTask(Task):
        def startup(self):
            '''optional: initialize resources for the task'''
        def task(self):
            '''implement the task'''
        def shutdown(self):
            '''optional: clean up resources for the task'''
    ```
    -----
    ```
    mytask = MyTask()
    mytask.start()
    print(Task.runningtasks[mytask.name])  # check status of task
    mytask.join() # to wait for the task to complete
    ```

    """

    runningtasks = {}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.handler = TaskInterruptHandler(self)
        Task.runningtasks[self.name] = "initialized"

    def startup(self) -> None:
        log("Task started: override `startup(self)` method to intialize resources for the task")

    def task(self) -> None:
        log("Task executing: override `task` method to implement the task")

    def shutdown(self) -> None:
        log("Task complete: override `shutdown` method to clean up resources for the task")

    def run(self) -> None:
        """
        This method will be executed in a separate thread
        when start() method is called.
        :return: None
        """
        Task.runningtasks[self.name] = "starting"
        self.startup()
        try:
            Task.runningtasks[self.name] = "running"
            self.task()
        except Exception as e:
            Task.runningtasks[self.name] = f"ERROR: {e}"
            log(f"Task raised an exception: {e}")
            raise e
        else:
            log("Task was executed.")
        self.shutdown()
        Task.runningtasks[self.name] = "complete"
