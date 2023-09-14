import os
from concurrent.futures import ProcessPoolExecutor

from redis import Redis
from rq import Queue, Worker
from rq.job import Job

from autonomous import log


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
    def running(self):
        return self.status == "running"

    @property
    def finished(self):
        return self.status == "finished"

    @property
    def failed(self):
        return self.status == "failed"

    def result(self):
        return self.job.latest_result()

    @property
    def return_value(self):
        return self.job.return_value()


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

    def task(self, func, *args, **kwargs):
        """
        :param job: job function
        :param args: job function args
        :param kwargs: job function kwargs
        args and kwargs: use these to explicitly pass arguments and keyword to the underlying job function. This is useful if your function happens to have conflicting argument names with RQ, for example description or ttl.
        :return: job
        """
        print("task 1", func)
        job = AutoTasks.queue.enqueue(func, *args, **kwargs)
        print("task 2", job.id)
        AutoTasks.all_tasks.append(AutoTask(job))
        print("task 3", job.id)
        with ProcessPoolExecutor() as executor:
            print("task 4", job.id)
            worker = Worker(
                [AutoTasks.queue.name], connection=Redis(**AutoTasks.config)
            )
            executor.submit(worker.work, burst=True)
        print("task 5", job.id)
        return AutoTask(job)

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


# if __name__ == "__main__":
#     autotasks = AutoTasks()
#     for _ in range(autotasks.workers):
#         create_worker(autotasks.queue.name)
