from __future__ import annotations

import json
import os
from enum import Enum
from typing import Any

import redis
from redis import Redis
from rq import Queue, get_current_job
from rq.command import send_stop_job_command
from rq.exceptions import NoSuchJobError
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
    def args(self):
        return self.job.args

    @property
    def kwargs(self):
        return self.job.kwargs

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
        return self.job.get_status() == "failed"

    @property
    def is_finished(self):
        return self.job.get_status() == "finished"

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

    def meta(self, *args, **kwargs):
        if args:
            return {k: v for k, v in self.job.meta.items() if k in args}
        if kwargs:
            for k, v in kwargs.items():
                self.job.meta[k] = (
                    json.dumps(v, indent=2) if isinstance(v, dict) else str(v)
                )
        self.job.save_meta()
        return self.job.meta


class AutoTasks:
    """Thin wrapper around RQ + Redis with priority queues.

    Process-wide connection singleton (``AutoTasks._process_connection``)
    is built lazily on the first method call that needs Redis. Each
    instance can override the singleton by either passing
    ``redis_client=`` directly or by passing connection kwargs that get
    used to build a per-instance client.

    Construction never opens a socket. ``AutoTasks()`` in a unit test
    that patches RQ does not need Redis up.
    """

    #: Process-wide singleton built lazily by ``_get_connection``.
    _process_connection: Redis | None = None

    def __init__(
        self,
        redis_client: Redis | None = None,
        *,
        host: str | None = None,
        port: int | None = None,
        password: str | None = None,
        username: str | None = None,
        db: int | None = None,
    ):
        # If a client is injected, the instance overrides the singleton.
        # Useful for tests and multi-cluster apps that want a non-default
        # connection in a particular code path.
        self._instance_connection: Redis | None = redis_client
        # Per-instance overrides applied when the singleton is built.
        self._overrides: dict[str, Any] = {
            k: v
            for k, v in (
                ("host", host),
                ("port", port),
                ("password", password),
                ("username", username),
                ("db", db),
            )
            if v is not None
        }

    # --- connection management ------------------------------------------------

    @property
    def _connection(self) -> Redis:
        """Compatibility alias used by the rest of the module."""
        return self._get_connection()

    def _get_connection(self) -> Redis:
        if self._instance_connection is not None:
            return self._instance_connection
        if AutoTasks._process_connection is None:
            AutoTasks._process_connection = self._build_connection()
        return AutoTasks._process_connection

    def _build_connection(self) -> Redis:
        config = {
            "host": self._overrides.get(
                "host", os.environ.get("REDIS_HOST", "cachedb")
            ),
            "port": int(
                self._overrides.get("port", os.environ.get("REDIS_PORT", 6379))
            ),
            "db": int(
                self._overrides.get("db", os.environ.get("REDIS_DB", 0))
            ),
        }
        password = self._overrides.get("password", os.environ.get("REDIS_PASSWORD"))
        if password:
            config["password"] = password
        username = self._overrides.get("username", os.environ.get("REDIS_USERNAME"))
        if username:
            config["username"] = username
        return Redis(decode_responses=False, **config)

    @classmethod
    def reset_connection(cls) -> None:
        """Drop the process-wide singleton so the next call rebuilds it.

        Test helper. Production callers shouldn't normally need this.
        """
        cls._process_connection = None

    # --- queue / task API -----------------------------------------------------

    def _get_queue(self, priority_name: str) -> Queue:
        """Return (or build) the Queue for ``priority_name``."""
        return Queue(priority_name, connection=self._get_connection())

    def task(self, func, *args, **kwargs) -> AutoTask:
        """Enqueue ``func`` and return an :class:`AutoTask` handle.

        Recognized kwargs:
          - ``priority`` (``TaskPriority`` or str): queue selector
          - ``_task_job_timeout`` (int seconds, default 7200)

        All other args/kwargs forward to ``func``.
        """
        job_timeout = kwargs.pop("_task_job_timeout", 7200)

        priority = kwargs.pop("priority", TaskPriority.DEFAULT)
        queue_name = priority.value if isinstance(priority, TaskPriority) else priority

        q = self._get_queue(queue_name)
        job = q.enqueue(func, args=args, kwargs=kwargs, job_timeout=job_timeout)
        return AutoTask(job)

    def get_current_task(self) -> AutoTask | None:
        if job := get_current_job():
            return AutoTask(job)
        return None

    def get_task(self, job_id: str) -> AutoTask | None:
        try:
            if job := Job.fetch(job_id, connection=self._get_connection()):
                return AutoTask(job)
        except (NoSuchJobError, redis.RedisError):
            return None
        return None

    def get_tasks(self) -> dict[str, list[AutoTask]]:
        connection = self._get_connection()
        high_queue = Queue("high", connection=connection)
        default_queue = Queue("default", connection=connection)
        low_queue = Queue("low", connection=connection)

        registries = {
            "started": [
                high_queue.started_job_registry,
                default_queue.started_job_registry,
                low_queue.started_job_registry,
            ],
            "finished": [
                high_queue.finished_job_registry,
                default_queue.finished_job_registry,
                low_queue.finished_job_registry,
            ],
            "failed": [
                high_queue.failed_job_registry,
                default_queue.failed_job_registry,
                low_queue.failed_job_registry,
            ],
            "queued": [high_queue, default_queue, low_queue],
        }

        tasks: dict[str, list[AutoTask]] = {}
        for status, regs in registries.items():
            all_job_ids: list[str] = []
            for reg in regs:
                all_job_ids.extend(reg.get_job_ids())
            unique_job_ids = sorted(list(set(all_job_ids)), reverse=True)
            jobs = Job.fetch_many(unique_job_ids, connection=connection)
            tasks[status] = [AutoTask(job) for job in jobs if job]
        return tasks

    def kill(self, pk: str) -> None:
        job = self.get_task(pk)
        if job and job.status == "started":
            send_stop_job_command(self._get_connection(), job.id)
        if job:
            job.delete()
