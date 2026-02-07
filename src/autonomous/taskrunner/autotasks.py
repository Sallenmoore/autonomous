import os
from enum import Enum

from redis import Redis
from rq import Queue, get_current_job
from rq.command import send_stop_job_command
from rq.job import Job


# 1. Define Priorities clearly
class TaskPriority(Enum):
    HIGH = "high"
    DEFAULT = "default"
    LOW = "low"
    IMAGE = "image"
    AUDIO = "audio"


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
    def func_name(self):
        return self.job.func_name

    @property
    def timeout(self):
        return self.job.timeout

    @property
    def enqueued_at(self):
        return self.job.enqueued_at

    @property
    def started_at(self):
        return self.job.started_at

    @property
    def ended_at(self):
        return self.job.ended_at

    @property
    def retries_left(self):
        return self.job.retries_left

    @property
    def is_failed(self):
        return self.job.is_failed

    @property
    def is_finished(self):
        return self.job.is_failed

    @property
    def kwargs(self):
        return self.job.kwargs

    @property
    def origin(self):
        return self.job.origin

    @property
    def exc_info(self):
        return self.job.exc_info

    @property
    def result(self):
        return self.job.result

    def delete(self):
        self.job.delete()

    def meta(self, key=None, value=None):
        if value:
            self.job.meta[key] = value
            self.job.save_meta()
        if key:
            return self.job.meta.get(key, "")
        return self.job.meta


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
        job_timeout = kwargs.pop("_task_job_timeout", 7200)

        # 2. Extract Priority (support Enum or string)
        priority = kwargs.pop("priority", TaskPriority.DEFAULT)
        queue_name = priority.value if isinstance(priority, TaskPriority) else priority

        # 3. Get the specific queue
        q = self._get_queue(queue_name)

        # 4. Enqueue
        job = q.enqueue(func, args=args, kwargs=kwargs, job_timeout=job_timeout)

        return AutoTask(job)

    def get_current_task(self):
        if job := get_current_job():
            return AutoTask(job)

    def get_task(self, job_id):
        try:
            if job := Job.fetch(job_id, connection=AutoTasks._connection):
                return AutoTask(job)
        except Exception:
            return None

    def get_tasks(self):

        high_queue = Queue("high", connection=self._connection)
        default_queue = Queue("default", connection=self._connection)
        low_queue = Queue("low", connection=self._connection)
        audio_queue = Queue("audio", connection=self._connection)
        image_queue = Queue("image", connection=self._connection)

        registries = {
            "started": [
                high_queue.started_job_registry,
                default_queue.started_job_registry,
                low_queue.started_job_registry,
                audio_queue.started_job_registry,
                image_queue.started_job_registry,
            ],
            "finished": [
                high_queue.finished_job_registry,
                default_queue.finished_job_registry,
                low_queue.finished_job_registry,
                audio_queue.finished_job_registry,
                image_queue.finished_job_registry,
            ],
            "failed": [
                high_queue.failed_job_registry,
                default_queue.failed_job_registry,
                low_queue.failed_job_registry,
                audio_queue.failed_job_registry,
                image_queue.failed_job_registry,
            ],
            "queued": [high_queue, default_queue, low_queue, audio_queue, image_queue],
        }

        tasks = {}
        for status, regs in registries.items():
            all_job_ids = []
            for reg in regs:
                all_job_ids.extend(reg.get_job_ids())
            # Use a set to remove duplicate job_ids if a job is in multiple registries
            unique_job_ids = sorted(list(set(all_job_ids)), reverse=True)
            jobs = Job.fetch_many(unique_job_ids, connection=self._connection)
            # Filter out None values in case a job expired between fetch and get
            tasks[status] = [AutoTask(job) for job in jobs if job]
        return tasks

    def kill(self, pk):
        job = self.get_task(pk)
        if job.status == "started":
            send_stop_job_command(AutoTasks._connection, job.id)
        job.delete()
