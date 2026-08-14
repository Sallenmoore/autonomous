"""Independent tests for PR #222 — #220's write-side vector_index enforcement.

Written from the PR diff (two-perspective contract). The diff's claims:

1. **The load-bearing gate is at enqueue, instance-accurate.**
   ``request_indexing`` reads the document's stored ``_cls`` with a
   projected point-read — in the calling process, where the registry
   is populated — and refuses only on an exact registry hit that opts
   out. Everything unresolvable (absent doc/_cls, unimported class,
   gate error) fails OPEN: refusing on a guess could silently
   un-index a live document.
2. **The worker re-check is defense-in-depth, exact-lookup only.** A
   stale ``_cls`` must never resolve through the fuzzy suffix fallback
   into a same-named class and drive the stale-hash delete off a
   guess; unresolvable ``_cls`` (bare rq worker, empty registry)
   prints a breadcrumb and indexes — the fail-open default.
3. **``request_indexing`` never raises after the Mongo commit.** Any
   failure logs at [WARNING], returns False, and best-effort removes
   the just-set token so an in-flight predecessor job doesn't skip
   itself as "superseded" by a job that never enqueued.
"""

import sys

import pytest

from autonomous.db import db_sync
from autonomous.db.base.common import _document_registry

# ---------------------------------------------------------------------------
# Stubs — hand-rolled, never MagicMock; unique class names (the registry
# and AutoModel.__subclasses__ are process-global).
# ---------------------------------------------------------------------------


class _WsgNpArray:
    def __init__(self, values, dtype=None):
        self.values = values

    def tobytes(self):
        return b"stub-vector-bytes"


class _WsgNumpy:
    float32 = object()

    @staticmethod
    def array(values, dtype=None):
        return _WsgNpArray(values, dtype=dtype)


class _WsgRedis:
    def __init__(self, *, dead=False):
        self.dead = dead
        self.sets = []
        self.deletes = []
        self.hsets = []

    def get(self, key):
        return "tok"

    def set(self, key, value, ex=None):
        if self.dead:
            raise ConnectionError("redis down")
        self.sets.append((key, value, ex))

    def delete(self, key):
        if self.dead:
            raise ConnectionError("redis down")
        self.deletes.append(key)
        return 1

    def hset(self, key, mapping=None):
        self.hsets.append({"key": key, "mapping": mapping})


class _WsgCollection:
    def __init__(self, docs):
        self._docs = list(docs)

    def find_one(self, query, projection=None):
        return self._docs.pop(0) if self._docs else None


class _WsgMongo:
    def __init__(self, collection):
        self._collection = collection

    def __getitem__(self, key):
        return self._collection


class _WsgTaskRunner:
    tasks = []
    raise_on_task = False

    def task(self, *a, **kw):
        if _WsgTaskRunner.raise_on_task:
            raise ConnectionError("enqueue blip")
        _WsgTaskRunner.tasks.append((a, kw))


class _WsgOptOutA:
    _meta = {"vector_index": False, "collection": "wsg_world"}


class _WsgOptOutB:
    _meta = {"vector_index": False, "collection": "wsg_world"}


class _WsgIndexed:
    _meta = {"collection": "wsg_world"}


def _doc(**extra):
    return {
        "_id": "wsg_pk",
        "name": "a name long enough to clear MIN_CONTENT_CHARS",
        "history": "",
        "associations": [],
        "world": None,
        **extra,
    }


@pytest.fixture
def enqueue(monkeypatch):
    """Wire request_indexing's seams. Returns (redis, taskrunner,
    warnings, events, state); ``state["doc"]`` is what the gate's
    projected point-read finds (None = document absent)."""
    import autonomous.taskrunner.autotasks as at

    _WsgTaskRunner.tasks = []
    _WsgTaskRunner.raise_on_task = False
    monkeypatch.setattr(at, "AutoTasks", _WsgTaskRunner)
    warnings = []
    monkeypatch.setattr(
        db_sync, "log", lambda m, *a, **kw: warnings.append(str(m))
    )
    events = []
    monkeypatch.setattr(
        db_sync, "record_embedding_sync_event", lambda ev: events.append(ev)
    )
    redis = _WsgRedis()
    monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)

    state = {"doc": None, "raise_on_find": False}

    class _GateCollection:
        def find_one(self, query, projection=None):
            if state["raise_on_find"]:
                raise RuntimeError("mongo hiccup in the gate")
            assert projection == {"_cls": 1}, (
                "the gate's read must stay a projected point-read"
            )
            return state["doc"]

    monkeypatch.setattr(
        db_sync, "_get_mongo_db", lambda: _WsgMongo(_GateCollection())
    )
    return redis, _WsgTaskRunner, warnings, events, state


@pytest.fixture
def worker(monkeypatch):
    def _build(docs):
        monkeypatch.setitem(sys.modules, "numpy", _WsgNumpy())
        redis = _WsgRedis()
        mongo = _WsgMongo(_WsgCollection(docs))
        events = []
        vector_calls = []
        prints = []

        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)
        monkeypatch.setattr(db_sync, "_get_mongo_db", lambda: mongo)
        monkeypatch.setattr(db_sync.time, "sleep", lambda _: None)
        monkeypatch.setattr(
            db_sync, "record_embedding_sync_event", lambda ev: events.append(ev)
        )
        monkeypatch.setattr(
            db_sync,
            "get_vector",
            lambda text: (vector_calls.append(text), [0.1, 0.2])[-1],
        )
        monkeypatch.setattr(
            "builtins.print", lambda *a, **kw: prints.append(" ".join(map(str, a)))
        )
        return redis, events, vector_calls, prints

    return _build


# ===========================================================================
# 1. The enqueue gate — where the registry lives
# ===========================================================================


class TestEnqueueGate:
    def test_opted_out_document_is_refused_logged_and_counted(
        self, enqueue, monkeypatch
    ):
        monkeypatch.setitem(_document_registry, "_WsgOptOutA", _WsgOptOutA)
        redis, runner, warnings, events, state = enqueue
        state["doc"] = {"_cls": "_WsgOptOutA"}

        assert db_sync.request_indexing("wsg_pk", "wsg_world") is False
        assert redis.sets == [], "no token for a request that won't enqueue"
        assert runner.tasks == []
        assert any("vector_index: False" in w for w in warnings), (
            "a bulk skip must be visible in the log, not just stdout"
        )
        assert events == ["silent_skip"], (
            "the health hash must see the skip volume this gate absorbs"
        )

    def test_indexed_document_proceeds(self, enqueue, monkeypatch):
        monkeypatch.setitem(_document_registry, "_WsgIndexed", _WsgIndexed)
        redis, runner, _, _, state = enqueue
        state["doc"] = {"_cls": "_WsgIndexed"}

        assert db_sync.request_indexing("wsg_pk", "wsg_world") is True
        assert len(runner.tasks) == 1

    def test_partial_registry_fails_open(self, enqueue, monkeypatch):
        # THE review scenario: a bulk-reindex process imported only the
        # opted-out base, but this document belongs to an indexed child
        # that process never imported. Refusing would silently un-index
        # live documents — the gate must enqueue.
        monkeypatch.setitem(_document_registry, "_WsgOptOutA", _WsgOptOutA)
        _, runner, _, _, state = enqueue
        state["doc"] = {"_cls": "_WsgIndexedChildNotImported"}

        assert db_sync.request_indexing("wsg_pk", "wsg_world") is True
        assert len(runner.tasks) == 1

    def test_absent_document_fails_open(self, enqueue):
        _, runner, _, _, state = enqueue
        state["doc"] = None  # worker's not-found branch owns cleanup

        assert db_sync.request_indexing("wsg_pk", "wsg_world") is True
        assert len(runner.tasks) == 1

    def test_document_without_cls_fails_open(self, enqueue, monkeypatch):
        # allow_inheritance: False models store no _cls; unknowable at
        # enqueue AND in the worker — the documented sweep backstop.
        monkeypatch.setitem(_document_registry, "_WsgOptOutA", _WsgOptOutA)
        _, runner, _, _, state = enqueue
        state["doc"] = {}

        assert db_sync.request_indexing("wsg_pk", "wsg_world") is True
        assert len(runner.tasks) == 1

    def test_gate_error_fails_open_with_warning(self, enqueue):
        # A gate that raises through save(sync=True) after the Mongo
        # commit, or whose error reads as "skip", would be worse than
        # no gate. It must enqueue and warn.
        redis, runner, warnings, _, state = enqueue
        state["raise_on_find"] = True

        assert db_sync.request_indexing("wsg_pk", "wsg_world") is True
        assert len(runner.tasks) == 1
        assert any("indexing anyway" in w for w in warnings)

    def test_resolver_directly(self, enqueue, monkeypatch):
        monkeypatch.setitem(_document_registry, "_WsgOptOutA", _WsgOptOutA)
        _, _, _, _, state = enqueue
        state["doc"] = {"_cls": "_WsgOptOutA"}
        assert db_sync._requested_doc_vector_indexed("wsg_pk", "wsg_world") is False
        state["doc"] = {"_cls": "_WsgUnregistered"}
        assert db_sync._requested_doc_vector_indexed("wsg_pk", "wsg_world") is True


# ===========================================================================
# 2. request_indexing never raises post-commit
# ===========================================================================


class TestRequestIndexingNeverRaises:
    def test_redis_down_returns_false_and_logs_warning(self, enqueue, monkeypatch):
        redis, runner, warnings, _, _ = enqueue
        redis.dead = True

        assert db_sync.request_indexing("wsg_pk", "wsg_unknown_coll") is False
        assert runner.tasks == []
        assert any("[WARNING]" in w and "Sync request failed" in w for w in warnings), (
            "a bare print was the old sole signal; operators grep the log"
        )

    def test_failed_enqueue_removes_its_token(self, enqueue):
        # A live token with no job behind it makes an in-flight
        # predecessor job skip itself as 'superseded' (worker step 2).
        redis, runner, _, _, _ = enqueue
        runner.raise_on_task = True

        assert db_sync.request_indexing("wsg_pk", "wsg_unknown_coll") is False
        assert len(redis.sets) == 1
        assert redis.deletes == [redis.sets[0][0]]

    def test_cleanup_failure_is_also_swallowed(self, enqueue, monkeypatch):
        # Token lands, enqueue fails, and by then Redis has died too:
        # the cleanup's own failure must not resurrect the raise.
        redis, runner, _, _, _ = enqueue
        runner.raise_on_task = True

        original_set = redis.set

        def _set_then_die(key, value, ex=None):
            original_set(key, value, ex=ex)
            redis.dead = True  # everything after the set fails

        redis.set = _set_then_die

        assert db_sync.request_indexing("wsg_pk", "wsg_unknown_coll") is False

    def test_save_sync_does_not_raise_when_redis_is_down(self, enqueue, monkeypatch):
        # The consumer-visible contract: Mongo committed, so save must
        # return the pk normally; the failure lives in the log line.
        from autonomous.db import Document
        from autonomous.model import automodel as am

        class _WsgSaveProbe(am.AutoModel):
            pass

        redis, _, warnings, _, _ = enqueue
        redis.dead = True
        monkeypatch.setattr(Document, "save", lambda self, *a, **kw: None)

        from unittest.mock import patch

        with patch.object(am, "_ensure_connected"):
            obj = _WsgSaveProbe()
            obj.pk = "wsg_pk"
            assert obj.save(sync=True) == "wsg_pk"
        assert any("Sync request failed" in w for w in warnings)

    def test_ttl_zero_is_clamped(self, monkeypatch):
        monkeypatch.setenv("SYNC_TOKEN_TTL_SECONDS", "0")
        assert db_sync._sync_token_ttl_seconds() == 1

    def test_ttl_negative_is_clamped(self, monkeypatch):
        monkeypatch.setenv("SYNC_TOKEN_TTL_SECONDS", "-5")
        assert db_sync._sync_token_ttl_seconds() == 1

    def test_ttl_normal_passes_through(self, monkeypatch):
        monkeypatch.setenv("SYNC_TOKEN_TTL_SECONDS", "120")
        assert db_sync._sync_token_ttl_seconds() == 120


# ===========================================================================
# 3. The worker re-check — exact, fail-open, self-healing
# ===========================================================================


class TestWorkerRecheck:
    def test_opt_out_doc_skips_deletes_stale_hash_and_records(
        self, worker, monkeypatch
    ):
        doc = _doc(_cls="_WsgOptOutA")
        redis, events, vector_calls, prints = worker([doc, doc])
        monkeypatch.setitem(_document_registry, "_WsgOptOutA", _WsgOptOutA)

        db_sync.process_single_object_sync("wsg_pk", "wsg_world", "tok")

        assert redis.hsets == [], "no hash for an opted-out document"
        assert redis.deletes == [db_sync._index_key("wsg_pk")], (
            "the stale pre-flag hash must be dropped (best-effort deindex)"
        )
        assert events == ["silent_skip"]
        assert vector_calls == [], "no embedding HTTP work for a skip"
        assert any("vector_index: False" in p for p in prints)

    def test_exact_lookup_never_uses_fuzzy_fallback(self, worker, monkeypatch):
        # get_document('Stale._WsgChild') would suffix-match a registered
        # 'Live._WsgChild'; a policy gate driving a destructive delete
        # must not act on that guess — no exact hit means index.
        class _WsgNamesake:
            _meta = {"vector_index": False, "collection": "wsg_world"}

        doc = _doc(_cls="Stale._WsgChild")
        redis, events, _, _ = worker([doc, doc])
        monkeypatch.setitem(_document_registry, "Live._WsgChild", _WsgNamesake)

        db_sync.process_single_object_sync("wsg_pk", "wsg_world", "tok")

        assert len(redis.hsets) == 1, "no exact hit -> index"
        assert redis.deletes == [], "and, critically, no delete off a guess"

    def test_unregistered_cls_fails_open_with_breadcrumb(self, worker):
        doc = _doc(_cls="_WsgNeverImported")
        redis, events, _, prints = worker([doc, doc])

        db_sync.process_single_object_sync("wsg_pk", "wsg_world", "tok")

        assert len(redis.hsets) == 1, (
            "a bare rq worker's registry is empty; the check must fail "
            "open to the pre-#220 behavior"
        )
        assert any("not registered in this process" in p for p in prints), (
            "fail-open must leave a breadcrumb, not be silent"
        )

    def test_registered_indexed_model_writes_normally(self, worker, monkeypatch):
        doc = _doc(_cls="_WsgIndexed")
        redis, events, _, _ = worker([doc, doc])
        monkeypatch.setitem(_document_registry, "_WsgIndexed", _WsgIndexed)

        db_sync.process_single_object_sync("wsg_pk", "wsg_world", "tok")

        assert len(redis.hsets) == 1
        assert events == ["success"]

    def test_doc_without_cls_indexes_normally(self, worker):
        redis, events, _, _ = worker([_doc(), _doc()])

        db_sync.process_single_object_sync("wsg_pk", "wsg_world", "tok")

        assert len(redis.hsets) == 1


# ===========================================================================
# 4. The shared predicate
# ===========================================================================


class TestVectorIndexedPredicate:
    def test_default_is_true(self):
        class _WsgUndeclared:
            _meta = {}

        assert db_sync.vector_indexed(_WsgUndeclared) is True

    def test_false_is_honored(self):
        assert db_sync.vector_indexed(_WsgOptOutA) is False

    def test_explicit_true(self):
        class _WsgExplicit:
            _meta = {"vector_index": True}

        assert db_sync.vector_indexed(_WsgExplicit) is True
