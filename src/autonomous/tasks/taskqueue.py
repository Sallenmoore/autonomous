import queue
from . import Task


class TaskQueue:
    def __init__(self):
        self.queue = queue.Queue()

    def add(self, task):
        if isinstance(task, list):
            for t in task:
                self.queue.put(t)
        elif isinstance(task, Task):
            self.queue.put(task)
        else:
            raise TypeError("Task must be of type Task or list")

    def runtasks(self):
        while not self.queue.empty():
            task = self.queue.get()
            task.start()
            task.join()
