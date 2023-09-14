import os
import time

import pytest
import redis
from rq import get_current_job

from autonomous import log
from autonomous.tasks import AutoTasks


def mylongtask():
    job = get_current_job()
    print(f"\nCurrent job 1: {job.id}")
    time.sleep(10)
    print(f"\nCurrent job 2: {job.id}")
    return job.id


def mytask(a, b):
    job = get_current_job()
    print(f"\nCurrent job: {job.id}")
    time.sleep(2)
    return a + b


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
        result = job.status
        assert result

    def test_autotask_results(self):
        tasks = AutoTasks()
        tasks.clear()
        job = tasks.task(mytask, 5, 7)
        time.sleep(10)
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
