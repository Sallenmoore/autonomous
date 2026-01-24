import os
from redis import Redis
from rq import Queue
from rq.job import Job

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
        # Simplified result fetching
        return {
            "id": self.id,
            "return_value": self.job.result,
            "status": self.status,
            "error": self.job.exc_info
        }

class AutoTasks:
    _connection = None
    queue = None

    # Config stays the same
    config = {
        "host": os.environ.get("REDIS_HOST", "cachedb"),
        "port": os.environ.get("REDIS_PORT", 6379),
        "password": os.environ.get("REDIS_PASSWORD"),
        "username": os.environ.get("REDIS_USERNAME"),
        "db": os.environ.get("REDIS_DB", 0),
    }

    def __init__(self, queue_name="default"):
        if not AutoTasks._connection:
            options = {}
            if AutoTasks.config.get("password"):
                options["password"] = AutoTasks.config.get("password")

            # Create Redis Connection
            AutoTasks._connection = Redis(
                host=AutoTasks.config.get("host"),
                port=AutoTasks.config.get("port"),
                decode_responses=False, # RQ requires bytes, not strings
                **options,
            )

        # Initialize Queue
        AutoTasks.queue = Queue(queue_name, connection=AutoTasks._connection)

    def task(self, func, *args, **kwargs):
        """
        Enqueues a job to Redis. Does NOT start a worker.
        """
        job_timeout = kwargs.pop("_task_job_timeout", 3600)

        # Enqueue the job
        # func can be a string path or the function object itself
        job = AutoTasks.queue.enqueue(
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
