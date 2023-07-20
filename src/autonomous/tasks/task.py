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
    def __init__(self):
        super().__init__()
        self.handler = TaskInterruptHandler(self)

    def startup(self) -> None:
        log("Task started: override `startup` method to intialize resouces for the task")

    def task(self) -> None:
        log("Task executing: override `task` mwethod to implement the task")

    def shutdown(self) -> None:
        log("Task stopped: override `shutdown` method to clean up resources for the task")

    def run(self) -> None:
        """
        This method will be executed in a separate thread
        when start() method is called.
        :return: None
        """
        self.startup()
        try:
            self.task()
        except Exception as e:
            log(f"Task raised an exception: {e}")
        else:
            log("Task was executed.")
        self.shutdown()
