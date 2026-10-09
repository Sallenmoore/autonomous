"""Independent test-agent coverage for PR #288 (batch 3).

- #273: ``_get_redis`` / ``_get_mongo_db`` construct their client once
  under a module ``_client_lock`` (double-checked), so concurrent first
  callers can't each build one; the steady-state read skips the lock.
- #281: ``request_indexing(..., debounce=False)`` reaches the worker as
  ``process_single_object_sync(..., debounce=False)``, which skips ONLY
  the 5s sleep; the supersede check still runs. The default enqueue
  payload is unchanged (the kwarg is sent only when False).
"""

import sys
import threading
import time
import types
from unittest.mock import MagicMock

import pytest

from autonomous.db import db_sync

N_THREADS = 16


def _race(fn):
    """Run ``fn`` on N threads released together; return their results."""
    barrier = threading.Barrier(N_THREADS)
    results = [None] * N_THREADS

    def worker(i):
        barrier.wait()
        results[i] = fn()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    return results


def _slow_factory(made):
    """A constructor slow enough that an unlocked check-then-set races."""
    def factory(*a, **kw):
        time.sleep(0.05)
        obj = MagicMock(name=f"client{len(made)}")
        made.append(obj)
        return obj
    return factory


# ---------------------------------------------------------------------------
# #273 singleton construction
# ---------------------------------------------------------------------------


def test_concurrent_first_get_redis_builds_one_client(monkeypatch):
    import redis

    made = []
    monkeypatch.setattr(db_sync, "_redis_client", None)
    monkeypatch.setattr(redis, "Redis", _slow_factory(made))

    results = _race(db_sync._get_redis)
    assert len(made) == 1
    assert all(r is made[0] for r in results)


def test_concurrent_first_get_mongo_db_builds_one_client(monkeypatch):
    made = []
    monkeypatch.setattr(db_sync, "_mongo_client", None)
    monkeypatch.setattr(db_sync, "_mongo_db", None)
    monkeypatch.setattr(db_sync.pymongo, "MongoClient", _slow_factory(made))

    results = _race(db_sync._get_mongo_db)
    assert len(made) == 1
    assert len({id(r) for r in results}) == 1
    assert results[0] is db_sync._mongo_db


class _ExplodingLock:
    def __enter__(self):
        raise AssertionError("fast path must not take _client_lock")

    def __exit__(self, *exc):
        return False


def test_fast_path_skips_lock_once_built(monkeypatch):
    redis_client, mongo_db = object(), object()
    monkeypatch.setattr(db_sync, "_client_lock", _ExplodingLock())
    monkeypatch.setattr(db_sync, "_redis_client", redis_client)
    monkeypatch.setattr(db_sync, "_mongo_db", mongo_db)
    assert db_sync._get_redis() is redis_client
    assert db_sync._get_mongo_db() is mongo_db


def test_client_lock_is_a_real_lock():
    assert isinstance(db_sync._client_lock, type(threading.Lock()))


# ---------------------------------------------------------------------------
# #281 worker side
# ---------------------------------------------------------------------------


@pytest.fixture
def worker(monkeypatch):
    """Stubs for driving process_single_object_sync. Returns
    (redis, mongo_db, sleeps, hsets)."""
    monkeypatch.setitem(sys.modules, "numpy", types.SimpleNamespace(
        float32=object,
        array=lambda v, dtype=None: types.SimpleNamespace(tobytes=lambda: b"v"),
    ))
    redis = MagicMock()
    redis.get.return_value = "tok"
    hsets = []
    redis.hset.side_effect = lambda key, mapping: hsets.append(mapping)
    mongo_db = MagicMock()
    mongo_db.__getitem__.return_value.find_one.return_value = {
        "_id": "x", "name": "a name long enough to index",
    }
    sleeps = []
    monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)
    monkeypatch.setattr(db_sync, "_get_mongo_db", lambda: mongo_db)
    monkeypatch.setattr(db_sync.time, "sleep", sleeps.append)
    monkeypatch.setattr(db_sync, "get_vector", lambda _: [0.1])
    monkeypatch.setattr(db_sync, "record_embedding_sync_event", lambda *_: None)
    return redis, mongo_db, sleeps, hsets


def test_default_worker_still_sleeps_five_seconds(worker):
    _, _, sleeps, hsets = worker
    db_sync.process_single_object_sync("x", "lore", "tok")
    assert sleeps == [5]
    assert len(hsets) == 1


def test_debounce_false_skips_sleep_and_indexes(worker):
    _, _, sleeps, hsets = worker
    db_sync.process_single_object_sync("x", "lore", "tok", debounce=False)
    assert sleeps == []
    assert len(hsets) == 1


def test_debounce_false_still_honors_newer_token(worker):
    redis, mongo_db, sleeps, hsets = worker
    redis.get.return_value = "newer-token"
    db_sync.process_single_object_sync("x", "lore", "tok", debounce=False)
    assert sleeps == []
    assert hsets == []
    redis.get.assert_called_once_with("sync_token:lore:x")
    mongo_db.__getitem__.return_value.find_one.assert_not_called()


def test_debounce_false_expired_token_still_processes(worker):
    # #183 semantics unchanged: an absent token is not a supersede.
    redis, _, _, hsets = worker
    redis.get.return_value = None
    db_sync.process_single_object_sync("x", "lore", "tok", debounce=False)
    assert len(hsets) == 1


# ---------------------------------------------------------------------------
# #281 enqueue side
# ---------------------------------------------------------------------------


@pytest.fixture
def enqueued(monkeypatch):
    from autonomous.taskrunner import autotasks

    calls = []

    class _Tasks:
        def task(self, func, *args, **kwargs):
            calls.append((func, args, kwargs))

    monkeypatch.setattr(autotasks, "AutoTasks", _Tasks)
    monkeypatch.setattr(db_sync, "_requested_doc_vector_indexed", lambda *a: True)
    monkeypatch.setattr(db_sync, "_get_redis", lambda: MagicMock())
    return calls


DEFAULT_KEYS = {"object_id", "collection_name", "token", "priority"}


@pytest.mark.parametrize("kwargs", [{}, {"debounce": True}])
def test_default_enqueue_payload_unchanged(enqueued, kwargs):
    from autonomous.taskrunner.autotasks import TaskPriority

    assert db_sync.request_indexing("abc", "lore", **kwargs) is True
    (func, args, kw), = enqueued
    assert func is db_sync.process_single_object_sync
    assert args == ()
    assert set(kw) == DEFAULT_KEYS
    assert kw["object_id"] == "abc" and kw["collection_name"] == "lore"
    assert kw["priority"] is TaskPriority.LOW


def test_debounce_false_is_forwarded(enqueued):
    assert db_sync.request_indexing("abc", "lore", debounce=False) is True
    (_, _, kw), = enqueued
    assert set(kw) == DEFAULT_KEYS | {"debounce"}
    assert kw["debounce"] is False


def test_forwarded_payload_is_accepted_by_worker(enqueued, worker):
    # The enqueued kwargs (minus the queue selector AutoTasks.task pops)
    # must be a valid call of the worker, end to end.
    worker[0].get.return_value = None
    db_sync.request_indexing("abc", "lore", debounce=False)
    (func, _, kw), = enqueued
    kw = {k: v for k, v in kw.items() if k != "priority"}
    func(**kw)
    assert worker[2] == []
    assert len(worker[3]) == 1
