"""Independent test-agent coverage for PR #214 (closes #207).

0.3.171 hooked de-indexing into ``AutoModel.delete()``, which sees only
the single-document path. PR #214 moves the coverage down to
``BaseQuerySet.delete()`` — the funnel bulk deletes, CASCADE children
and ``Document.delete()`` all converge on — by scanning the matched pks
before ``delete_many``, narrowing them to the ones Mongo provably
removed, and handing those to the new ``db_sync.deindex_many()``.

Written from the PR diff alone; dev's ``tests/_dev_local/`` is
gitignored and never appears in the diff. What this file pins beyond
restating the diff:

- **The surviving-document direction is the dangerous one.** ``find``
  and ``delete_many`` are two operations against one filter, so a
  document mutated out of the filter in between survives the delete
  while still sitting in the batch. De-indexing it leaves a *live*
  document permanently unreachable by KNN with nothing to restore it —
  unrecoverable, where the opposite direction (a leaked hash) is
  sweepable. Both branches that can produce a survivor are pinned: the
  ``deleted_count`` mismatch and the ``w=0`` case where that count
  carries no information at all.
- **Fail-soft is a contract, not an implementation detail.** The pk
  pre-scan is the only part of this cleanup that runs *before* the
  delete and therefore the only part that could stop one. Every failure
  seam — dead pre-scan cursor, dead confirmation cursor, unreachable
  Redis — must cost vector entries and never the delete itself.
- **Per-chunk isolation in ``deindex_many``.** Wrapping the loop instead
  of the chunk would look identical on every happy-path test and leak
  every key after the first blip. 0.3.171 disabled redis-py's retry
  policy, so a transient error raises immediately — exactly when
  finishing the batch matters.
- **The disjointness of the two hooks.** ``_from_doc_delete=True`` must
  skip the pre-scan (``AutoModel.delete`` already de-indexed that pk),
  while the CASCADE recursion must *not* inherit the flag or every
  child leaks again — which is the whole of #207.

Hermetic: no Mongo, no Redis, no numpy. The collection/queryset stubs
drive the real ``BaseQuerySet.delete`` and the real ``set_write_concern``
context manager; only Redis and Mongo I/O are stubbed.
"""

from __future__ import annotations

import pytest
from bson.objectid import ObjectId

from autonomous.db import db_sync
from autonomous.db.db_sync import _DEINDEX_CHUNK, _index_key, deindex_many
from autonomous.db.queryset import base as qs_base
from autonomous.db.queryset.base import (
    CASCADE,
    _PK_SCAN_CHUNK,
    BaseQuerySet,
    _confirm_deleted,
)


# ---------------------------------------------------------------------------
# Stubs — hand-rolled, never MagicMock. ``_skip``/``_limit`` must be
# explicit falsy values or ``call_document_delete`` routes past the code
# under test entirely (the trap PR #158's coverage documented).
# ---------------------------------------------------------------------------


class _DeleteResult:
    """Stand-in for pymongo's ``DeleteResult``."""

    def __init__(self, *, acknowledged=True, deleted_count=0):
        self.acknowledged = acknowledged
        self.deleted_count = deleted_count


class _WriteConcernStub:
    document = {}


class _CollectionStub:
    """Records the two distinct ``find`` shapes ``delete()`` issues.

    The pk pre-scan queries the caller's own filter; the confirmation
    re-check queries ``{"_id": {"$in": chunk}}``. Dispatching on the
    shape lets one stub serve both and lets a test say "these pks
    survived the delete" without the two calls interfering.
    """

    def __init__(
        self,
        pks=(),
        *,
        survivors=(),
        deleted_count=None,
        acknowledged=True,
        scan_raises=None,
        confirm_raises=None,
    ):
        self._pks = list(pks)
        self._survivors = set(survivors)
        self._acknowledged = acknowledged
        self._deleted_count = (
            len(self._pks) if deleted_count is None else deleted_count
        )
        self._scan_raises = scan_raises
        self._confirm_raises = confirm_raises
        self.scan_calls = []
        self.confirm_chunks = []
        self.delete_many_calls = []
        self.write_concerns = []
        self.write_concern = _WriteConcernStub()

    # -- pymongo surface -------------------------------------------------
    def find(self, query, projection=None):
        in_clause = (query or {}).get("_id")
        if isinstance(in_clause, dict) and "$in" in in_clause:
            chunk = list(in_clause["$in"])
            self.confirm_chunks.append(chunk)
            if self._confirm_raises is not None:
                raise self._confirm_raises
            return [{"_id": pk} for pk in chunk if pk in self._survivors]
        self.scan_calls.append((query, projection))
        if self._scan_raises is not None:
            raise self._scan_raises
        return [{"_id": pk} for pk in self._pks]

    def with_options(self, write_concern=None):
        self.write_concerns.append(write_concern)
        return self

    def delete_many(self, query):
        self.delete_many_calls.append(query)
        return _DeleteResult(
            acknowledged=self._acknowledged, deleted_count=self._deleted_count
        )


class _DocClass:
    def __init__(self, delete_rules=None):
        self._meta = {"delete_rules": delete_rules or {}}
        self._collection = "doc_collection"


class _QuerySetStub:
    """The ``self`` that ``BaseQuerySet.delete`` operates on."""

    def __init__(self, collection, doc, *, query=None, docs=()):
        self._collection = collection
        self._document = doc
        self._query = {"world": "w1"} if query is None else query
        self._skip = 0
        self._limit = 0
        self._docs = list(docs)

    def clone(self):
        return self

    def __iter__(self):
        return iter(self._docs)


class _RecursingRefs:
    """A CASCADE referrer queryset that really re-enters ``delete()``.

    A spy that only records the call would leave the interesting half
    untested: what proves #207 fixed is that the *recursion* reaches the
    de-index, and that ``_from_doc_delete`` is not forwarded into it.
    """

    def __init__(self, child_qs):
        self._child_qs = child_qs
        self.delete_kwargs = []

    def first(self):
        return object()  # "there is something to cascade through"

    def delete(self, **kwargs):
        self.delete_kwargs.append(kwargs)
        return BaseQuerySet.delete(self._child_qs, **kwargs)


class _RefsDocClass:
    _meta = {"abstract": False}
    _collection = "refs_collection"
    __name__ = "RefsDoc"

    def __init__(self, refs):
        self._refs = refs

    def objects(self, **filter_kwargs):
        return self._refs


class _RedisStub:
    def __init__(self, *, raise_on_chunk=()):
        self._raise_on_chunk = set(raise_on_chunk)
        self.delete_calls = []

    def delete(self, *keys):
        index = len(self.delete_calls)
        self.delete_calls.append(list(keys))
        if index in self._raise_on_chunk:
            raise ConnectionError(f"redis blip on chunk {index}")
        return len(keys)


@pytest.fixture(autouse=True)
def _no_signal_receivers(monkeypatch):
    """Receivers left registered by other tests would flip
    ``call_document_delete`` and route every test in this file down the
    per-document loop instead of the funnel under test."""
    from autonomous.db import signals as _signals

    monkeypatch.setattr(_signals.pre_delete, "has_receivers_for", lambda _s: False)
    monkeypatch.setattr(_signals.post_delete, "has_receivers_for", lambda _s: False)


@pytest.fixture
def deindexed(monkeypatch):
    """Capture what the funnel hands to ``db_sync.deindex_many``."""
    calls = []
    monkeypatch.setattr(
        db_sync, "deindex_many", lambda pks: (calls.append(list(pks)), True)[-1]
    )
    return calls


@pytest.fixture
def logged(monkeypatch):
    messages = []
    monkeypatch.setattr(qs_base, "log", lambda msg, *a, **kw: messages.append(str(msg)))
    return messages


# ===========================================================================
# 1. Bulk ``objects(...).delete()`` — the first path #207 left leaking
# ===========================================================================


class TestBulkDeleteDeindexes:
    def test_deindexes_exactly_the_deleted_pks(self, deindexed):
        pks = [ObjectId() for _ in range(3)]
        collection = _CollectionStub(pks)
        qs = _QuerySetStub(collection, _DocClass())

        assert BaseQuerySet.delete(qs) == 3
        assert deindexed == [pks], (
            "a bulk delete must de-index every pk it removed — pre-#214 "
            "it de-indexed none of them"
        )

    def test_prescan_is_projected_and_uses_the_delete_filter(self, deindexed):
        collection = _CollectionStub([ObjectId()])
        qs = _QuerySetStub(collection, _DocClass(), query={"world": "w9"})

        BaseQuerySet.delete(qs)

        assert len(collection.scan_calls) == 1
        query, projection = collection.scan_calls[0]
        assert query == {"world": "w9"}, (
            "the scan must reuse the delete's own filter, or it collects "
            "pks for documents the delete will not touch"
        )
        assert projection == {"_id": 1}, (
            "pulling whole documents back would put real cost on every "
            "bulk delete in the library"
        )

    def test_delete_many_fast_path_is_preserved(self, deindexed):
        pks = [ObjectId() for _ in range(5)]
        collection = _CollectionStub(pks)
        qs = _QuerySetStub(collection, _DocClass())

        BaseQuerySet.delete(qs)

        assert collection.delete_many_calls == [{"world": "w1"}], (
            "five documents must still cost one delete_many — a degrade "
            "to a per-document loop is the failure mode this design "
            "explicitly rejected"
        )

    def test_empty_match_deindexes_nothing(self, deindexed):
        collection = _CollectionStub([])
        qs = _QuerySetStub(collection, _DocClass())

        assert BaseQuerySet.delete(qs) == 0
        assert deindexed == [], (
            "a filter that matched nothing must not reach Redis at all"
        )

    def test_prescan_runs_before_the_delete(self, deindexed):
        # Ordering is the whole reason the pks are buffered: scanning
        # after delete_many finds nothing, and DELing before it strips
        # vectors off documents a failed delete leaves in place.
        order = []
        pks = [ObjectId()]

        class _OrderedCollection(_CollectionStub):
            def find(self, query, projection=None):
                if not (isinstance((query or {}).get("_id"), dict)):
                    order.append("scan")
                return super().find(query, projection)

            def delete_many(self, query):
                order.append("delete_many")
                return super().delete_many(query)

        collection = _OrderedCollection(pks)
        monkey_qs = _QuerySetStub(collection, _DocClass())

        BaseQuerySet.delete(monkey_qs)

        assert order == ["scan", "delete_many"]


# ===========================================================================
# 2. ``_from_doc_delete`` — the two hooks are disjoint, not redundant
# ===========================================================================


class TestSingleDocumentPathIsSkipped:
    def test_from_doc_delete_skips_the_scan_and_the_deindex(self, deindexed):
        # ``AutoModel.delete()`` already de-indexed the pk it holds;
        # re-scanning would add a Mongo round-trip to the most common
        # delete in the library for zero new coverage.
        collection = _CollectionStub([ObjectId()])
        qs = _QuerySetStub(collection, _DocClass())

        BaseQuerySet.delete(qs, _from_doc_delete=True)

        assert collection.scan_calls == []
        assert deindexed == []
        assert len(collection.delete_many_calls) == 1, (
            "skipping the cleanup must not skip the delete"
        )


# ===========================================================================
# 3. CASCADE children — the path that was invisible at the call site
# ===========================================================================


class TestCascadeChildrenDeindex:
    def _build(self, parent_pks, child_pks):
        child_collection = _CollectionStub(child_pks)
        child_qs = _QuerySetStub(
            child_collection, _DocClass(), query={"parent": "p1"}
        )
        refs = _RecursingRefs(child_qs)
        parent_collection = _CollectionStub(parent_pks)
        parent_qs = _QuerySetStub(
            parent_collection,
            _DocClass({(_RefsDocClass(refs), "parent"): CASCADE}),
        )
        return parent_qs, refs, parent_collection, child_collection

    def test_children_are_deindexed_with_the_parent(self, deindexed):
        parent_pks = [ObjectId()]
        child_pks = [ObjectId() for _ in range(4)]
        parent_qs, _, _, _ = self._build(parent_pks, child_pks)

        BaseQuerySet.delete(parent_qs)

        # Children first: the CASCADE recursion runs before the parent's
        # own delete_many.
        assert deindexed == [child_pks, parent_pks], (
            "pre-#214 a cascade de-indexed only the parent and leaked "
            "every child's embedding"
        )

    def test_cascade_recursion_does_not_inherit_from_doc_delete(self, deindexed):
        # If the flag were forwarded, children of a single
        # ``obj.delete()`` would skip the scan and leak — silently, since
        # nothing at the call site mentions the children at all.
        parent_qs, refs, _, _ = self._build([ObjectId()], [ObjectId()])

        BaseQuerySet.delete(parent_qs, _from_doc_delete=True)

        assert refs.delete_kwargs, "the CASCADE arm must still recurse"
        assert refs.delete_kwargs[0].get("_from_doc_delete") is None
        assert len(deindexed) == 1, (
            "the parent is de-indexed by AutoModel.delete on this path, "
            "but its children must still be de-indexed here"
        )

    def test_child_deindex_is_separate_from_the_parent_batch(self, deindexed):
        # One batch per recursion level, not one merged batch: each level
        # confirms its own delete against its own filter.
        parent_pks = [ObjectId()]
        child_pks = [ObjectId(), ObjectId()]
        parent_qs, _, _, _ = self._build(parent_pks, child_pks)

        BaseQuerySet.delete(parent_qs)

        assert set(deindexed[0]).isdisjoint(set(deindexed[1]))
        assert sorted(map(str, deindexed[0] + deindexed[1])) == sorted(
            map(str, child_pks + parent_pks)
        )


# ===========================================================================
# 4. Surviving documents must never be de-indexed
# ===========================================================================


class TestSurvivorProtection:
    def test_matching_count_costs_no_extra_query(self, deindexed):
        pks = [ObjectId() for _ in range(3)]
        collection = _CollectionStub(pks, deleted_count=3, acknowledged=True)
        qs = _QuerySetStub(collection, _DocClass())

        BaseQuerySet.delete(qs)

        assert collection.confirm_chunks == [], (
            "an acknowledged delete whose count matches the scan proves "
            "the batch is clean — the confirmation must stay free here"
        )
        assert deindexed == [pks]

    def test_deleted_count_mismatch_drops_the_survivor(self, deindexed):
        # The race the mismatch reveals: one document was mutated out of
        # the filter between the scan and the delete, so it is still
        # alive. De-indexing it would make a live document permanently
        # unreachable by KNN with nothing to restore it.
        gone_a, survivor, gone_b = ObjectId(), ObjectId(), ObjectId()
        collection = _CollectionStub(
            [gone_a, survivor, gone_b], survivors=[survivor], deleted_count=2
        )
        qs = _QuerySetStub(collection, _DocClass())

        BaseQuerySet.delete(qs)

        assert collection.confirm_chunks, "a mismatch must pay the re-check"
        assert deindexed == [[gone_a, gone_b]]
        assert survivor not in deindexed[0], (
            "a document that survived the delete must keep its vector — "
            "the unrecoverable direction of #207's race"
        )

    def test_unacknowledged_write_concern_forces_the_recheck(self, deindexed):
        # Under w=0 ``deleted_count`` carries no information, so a count
        # that happens to equal the scan size proves nothing. Trusting it
        # would de-index survivors on exactly the write concern that can
        # least afford it.
        gone, survivor = ObjectId(), ObjectId()
        collection = _CollectionStub(
            [gone, survivor],
            survivors=[survivor],
            deleted_count=2,  # would "match" if the count were trusted
            acknowledged=False,
        )
        qs = _QuerySetStub(collection, _DocClass())

        assert BaseQuerySet.delete(qs) is None  # unack'd → no count returned
        assert collection.confirm_chunks, (
            "w=0 must re-check even when deleted_count looks right"
        )
        assert deindexed == [[gone]]

    def test_all_survived_means_nothing_is_deindexed(self, deindexed):
        pks = [ObjectId(), ObjectId()]
        collection = _CollectionStub(pks, survivors=pks, deleted_count=0)
        qs = _QuerySetStub(collection, _DocClass())

        BaseQuerySet.delete(qs)

        assert deindexed == [], "no confirmed delete means no de-index"

    def test_recheck_is_chunked_below_the_bson_limit(self, deindexed):
        pks = [ObjectId() for _ in range(_PK_SCAN_CHUNK + 20)]
        collection = _CollectionStub(pks, deleted_count=0)  # force the re-check
        qs = _QuerySetStub(collection, _DocClass())

        BaseQuerySet.delete(qs)

        assert [len(c) for c in collection.confirm_chunks] == [_PK_SCAN_CHUNK, 20], (
            "an unbounded $in list on a large teardown would push the "
            "query document past MongoDB's 16MB BSON limit"
        )
        # Chunking must not lose or duplicate pks.
        seen = [pk for chunk in collection.confirm_chunks for pk in chunk]
        assert seen == pks

    def test_pk_scan_chunk_is_five_hundred(self):
        assert _PK_SCAN_CHUNK == 500


class TestConfirmDeletedDirectly:
    def test_empty_batch_never_touches_the_collection(self):
        collection = _CollectionStub([])

        assert _confirm_deleted(collection, [], _DeleteResult()) == []
        assert collection.confirm_chunks == []

    def test_free_path_returns_the_batch_unchanged(self):
        pks = [ObjectId(), ObjectId()]
        collection = _CollectionStub(pks)

        result = _DeleteResult(acknowledged=True, deleted_count=2)

        assert _confirm_deleted(collection, pks, result) == pks
        assert collection.confirm_chunks == []

    def test_confirmation_failure_drops_the_batch(self, logged):
        # Deliberate direction: dropping the batch leaks hashes a sweep
        # can recover; de-indexing pks we could not verify cannot be
        # recovered at all.
        pks = [ObjectId()]
        collection = _CollectionStub(
            pks, deleted_count=0, confirm_raises=RuntimeError("cursor died")
        )

        assert _confirm_deleted(collection, pks, _DeleteResult(deleted_count=0)) == []
        assert any("[WARNING]" in m for m in logged), (
            f"a dropped confirmation must be greppable; got {logged!r}"
        )


# ===========================================================================
# 5. Fail-soft — nothing in this cleanup may fail a delete
# ===========================================================================


class TestFailSoft:
    def test_dead_prescan_cursor_still_deletes(self, deindexed, logged):
        # The scan is the only part that runs BEFORE the delete, so it is
        # the only part that could stop one.
        collection = _CollectionStub(
            [ObjectId()], scan_raises=RuntimeError("cursor died")
        )
        qs = _QuerySetStub(collection, _DocClass())

        assert BaseQuerySet.delete(qs) == 1
        assert collection.delete_many_calls, "the delete must still happen"
        assert deindexed == [], "a failed scan must skip the cleanup, not guess"
        assert any("[WARNING]" in m for m in logged)

    def test_dead_confirmation_cursor_still_deletes(self, deindexed, logged):
        collection = _CollectionStub(
            [ObjectId()], deleted_count=0, confirm_raises=RuntimeError("cursor died")
        )
        qs = _QuerySetStub(collection, _DocClass())

        assert BaseQuerySet.delete(qs) == 0
        assert deindexed == []

    def test_unreachable_redis_does_not_fail_the_delete(self, monkeypatch):
        # End-to-end through the real ``deindex_many``: an absent or
        # unreachable Redis must cost vector entries, never the delete
        # Mongo has already committed.
        monkeypatch.setattr(db_sync, "log", lambda *a, **kw: None)
        monkeypatch.setattr(
            db_sync,
            "_get_redis",
            lambda: (_ for _ in ()).throw(ConnectionError("connection refused")),
        )
        pks = [ObjectId() for _ in range(2)]
        collection = _CollectionStub(pks)
        qs = _QuerySetStub(collection, _DocClass())

        assert BaseQuerySet.delete(qs) == 2

    def test_redis_failure_mid_cascade_does_not_stop_the_cascade(self, monkeypatch):
        monkeypatch.setattr(db_sync, "log", lambda *a, **kw: None)
        monkeypatch.setattr(
            db_sync,
            "_get_redis",
            lambda: (_ for _ in ()).throw(ConnectionError("connection refused")),
        )
        child_collection = _CollectionStub([ObjectId()])
        refs = _RecursingRefs(_QuerySetStub(child_collection, _DocClass()))
        parent_collection = _CollectionStub([ObjectId()])
        parent_qs = _QuerySetStub(
            parent_collection, _DocClass({(_RefsDocClass(refs), "parent"): CASCADE})
        )

        assert BaseQuerySet.delete(parent_qs) == 1
        assert child_collection.delete_many_calls, "the child delete must land"


# ===========================================================================
# 6. ``deindex_many`` — batching, key shape, per-chunk isolation
# ===========================================================================


class TestDeindexManyKeys:
    def test_sends_the_lore_prefixed_keys(self, monkeypatch):
        redis = _RedisStub()
        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)

        assert deindex_many(["a", "b"]) is True
        assert redis.delete_calls == [["lore:a", "lore:b"]]

    def test_objectids_match_the_writer_key(self, monkeypatch):
        # pks arrive as ObjectId from the funnel and as str from the
        # worker; both must land on the key the writer produced.
        redis = _RedisStub()
        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)
        oid = ObjectId()

        deindex_many([oid])

        assert redis.delete_calls == [[_index_key(oid)]] == [[f"lore:{oid}"]]

    def test_one_variadic_del_not_one_per_key(self, monkeypatch):
        # The point of the batch form: N separate DELs would drop N
        # round-trips into the path of a single delete_many, each bounded
        # by REDIS_SOCKET_TIMEOUT_SECONDS.
        redis = _RedisStub()
        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)

        deindex_many([f"pk{i}" for i in range(50)])

        assert len(redis.delete_calls) == 1
        assert len(redis.delete_calls[0]) == 50

    def test_accepts_a_generator(self, monkeypatch):
        # The MIGRATIONS recipe passes a generator expression straight
        # from a projected cursor; materializing is the callee's job.
        redis = _RedisStub()
        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)

        assert deindex_many(d["_id"] for d in [{"_id": "a"}, {"_id": "b"}]) is True
        assert redis.delete_calls == [["lore:a", "lore:b"]]

    def test_empty_input_builds_no_client(self, monkeypatch):
        # A filtered bulk delete that matched nothing is the common case;
        # it must not pay a connection or a round-trip.
        def _boom():
            raise AssertionError("_get_redis must not be called for an empty batch")

        monkeypatch.setattr(db_sync, "_get_redis", _boom)

        assert deindex_many([]) is True


class TestDeindexManyChunking:
    def test_chunk_size_is_five_hundred(self):
        # DEL is O(N) and runs to completion on Redis's single thread —
        # the cap is what keeps a 100k teardown from stalling every other
        # client, so the value is part of the contract.
        assert _DEINDEX_CHUNK == 500

    def test_large_batch_is_split_into_capped_chunks(self, monkeypatch):
        redis = _RedisStub()
        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)
        pks = [f"pk{i}" for i in range(1200)]

        assert deindex_many(pks) is True
        assert [len(c) for c in redis.delete_calls] == [500, 500, 200]
        sent = [k for chunk in redis.delete_calls for k in chunk]
        assert sent == [f"lore:{pk}" for pk in pks], (
            "chunking must not drop, duplicate or reorder keys"
        )

    def test_exact_multiple_produces_no_empty_chunk(self, monkeypatch):
        redis = _RedisStub()
        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)

        deindex_many([f"pk{i}" for i in range(1000)])

        assert [len(c) for c in redis.delete_calls] == [500, 500]


class TestDeindexManyPerChunkIsolation:
    def test_a_failing_chunk_does_not_abandon_the_rest(self, monkeypatch):
        # The isolation that matters: try/except around the loop would
        # pass every happy-path test above and leak every key after the
        # first blip. With redis-py's retry policy disabled (0.3.171) a
        # single transient error raises immediately.
        redis = _RedisStub(raise_on_chunk=[1])
        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)
        monkeypatch.setattr(db_sync, "log", lambda *a, **kw: None)
        pks = [f"pk{i}" for i in range(1200)]

        assert deindex_many(pks) is False, "a failed chunk must report failure"
        assert [len(c) for c in redis.delete_calls] == [500, 500, 200], (
            "chunk 3 must still be attempted after chunk 2 raised"
        )
        assert redis.delete_calls[2][0] == "lore:pk1000"

    def test_first_chunk_failure_still_sends_the_others(self, monkeypatch):
        redis = _RedisStub(raise_on_chunk=[0])
        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)
        monkeypatch.setattr(db_sync, "log", lambda *a, **kw: None)

        assert deindex_many([f"pk{i}" for i in range(1100)]) is False
        assert len(redis.delete_calls) == 3

    def test_every_chunk_failing_returns_false_without_raising(self, monkeypatch):
        redis = _RedisStub(raise_on_chunk=[0, 1])
        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)
        monkeypatch.setattr(db_sync, "log", lambda *a, **kw: None)

        assert deindex_many([f"pk{i}" for i in range(600)]) is False


class TestDeindexManyFailSoft:
    @pytest.mark.parametrize(
        "exc",
        [
            ConnectionError("connection refused"),
            TimeoutError("socket timeout"),
            RuntimeError("some redis-py internal"),
        ],
    )
    def test_redis_failures_return_false_without_raising(self, monkeypatch, exc):
        monkeypatch.setattr(db_sync, "log", lambda *a, **kw: None)
        monkeypatch.setattr(
            db_sync, "_get_redis", lambda: (_ for _ in ()).throw(exc)
        )

        assert deindex_many(["a"]) is False

    def test_missing_redis_package_returns_false(self, monkeypatch):
        # redis lives in the [tasks] extra; an ORM-only consumer has none
        # installed and every bulk delete they issue reaches this path.
        import sys

        monkeypatch.setattr(db_sync, "_redis_client", None)
        monkeypatch.setitem(sys.modules, "redis", None)  # `import redis` → ImportError
        monkeypatch.setattr(db_sync, "log", lambda *a, **kw: None)

        assert deindex_many(["a"]) is False

    def test_failure_is_logged_at_warning_with_a_key(self, monkeypatch):
        # A False return leaks those hashes permanently and nothing
        # revisits them, so the log line is the operator's only
        # breadcrumb — and bare ``log()`` emits at DEBUG, below the
        # default LOG_LEVEL.
        logged = []
        monkeypatch.setattr(db_sync, "log", lambda msg, *a, **kw: logged.append(str(msg)))
        monkeypatch.setattr(
            db_sync,
            "_get_redis",
            lambda: (_ for _ in ()).throw(ConnectionError("refused")),
        )

        deindex_many(["abc"])

        assert any("[WARNING]" in m for m in logged), (
            f"the permanent-leak condition MUST be greppable; got {logged!r}"
        )
        assert any("lore:abc" in m for m in logged), (
            f"the log must name a key so the leak is sweepable; got {logged!r}"
        )

    def test_uses_log_not_print(self, monkeypatch):
        printed = []
        monkeypatch.setattr("builtins.print", lambda *a, **kw: printed.append(a))
        monkeypatch.setattr(db_sync, "log", lambda *a, **kw: None)
        monkeypatch.setattr(
            db_sync,
            "_get_redis",
            lambda: (_ for _ in ()).throw(ConnectionError("refused")),
        )

        deindex_many(["abc"])

        assert printed == [], f"de-index failure must not print; got {printed!r}"
