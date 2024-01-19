import os
import time

import pytest
import redis

from autonomous import log
from autonomous.tasks import AutoTasks
from tests.assets.tasktesters import myfailedtask, mylongtask, mytask


# @pytest.mark.skip(reason="dumb")
def test_connection():
    config = {
        "host": os.environ.get("REDIS_HOST", ""),
        "port": os.environ.get("REDIS_PORT", ""),
        "password": os.environ.get("REDIS_PASSWORD"),
        "username": os.environ.get("REDIS_USERNAME"),
        "db": os.environ.get("REDIS_DB", ""),
    }
    r = redis.Redis(**config)
    log(r.get_connection_kwargs())
    assert r.ping()
    assert r.set("key1", "123")
    assert r.get("key1")


# @pytest.mark.skip(reason="OpenAI API is not free")
class TestAutoTasks:
    def test_autotask_connection(self):
        tasks = AutoTasks()
        tasks.clear()
        assert tasks._connection.ping()
        assert tasks.queue
        assert tasks.queue.job_ids == []

    def test_autotask_concurrency(self):
        tasks = AutoTasks()
        tasks.clear()
        job = tasks.task(mylongtask)
        log(job.id)
        job = tasks.task(mylongtask)
        log(job.id)
        assert job.id

    def test_autotask_add(self):
        tasks = AutoTasks()
        tasks.clear()
        job = tasks.task(mytask, 5, 7)
        assert job.id

    def test_autotask_get(self):
        tasks = AutoTasks()
        tasks.clear()
        job = tasks.task(mytask, 5, 7)
        log(job.id)
        result = tasks.get_task(job.id)
        assert result

    def test_autotask_status(self):
        tasks = AutoTasks()
        tasks.clear()
        job = tasks.task(mytask, 5, 7)
        while job.status == "running":
            time.sleep(1)
        assert job.status == "finished"

    def test_autotask_results(self):
        tasks = AutoTasks()
        tasks.clear()
        job = tasks.task(mytask, 5, 7)
        while job.status not in ["finished", "failed"]:
            time.sleep(1)
            print(job.status)
        assert job.return_value == 12

    def test_autotask_all(self):
        tasks = AutoTasks()
        tasks.clear()
        (tasks.task(mytask, 5, i) for i in range(3))
        for t in tasks.get_tasks():
            assert t.return_value or t.status == "running"

    def test_autotask_fail(self):
        tasks = AutoTasks()
        tasks.clear()
        task = tasks.task(myfailedtask, 5, 5)
        while task.status == "running":
            time.sleep(1)
        assert task.status == "failed"
        assert task.result["error"]
        print(task.result["error"])
