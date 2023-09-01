from autonomous.tasks import AutoTasks
from autonomous import log
import pytest
import requests
import redis


def mytask(url):
    resp = requests.get(url)
    return len(resp.text.split())


def test_connection():
    r = redis.StrictRedis(host="db.samoore.page", port=10003, username="admin", password="BellaEmmmaNatasha77")
    log(r.get_connection_kwargs())
    assert r.ping()
    assert r.set("key1", "123")
    assert r.get("key1")


class TestAutoTasks:
    def test_autotask_connection(self):
        tasks = AutoTasks()
        assert tasks.queue
        assert tasks._connection
        assert tasks._connection.ping()
        log(tasks._connection.ping())

    def test_autotask_add(self):
        tasks = AutoTasks()
        id = tasks.task(mytask)
        assert id

    def test_autotask_get(self):
        tasks = AutoTasks()
        id = tasks.task(mytask)
        result = tasks.get_task(id)
        assert result

    def test_autotask_results(self):
        tasks = AutoTasks()
        id = tasks.task(mytask)
        result = tasks.get_result(id)
        assert result

    def test_autotask_all(self):
        tasks = AutoTasks()
        (tasks.task(mytask) for i in range(3))
        result = tasks.get_all()
        assert result
