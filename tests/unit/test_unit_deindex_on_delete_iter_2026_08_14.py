"""Independent test-agent coverage for PR #206 (#204, #205) and the
test-side fix for #210.

Three related changes to the vector-index lifecycle:

- ``db_sync.deindex(pk)`` — new public inverse of ``request_indexing``.
  Best-effort by contract: it must never raise, because its caller is
  mid-delete and the Mongo document is already gone.
- ``AutoModel.delete()`` calls it unconditionally, with the pk captured
  **before** ``super().delete()`` runs.
- ``process_single_object_sync``'s not-found self-heal deleted
  ``<collection>:<pk>`` — a prefix no writer ever produced — so it
  cleaned nothing. Both sites now route through ``_index_key``.

Plus the #210 fix that landed on this branch: the worker re-checks the
document's existence immediately before its ``hset``, so a delete that
lands during ``get_vector()``'s multi-second HTTP call no longer
resurrects the vector permanently.

Written from the PR diff alone; dev's ``tests/_dev_local/`` is
gitignored and absent from the diff. What this file pins, beyond
restating the diff:

- **The key prefix is the whole bug in #204.** Asserting "delete was
  called" would have passed against the broken code too — the tests
  assert the exact key string, and assert the old ``<collection>:<pk>``
  form is NOT what goes out.
- **Fail-soft is a contract, not an implementation detail.** Every
  failure mode a real deployment produces (Redis down, socket timeout,
  the ``redis`` package absent because ``[tasks]`` was not installed)
  must return ``False``, not propagate. A regression here turns every
  delete in a Redis-less install into an exception.
- **pk capture ordering.** ``super().delete()`` fires ``post_delete``
  to arbitrary consumer receivers that may mutate the document. Reading
  ``self.pk`` after the delete would de-index the wrong key — or
  ``None`` — depending on what the consumer's receiver did.
- **The #210 re-check has to sit after ``get_vector``.** Hoisting it
  above the embedding call would restore the whole race while leaving
  every "does it skip a deleted doc" test green, so the ordering is
  pinned explicitly.

Hermetic: no Redis, no Mongo, no numpy (CI's unit leg installs neither
numpy nor a live Redis — the ``if vector:`` branch's lazy ``import
numpy`` is stubbed the same way the #132 coverage does it).
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from bson.objectid import ObjectId

from autonomous.db import db_sync
from autonomous.db.db_sync import _index_key, deindex


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _StubNpArray:
    def __init__(self, values, dtype=None):
        self.values = values

    def tobytes(self):
        return b"stub-vector-bytes"


class _StubNumpy:
    """Minimal stand-in for the lazy ``import numpy`` inside the
    ``if vector:`` branch. numpy is NOT installed on CI's unit leg, so
    any test reaching the write path must inject this or it passes
    locally and errors in CI."""

    float32 = object()

    @staticmethod
    def array(values, dtype=None):
        return _StubNpArray(values, dtype=dtype)


class _RedisStub:
    """Records what the code under test asked Redis to do."""

    def __init__(self, *, get_returns="tok", delete_raises=None):
        self._get_returns = get_returns
        self._delete_raises = delete_raises
        self.delete_calls = []
        self.hset_calls = []

    def get(self, key):
        return self._get_returns

    def delete(self, key):
        self.delete_calls.append(key)
        if self._delete_raises is not None:
            raise self._delete_raises
        return 1

    def hset(self, key, mapping=None):
        self.hset_calls.append({"key": key, "mapping": mapping})


class _CollectionStub:
    """``find_one`` returns each queued doc in turn, so a test can say
    "present on the first lookup, gone on the second"."""

    def __init__(self, docs, on_call=None):
        self._docs = list(docs)
        self._on_call = on_call
        self.calls = []

    def find_one(self, query, projection=None):
        self.calls.append((query, projection))
        if self._on_call is not None:
            self._on_call()
        return self._docs.pop(0) if self._docs else None


class _MongoDbStub:
    def __init__(self, collection):
        self._collection = collection
        self.subscript_calls = []

    def __getitem__(self, key):
        self.subscript_calls.append(key)
        return self._collection


DOC = {
    "_id": "lore_x",
    "name": "a name long enough to clear MIN_CONTENT_CHARS",
    "history": "",
    "associations": [],
    "world": None,
}


@pytest.fixture
def worker_stubs(monkeypatch):
    """Wire ``process_single_object_sync``'s dependency seams. Returns a
    builder so each test chooses the doc sequence find_one replays."""

    def _build(docs, *, vector=(0.1, 0.2, 0.3), on_find=None):
        monkeypatch.setitem(sys.modules, "numpy", _StubNumpy())
        redis = _RedisStub()
        collection = _CollectionStub(docs, on_call=on_find)
        mongo = _MongoDbStub(collection)
        events = []

        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)
        monkeypatch.setattr(db_sync, "_get_mongo_db", lambda: mongo)
        monkeypatch.setattr(db_sync.time, "sleep", lambda _: None)
        monkeypatch.setattr(
            db_sync, "record_embedding_sync_event", lambda ev: events.append(ev)
        )
        monkeypatch.setattr(db_sync, "get_vector", lambda _: list(vector) if vector else None)
        return redis, collection, mongo, events

    return _build


# ---------------------------------------------------------------------------
# 1. _index_key — the shape the whole #204 bug was about
# ---------------------------------------------------------------------------


class TestIndexKeyShape:
    def test_prefix_is_lore(self):
        # The writer has always produced ``lore:<pk>``; the self-heal
        # used ``<collection>:<pk>``. Anything but this literal breaks
        # one of the two sites.
        assert _index_key("abc") == "lore:abc"

    def test_objectid_is_stringified(self):
        # pks arrive as ObjectId from AutoModel.delete and as str from
        # the worker; both must land on the same key.
        oid = ObjectId()
        assert _index_key(oid) == f"lore:{oid}"

    def test_deindex_takes_no_collection_argument(self):
        # Structural guard on the fix: the key shape does not depend on
        # the collection, so ``deindex`` must not accept one. A future
        # ``deindex(pk, collection)`` is how ``<collection>:<pk>`` would
        # creep back in.
        import inspect

        params = list(inspect.signature(deindex).parameters)
        assert params == ["object_id"], (
            f"deindex must take the pk alone; got {params!r}"
        )


# ---------------------------------------------------------------------------
# 2. deindex — best-effort contract
# ---------------------------------------------------------------------------


class TestDeindexHappyPath:
    def test_deletes_the_lore_key_and_returns_true(self, monkeypatch):
        redis = _RedisStub()
        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)

        assert deindex("abc") is True
        assert redis.delete_calls == ["lore:abc"]

    def test_does_not_use_the_collection_prefixed_key(self, monkeypatch):
        # Explicit anti-assertion for the #204 shape — "delete was
        # called" alone would have passed against the broken code.
        redis = _RedisStub()
        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)

        deindex("abc")

        assert not any(":abc" in k and not k.startswith("lore:") for k in redis.delete_calls)

    def test_missing_key_still_returns_true(self, monkeypatch):
        # Redis DEL on an absent key returns 0, which is not a failure:
        # "already gone" is the state the caller wanted.
        redis = _RedisStub()
        redis.delete = lambda key: 0
        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)

        assert deindex("never-indexed") is True


class TestDeindexFailSoft:
    @pytest.mark.parametrize(
        "exc",
        [
            ConnectionError("connection refused"),
            TimeoutError("socket timeout"),
            RuntimeError("some redis-py internal"),
        ],
    )
    def test_unreachable_redis_returns_false_without_raising(self, monkeypatch, exc):
        # The caller is mid-delete: the Mongo document is already gone,
        # so an unreachable Redis must not turn a successful delete into
        # an exception.
        redis = _RedisStub(delete_raises=exc)
        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)

        assert deindex("abc") is False

    def test_failure_names_the_key_in_the_log(self, monkeypatch):
        # A False return leaks that hash permanently and nothing
        # revisits it — the log line is the only breadcrumb an operator
        # has to sweep it later, so it has to carry the key.
        logged = []
        monkeypatch.setattr(db_sync, "log", lambda msg, *a, **kw: logged.append(str(msg)))
        monkeypatch.setattr(
            db_sync, "_get_redis", lambda: _RedisStub(delete_raises=ConnectionError("x"))
        )

        deindex("abc")

        assert any("lore:abc" in m for m in logged), (
            f"de-index failure MUST log the key; got {logged!r}"
        )
        # Bare ``log()`` emits at DEBUG and the default LOG_LEVEL is
        # WARNING, so without the module's ``[WARNING]`` text prefix
        # (the same convention record_embedding_sync_event and
        # _extract_world_pk use) the permanent-leak condition produces
        # no operator-visible signal at all.
        assert any("[WARNING]" in m for m in logged), (
            f"the permanent-leak condition MUST be greppable; got {logged!r}"
        )

    def test_uses_log_not_print(self, monkeypatch):
        # Deliberate in the diff: base installs without the [tasks]
        # extra fail on EVERY delete, and print would spam stdout past
        # LOG_LEVEL for all of them.
        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **kw: printed.append(a))
        monkeypatch.setattr(db_sync, "log", lambda *a, **kw: None)
        monkeypatch.setattr(
            db_sync, "_get_redis", lambda: _RedisStub(delete_raises=ConnectionError("x"))
        )

        deindex("abc")

        assert printed == [], f"de-index failure must not print; got {printed!r}"

    def test_missing_redis_package_returns_false(self, monkeypatch):
        # redis lives in the [tasks] extra. An ORM-only consumer has no
        # redis installed at all, and every delete they issue reaches
        # this path — it must degrade, not explode.
        monkeypatch.setattr(db_sync, "_redis_client", None)
        monkeypatch.setitem(sys.modules, "redis", None)  # `import redis` → ImportError
        monkeypatch.setattr(db_sync, "log", lambda *a, **kw: None)

        assert deindex("abc") is False

    def test_connection_construction_failure_returns_false(self, monkeypatch):
        # The failure can also come from building the client rather
        # than from the DEL itself (bad host, DNS failure).
        monkeypatch.setattr(db_sync, "log", lambda *a, **kw: None)
        monkeypatch.setattr(
            db_sync,
            "_get_redis",
            lambda: (_ for _ in ()).throw(OSError("name resolution failed")),
        )

        assert deindex("abc") is False


# ---------------------------------------------------------------------------
# 3. The self-heal branch (#204) — worker side of the same key bug
# ---------------------------------------------------------------------------


class TestSelfHealKeyPrefix:
    def test_not_found_branch_deletes_the_lore_key(self, worker_stubs):
        # Pre-fix this deleted ``lore_arbitrary:abc`` and the real
        # ``lore:abc`` hash survived, so the self-heal silently cleaned
        # nothing.
        redis, _, _, _ = worker_stubs([None])

        db_sync.process_single_object_sync("abc", "lore_arbitrary", "tok")

        assert redis.delete_calls == ["lore:abc"]

    def test_not_found_branch_never_uses_the_collection_prefix(self, worker_stubs):
        redis, _, _, _ = worker_stubs([None])

        db_sync.process_single_object_sync("abc", "characters", "tok")

        assert "characters:abc" not in redis.delete_calls

    def test_self_heal_writes_no_hash(self, worker_stubs):
        # The not-found branch returns immediately; a hash write here
        # would re-create what it just deleted.
        redis, _, _, _ = worker_stubs([None])

        db_sync.process_single_object_sync("abc", "lore", "tok")

        assert redis.hset_calls == []


# ---------------------------------------------------------------------------
# 4. AutoModel.delete() → deindex (#205)
# ---------------------------------------------------------------------------


@pytest.fixture
def delete_probe(monkeypatch):
    """A real ``AutoModel`` subclass with the ORM's own ``delete``
    replaced by a spy.

    A real subclass (not a hollow stub) because ``AutoModel.delete``
    calls zero-arg ``super()``, which requires an actual instance.
    ``Document.delete`` is the next ``delete`` in the MRO, so patching
    it there intercepts the ORM write without a live Mongo.
    """
    from autonomous.db import Document
    from autonomous.model import automodel as am

    class _DeindexProbeDoc(am.AutoModel):
        pass

    order = []
    deindexed = []

    def _super_delete(self, *args, **kwargs):
        order.append("mongo-delete")

    monkeypatch.setattr(Document, "delete", _super_delete)
    monkeypatch.setattr(
        am.db_sync,
        "deindex",
        lambda pk: (order.append("deindex"), deindexed.append(pk), True)[-1],
    )

    with patch.object(am, "_ensure_connected") as ensure:
        yield _DeindexProbeDoc, order, deindexed, ensure


class TestAutoModelDeleteDeindexes:
    def test_delete_deindexes_the_pk(self, delete_probe):
        cls, _, deindexed, _ = delete_probe
        obj = cls()
        obj.pk = "abc123"

        obj.delete()

        assert deindexed == ["abc123"]

    def test_deindex_runs_after_the_mongo_delete(self, delete_probe):
        # Mongo is the source of truth: de-indexing first would drop the
        # vector for a document whose delete then failed, leaving it
        # alive but unsearchable.
        cls, order, _, _ = delete_probe
        obj = cls()
        obj.pk = "abc123"

        obj.delete()

        assert order == ["mongo-delete", "deindex"]

    def test_pk_is_captured_before_the_mongo_delete(self, delete_probe):
        # ``super().delete()`` sends post_delete to arbitrary consumer
        # receivers, which are free to mutate the document. Reading
        # self.pk afterwards would de-index whatever they left behind.
        cls, order, deindexed, _ = delete_probe
        obj = cls()
        obj.pk = "abc123"

        from autonomous.db import Document

        def _mutating_delete(self, *args, **kwargs):
            order.append("mongo-delete")
            self.pk = None

        with patch.object(Document, "delete", _mutating_delete):
            obj.delete()

        assert deindexed == ["abc123"], (
            "pk must be read BEFORE super().delete(); a post_delete "
            "receiver that clears it would otherwise de-index nothing"
        )

    def test_unsaved_document_skips_deindex(self, delete_probe):
        # A never-saved document has no pk and therefore no index
        # entry; de-indexing would issue a pointless ``DEL lore:None``
        # — and on a busy Redis, one per delete.
        cls, order, deindexed, _ = delete_probe
        obj = cls()
        assert obj.pk is None

        obj.delete()

        assert deindexed == []
        assert order == ["mongo-delete"], (
            "the Mongo delete must still run for a pk-less document"
        )

    def test_delete_succeeds_when_deindex_reports_failure(self, delete_probe):
        # deindex returning False (Redis unreachable) is a leaked hash,
        # not a failed delete. The caller must not see an exception.
        cls, order, _, _ = delete_probe
        from autonomous.model import automodel as am

        with patch.object(am.db_sync, "deindex", return_value=False):
            obj = cls()
            obj.pk = "abc123"
            obj.delete()

        assert order == ["mongo-delete"]

    def test_delete_still_ensures_the_connection(self, delete_probe):
        # The lazy-connect discipline predates this change and must
        # survive it.
        cls, _, _, ensure = delete_probe
        obj = cls()
        obj.pk = "abc123"

        obj.delete()

        assert ensure.called

    def test_deindex_is_unconditional_no_opt_in_flag(self, delete_probe):
        # Documented as deliberate: unlike ``save(sync=True)`` there is
        # no flag, because the code deleting an object is rarely the
        # code that indexed it. A new keyword-only ``sync=`` default
        # would silently restore the leak for every existing caller.
        #
        # Originally spelled ``params == ["self"]``, which pinned far
        # more than that intent: it also froze the *narrowing* of
        # ``Document.delete(signal_kwargs=None, **write_concern)`` that
        # shipped alongside it, and so blocked the #213 fix. Restated as
        # the intent itself — plus, below, the base-class compatibility
        # the exact-list form was accidentally forbidding.
        import inspect
        from autonomous.model import automodel as am

        params = list(inspect.signature(am.AutoModel.delete).parameters)
        assert "sync" not in params, (
            f"delete() must take no opt-in de-index flag; got {params!r}"
        )

    def test_signature_stays_compatible_with_document_delete(self, delete_probe):
        # An override may widen a base signature, never narrow one. The
        # funnel's skip/limit/signal branch splats a write-concern dict
        # into ``doc.delete(**write_concern)``, so a narrowed override
        # raises TypeError for a caller who never named this method
        # (#213). Binding rather than list-comparison, so the override
        # stays free to add parameters of its own.
        import inspect
        from autonomous.db import Document
        from autonomous.model import automodel as am

        probe = object()
        inspect.signature(Document.delete).bind(probe, signal_kwargs={"a": 1}, w=1)
        inspect.signature(am.AutoModel.delete).bind(
            probe, signal_kwargs={"a": 1}, w=1
        )


# ---------------------------------------------------------------------------
# 5. Shared Redis client — socket timeouts
# ---------------------------------------------------------------------------


@pytest.fixture
def redis_ctor_kwargs(monkeypatch):
    """Capture the kwargs ``_get_redis`` constructs its client with.

    Patches ``redis.Redis`` on the real package rather than swapping the
    whole module out: the constructor is handed a real ``Retry`` object,
    and asserting on a stand-in would prove nothing about the policy the
    shipped client actually gets.
    """
    redis = pytest.importorskip("redis")
    captured = []

    class _FakeRedis:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(redis, "Redis", _FakeRedis)
    monkeypatch.setattr(db_sync, "_redis_client", None)
    return captured


class TestRedisSocketTimeouts:
    def test_both_timeouts_default_to_two_seconds(self, redis_ctor_kwargs, monkeypatch):
        # Without these, redis-py blocks indefinitely on a host that
        # resolves but blackholes — and ``AutoModel.delete()`` now
        # touches Redis on every single call.
        monkeypatch.delenv("REDIS_SOCKET_TIMEOUT_SECONDS", raising=False)

        db_sync._get_redis()

        kwargs = redis_ctor_kwargs[0]
        assert kwargs["socket_connect_timeout"] == 2
        assert kwargs["socket_timeout"] == 2

    def test_env_var_overrides_both(self, redis_ctor_kwargs, monkeypatch):
        monkeypatch.setenv("REDIS_SOCKET_TIMEOUT_SECONDS", "7")

        db_sync._get_redis()

        kwargs = redis_ctor_kwargs[0]
        assert kwargs["socket_connect_timeout"] == 7
        assert kwargs["socket_timeout"] == 7

    def test_unparseable_env_falls_back_to_the_default(
        self, redis_ctor_kwargs, monkeypatch
    ):
        # Routed through the ``config.env_*`` guard, which never raises.
        # A bare ``float(os.environ[...])`` here would take down every
        # delete in a deployment with a typoed value.
        monkeypatch.setenv("REDIS_SOCKET_TIMEOUT_SECONDS", "two")
        monkeypatch.setattr(db_sync, "log", lambda *a, **kw: None)

        db_sync._get_redis()

        assert redis_ctor_kwargs[0]["socket_timeout"] == 2

    def test_sub_second_values_are_honored(self, redis_ctor_kwargs, monkeypatch):
        # The natural tuning direction for a DEL on the request path is
        # below a second; an int-only parse would silently floor 0.5 to
        # 0, which is the non-blocking-socket footgun below.
        monkeypatch.setenv("REDIS_SOCKET_TIMEOUT_SECONDS", "0.5")

        db_sync._get_redis()

        assert redis_ctor_kwargs[0]["socket_timeout"] == 0.5

    @pytest.mark.parametrize("bad", ["0", "-1"])
    def test_non_positive_values_are_refused(
        self, redis_ctor_kwargs, monkeypatch, bad
    ):
        # redis-py hands the value to ``socket.settimeout``: 0 puts the
        # socket in non-blocking mode, so every command fails, and a
        # negative raises ValueError inside the worker. "0" is the
        # conventional spelling for "no timeout", which makes accepting
        # it a config trap rather than a feature.
        logged = []
        monkeypatch.setenv("REDIS_SOCKET_TIMEOUT_SECONDS", bad)
        monkeypatch.setattr(db_sync, "log", lambda msg, *a, **kw: logged.append(str(msg)))

        db_sync._get_redis()

        assert redis_ctor_kwargs[0]["socket_timeout"] == 2.0
        assert redis_ctor_kwargs[0]["socket_connect_timeout"] == 2.0
        assert any("REDIS_SOCKET_TIMEOUT_SECONDS" in m and "WARNING" in m for m in logged), (
            f"a refused timeout value MUST be logged; got {logged!r}"
        )

    def test_retry_policy_is_disabled(self, redis_ctor_kwargs, monkeypatch):
        # The timeouts alone do NOT bound the call. redis-py's default
        # is 3 retries with exponential-plus-jitter backoff, which
        # multiplies the timeout by four and adds seconds of sleeping on
        # top: measured 4.9s for one DEL against a refused Redis, versus
        # 0.0s with the retries off. Since AutoModel.delete() now hits
        # Redis on every call and request_indexing writes its token on
        # the request path, the retry policy is the difference between
        # the documented 2s bound and a ~15s worst case.
        monkeypatch.delenv("REDIS_SOCKET_TIMEOUT_SECONDS", raising=False)

        db_sync._get_redis()

        retry = redis_ctor_kwargs[0]["retry"]
        assert retry.get_retries() == 0, (
            "redis-py's default 3-retry policy must be disabled, or the "
            "socket timeouts do not bound the call"
        )
        assert retry._backoff.compute(1) == 0

    def test_decode_responses_still_set(self, redis_ctor_kwargs, monkeypatch):
        # The supersede guard compares a str token against r.get(); if
        # the timeout addition had displaced this flag, every job would
        # read as superseded.
        monkeypatch.delenv("REDIS_SOCKET_TIMEOUT_SECONDS", raising=False)

        db_sync._get_redis()

        assert redis_ctor_kwargs[0]["decode_responses"] is True


# ---------------------------------------------------------------------------
# 6. #210 — a delete during the embedding call must not resurrect
# ---------------------------------------------------------------------------


class TestDeleteDuringEmbedding:
    def test_hash_not_written_when_the_doc_vanished(self, worker_stubs):
        # The race: find_one sees the doc, get_vector spends seconds on
        # HTTP, the delete lands (issuing its own DEL), and the worker's
        # hset then puts the vector back forever — nothing re-enqueues
        # an index job for a deleted pk.
        redis, _, _, _ = worker_stubs([DOC, None])

        db_sync.process_single_object_sync("lore_x", "lore", "tok")

        assert redis.hset_calls == [], (
            "a document deleted during embedding MUST NOT be written "
            "back to the index"
        )

    def test_skipped_write_is_not_counted_as_a_success(self, worker_stubs):
        # ``success`` drives storyteller's /debug/lore/health; counting
        # a skipped write would hide the race rather than close it.
        _, _, _, events = worker_stubs([DOC, None])

        db_sync.process_single_object_sync("lore_x", "lore", "tok")

        assert "success" not in events

    def test_recheck_uses_an_id_only_projection(self, worker_stubs):
        # Existence is all the re-check needs; pulling the whole
        # document back would add real cost to every indexed object.
        _, collection, _, _ = worker_stubs([DOC, DOC])

        db_sync.process_single_object_sync("lore_x", "lore", "tok")

        assert len(collection.calls) == 2, (
            f"expected the initial fetch plus one re-check; got {collection.calls!r}"
        )
        query, projection = collection.calls[1]
        assert projection == {"_id": 1}
        assert query == collection.calls[0][0], (
            "the re-check must reuse the same filter as the original "
            "lookup, or the two can drift apart"
        )

    def test_surviving_doc_is_still_indexed(self, worker_stubs):
        # The control: the re-check must not break the normal path.
        redis, _, _, events = worker_stubs([DOC, DOC])

        db_sync.process_single_object_sync("lore_x", "lore", "tok")

        assert len(redis.hset_calls) == 1
        assert redis.hset_calls[0]["key"] == "lore:lore_x"
        assert events == ["success"]

    def test_recheck_happens_after_the_embedding_call(self, monkeypatch):
        # Load-bearing ordering: hoisting the re-check above
        # ``get_vector`` would leave every other test in this class
        # green while restoring the entire race — the whole window IS
        # the embedding call.
        monkeypatch.setitem(sys.modules, "numpy", _StubNumpy())
        order = []
        redis = _RedisStub()
        collection = _CollectionStub([DOC, DOC], on_call=lambda: order.append("find_one"))
        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)
        monkeypatch.setattr(db_sync, "_get_mongo_db", lambda: _MongoDbStub(collection))
        monkeypatch.setattr(db_sync.time, "sleep", lambda _: None)
        monkeypatch.setattr(db_sync, "record_embedding_sync_event", lambda ev: None)

        def _get_vector(_):
            order.append("get_vector")
            return [0.1, 0.2]

        monkeypatch.setattr(db_sync, "get_vector", _get_vector)

        db_sync.process_single_object_sync("lore_x", "lore", "tok")

        assert order == ["find_one", "get_vector", "find_one"], (
            f"the existence re-check must follow get_vector; got {order!r}"
        )

    def test_no_recheck_when_the_embedding_failed(self, worker_stubs):
        # ``get_vector`` returning None skips the write block entirely,
        # so the re-check must not fire — it would be a pure cost with
        # nothing to guard.
        _, collection, _, _ = worker_stubs([DOC], vector=None)

        db_sync.process_single_object_sync("lore_x", "lore", "tok")

        assert len(collection.calls) == 1
