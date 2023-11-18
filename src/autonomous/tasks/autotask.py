import importlib
import os
import subprocess

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
        status = self.job.get_status()
        if status in ["running", "queued", "started"]:
            return "running"
        return status

    @property
    def running(self):
        return self.status == "running"

    @property
    def finished(self):
        result = self.status == "finished"
        return result

    @property
    def failed(self):
        result = self.status == "failed"
        return result

    @property
    def result(self):
        result = self.job.latest_result()
        result_dict = {
            "id": self.id,
            "return_value": result.return_value if result else None,
            "status": self.status,
            "error": result.exc_string
            if result and result.type in [result.Type.FAILED, result.Type.STOPPED]
            else None,
        }

        return result_dict

    @property
    def return_value(self):
        return self.result.get("return_value")


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
        "db": os.environ.get("REDIS_DB", 0),
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
        args and kwargs: use these to explicitly pass arguments and keyword to the underlying job function.
        _task_<option>:pass options to the task object
        :return: job
        """
        job = AutoTasks.queue.enqueue(
            func,
            job_timeout=kwargs.get("_task_job_timeout", 3600),
            args=args,
            kwargs=kwargs,
        )
        self.create_worker(func)
        new_task = AutoTask(job)
        AutoTasks.all_tasks.append(new_task)
        return new_task

    def create_worker(self, func):
        # Get the module containing the target_function
        module = func.__module__

        # Get the file path of the module
        module_path = importlib.import_module(module).__file__

        # Set the PYTHONPATH environment variable
        pythonpath = os.path.dirname(module_path)
        env = os.environ.copy()
        env["PYTHONPATH"] = pythonpath

        rq_user_pass = f"{self.config['username']}:{self.config['password']}"
        rq_url = f"{self.config['host']}:{self.config['port']}"
        rq_db = self.config["db"]
        rq_worker_command = (
            f"rq worker --url redis://{rq_user_pass}@{rq_url}/{rq_db} --burst"
        )

        worker = subprocess.Popen(rq_worker_command, shell=True, env=env)
        self.workers.append(worker)
        return worker

    # get job given its id
    def get_task(self, job_id):
        # breakpoint()
        task = AutoTasks.queue.fetch_job(job_id)
        return AutoTask(task)

    # get job given its id
    def get_tasks(self):
        return [AutoTask(w) for w in Worker.all(queue=AutoTasks.queue)]

    def clear(self):
        AutoTasks.queue.empty()
        AutoTasks.all_tasks = []


# if __name__ == "__main__":
#     autotasks = AutoTasks()
#     for _ in range(autotasks.workers):
#         create_worker(autotasks.queue.name)
