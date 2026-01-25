import os
from enum import Enum
from redis import Redis
from rq import Queue
from rq.job import Job

# 1. Define Priorities clearly
class TaskPriority(Enum):
    HIGH = "high"
    DEFAULT = "default"
    LOW = "low"

class AutoTask:
    def __init__(self, job):
        self.job = job

    @property
    def id(self):
        return self.job.id

    @property
    def status(self):
        return self.job.get_status()

    @property
    def result(self):
        return {
            "id": self.id,
            "return_value": self.job.result,
            "status": self.status,
            "error": self.job.exc_info
        }

class AutoTasks:
    _connection = None
    # We remove the single 'queue' class attribute because we now have multiple

    config = {
        "host": os.environ.get("REDIS_HOST", "cachedb"),
        "port": os.environ.get("REDIS_PORT", 6379),
        "password": os.environ.get("REDIS_PASSWORD"),
        "username": os.environ.get("REDIS_USERNAME"),
        "db": os.environ.get("REDIS_DB", 0),
    }

    def __init__(self):
        # Establish connection once (Singleton pattern logic)
        if not AutoTasks._connection:
            options = {}
            if AutoTasks.config.get("password"):
                options["password"] = AutoTasks.config.get("password")

            AutoTasks._connection = Redis(
                host=AutoTasks.config.get("host"),
                port=AutoTasks.config.get("port"),
                decode_responses=False,
                **options,
            )

    def _get_queue(self, priority_name):
        """Helper to get or create the queue object for a specific priority"""
        return Queue(priority_name, connection=AutoTasks._connection)

    def task(self, func, *args, **kwargs):
        """
        Enqueues a job.
        kwarg 'priority' determines the queue (default: 'default').
        """
        job_timeout = kwargs.pop("_task_job_timeout", 3600)

        # 2. Extract Priority (support Enum or string)
        priority = kwargs.pop("priority", TaskPriority.DEFAULT)
        queue_name = priority.value if isinstance(priority, TaskPriority) else priority

        # 3. Get the specific queue
        q = self._get_queue(queue_name)

        # 4. Enqueue
        job = q.enqueue(
            func,
            args=args,
            kwargs=kwargs,
            job_timeout=job_timeout
        )

        return AutoTask(job)

    def get_task(self, job_id):
        try:
            job = Job.fetch(job_id, connection=AutoTasks._connection)
            return AutoTask(job)
        except Exception:
            return None