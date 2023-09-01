from redis import Redis
from rq import Queue
from autonomous import log
import os


class AutoTasks:
    _connection = None
    queue = None
    config = {
        "host": os.environ.get("REDIS_HOST", ""),
        "port": os.environ.get("REDIS_PORT", ""),
        "password": os.environ.get("REDIS_PASSWORD", ""),
        # "username": os.environ.get("REDIS_USERNAME", "root"),
        # "db": os.environ.get("REDIS_DB", ""),
        "decode_responses": os.environ.get("REDIS_DECODE", True),
    }

    def __init__(self):
        log(**AutoTasks.config)
        if not AutoTasks._connection:
            AutoTasks._connection = Redis(**AutoTasks.config)
        log(AutoTasks._connection)
        if not AutoTasks.queue:
            AutoTasks.queue = Queue(connection=self._connection)
        log(AutoTasks.queue)

    def task(self, job, *args, **kwargs):
        task = self.queue.enqueue(job, *args, **kwargs)
        return task.id

    # get job given its id
    def get_task(self, job_id):
        try:
            return self.queue.fetch_job(job_id)
        except Exception as e:
            return f"invalid:\t{e}"

    # get job given its id
    def get_status(self, job_id):
        try:
            return self.queue.fetch_job(job_id).get_status()
        except Exception as e:
            return f"invalid:\t{e}"

    # get job given its id
    def get_result(self, job_id):
        try:
            return self.queue.fetch_job(job_id).result
        except Exception as e:
            return f"invalid:\t{e}"

    # get all jobs
    def get_all(self):
        # init all_jobs list
        all_jobs = list(
            set(
                [
                    self.queue.started_job_registry.get_job_ids(),
                    self.queue.job_ids.get_job_ids(),  # queued job ids
                    self.queue.failed_job_registry.get_job_ids(),
                    self.queue.deferred_job_registry.get_job_ids(),
                    self.queue.finished_job_registry.get_job_ids(),
                    self.queue.scheduled_job_registry.get_job_ids(),
                ]
            )
        )
        # iterate over job ids list and fetch jobs
        for job_id in all_jobs:
            all_jobs.append(self.get_task(job_id))
        return all_jobs
