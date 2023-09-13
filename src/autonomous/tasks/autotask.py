import os
from concurrent.futures import ProcessPoolExecutor

from redis import Redis
from rq import Queue, Worker
from rq.job import Job

from autonomous import log


class AutoTasks:
    _connection = None
    queue = None
    workers = []
    all_tasks = []
    config = {
        "host": os.environ.get("REDIS_HOST", ""),
        "port": os.environ.get("REDIS_PORT", ""),
        "password": os.environ.get("REDIS_PASSWORD"),
        "username": os.environ.get("REDIS_USERNAME"),
        "db": os.environ.get("REDIS_DB", ""),
    }

    class AutoTask:
        def __init__(self, job):
            self.job = job

        @property
        def id(self):
            return self.job.id

        @property
        def status(self):
            return self.job.get_status()

        def result(self):
            return self.job.latest_result()

        @property
        def return_value(self):
            return self.job.return_value()

    def __init__(self, queue="default", num_workers=3):
        if not AutoTasks._connection:
            options = {}

            if AutoTasks.config.get("username"):
                options["username"] = AutoTasks.config.get("username")
            if AutoTasks.config.get("username"):
                options["password"] = AutoTasks.config.get("password")
            if AutoTasks.config.get("db"):
                options["db"] = AutoTasks.config.get("db")

            AutoTasks._connection = Redis(
                host=AutoTasks.config.get("host"),
                port=AutoTasks.config.get("port"),
                **options,
            )
        AutoTasks.queue = Queue(queue, connection=AutoTasks._connection)

    def task(self, job, *args, **kwargs):
        """
        :param job: job function
        :param args: job function args
        :param kwargs: job function kwargs
        args and kwargs: use these to explicitly pass arguments and keyword to the underlying job function. This is useful if your function happens to have conflicting argument names with RQ, for example description or ttl.
        :return: job
        """
        job = AutoTasks.queue.enqueue(job, *args, **kwargs)
        AutoTasks.all_tasks.append(self.AutoTask(job))
        with ProcessPoolExecutor() as executor:
            executor.submit(create_worker, AutoTasks.queue.name)
            # log(result)
        return self.AutoTask(job)

    # get job given its id
    def get_task(self, job_id):
        # breakpoint()
        job = AutoTasks.queue.fetch_job(job_id)
        return self.AutoTask(job)

    # get job given its id
    def get_tasks(self):
        return AutoTasks.all_tasks

    def clear(self):
        AutoTasks.queue.empty()


def create_worker(queue):
    Worker([queue], connection=Redis(**AutoTasks.config)).work(burst=True)
