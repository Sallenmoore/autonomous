"""Independent tests for PR #218 — #215's bounded, gated bulk-delete de-indexing.

Written from the PR diff (two-perspective contract). The diff's three
claims, each pinned here:

1. **Gated.** ``meta = {"vector_index": False}`` skips the de-index
   bookkeeping at all three surfaces — the bulk pre-scan, the single-pk
   ``DEL`` in ``AutoModel.delete()``, and (refusal) ``save(sync=True)``
   — with the bulk gate covering the class's whole subtree, because a
   base-class delete matches subclass documents.
2. **Bounded.** A rule-free teardown whose match set overflows
   ``_BULK_DEINDEX_BUFFER`` runs chunked (scan → ``$in``-restricted
   ``delete_many`` → confirm → de-index), never buffering more than one
   refill; models with reverse-delete rules keep the single-pass shape
   at any size, because their rule arms ran once against the
   pre-teardown match set.
3. **Contained.** Chunk-delete failures, refill-scan failures, and the
   refill cap all finish the caller's delete via one fallback
   ``delete_many`` on the filter (leaking only sweepable hashes), and a
   Redis outage stops costing connect timeouts after
   ``_DEINDEX_DOWN_CALLS`` consecutive failing ``deindex_many`` calls.

Stubs are hand-rolled, never MagicMock, matching the existing funnel
suite's conventions.
"""

from unittest.mock import patch

import pytest
from bson import ObjectId

from autonomous.db import db_sync
from autonomous.db.queryset import base as qs_base
from autonomous.db.queryset.base import (
    DO_NOTHING,
    BaseQuerySet,
    _any_vector_indexed,
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _DeleteResult:
    """pymongo-faithful: ``deleted_count`` raises when unacknowledged."""

    def __init__(self, *, acknowledged=True, deleted_count=0):
        self.acknowledged = acknowledged
        self._deleted_count = deleted_count

    @property
    def deleted_count(self):
        if not self.acknowledged:
            from pymongo.errors import InvalidOperation

            raise InvalidOperation(
                "Cannot read deleted_count of an unacknowledged write"
            )
        return self._deleted_count


class _WriteConcernStub:
    document = {}


class _StatefulCollection:
    """A collection whose ``delete_many`` really removes documents.

    Two populations model the #207/#215 race vocabulary:

    - ``matching`` — documents the caller's filter currently matches
      (what scans and filter-restricted deletes see);
    - ``alive`` — documents that exist (what the ``$in`` existence
      re-check sees).

    Mutating a doc out of the filter = remove from ``matching`` only.
    A late insert = append to ``matching`` and add to ``alive``.
    """

    def __init__(self, pks, *, acknowledged=True):
        self.matching = list(pks)
        self.alive = set(pks)
        self.acknowledged = acknowledged
        self.scan_calls = []
        self.confirm_chunks = []
        self.delete_queries = []
        self.fail_next_chunk_deletes = 0
        self.fail_scans_from = None  # 1-based scan ordinal
        self.on_scan = None  # hook: called before each pre-scan/refill
        self.write_concern = _WriteConcernStub()

    def find(self, query, projection=None):
        in_clause = (query or {}).get("_id")
        if isinstance(in_clause, dict) and "$in" in in_clause:
            chunk = list(in_clause["$in"])
            self.confirm_chunks.append(chunk)
            return [{"_id": pk} for pk in chunk if pk in self.alive]
        self.scan_calls.append((query, projection))
        if self.fail_scans_from and len(self.scan_calls) >= self.fail_scans_from:
            raise RuntimeError("scan cursor died")
        if self.on_scan is not None:
            self.on_scan(self)
        return iter([{"_id": pk} for pk in list(self.matching)])

    def with_options(self, write_concern=None):
        return self

    def delete_many(self, query):
        self.delete_queries.append(query)
        if "$and" in (query or {}):
            if self.fail_next_chunk_deletes > 0:
                self.fail_next_chunk_deletes -= 1
                raise RuntimeError("election in progress")
            chunk = set(query["$and"][1]["_id"]["$in"])
            removed = [pk for pk in self.matching if pk in chunk]
        else:
            removed = list(self.matching)
        for pk in removed:
            self.matching.remove(pk)
            self.alive.discard(pk)
        return _DeleteResult(
            acknowledged=self.acknowledged, deleted_count=len(removed)
        )


class _DocClass:
    def __init__(self, meta_extra=None):
        self._meta = {"delete_rules": {}, **(meta_extra or {})}
        self._collection = "doc_collection"


class _QuerySetStub:
    def __init__(self, collection, doc, *, query=None):
        self._collection = collection
        self._document = doc
        self._query = {"world": "w1"} if query is None else query
        self._skip = 0
        self._limit = 0

    def clone(self):
        return self


@pytest.fixture(autouse=True)
def _no_signal_receivers(monkeypatch):
    from autonomous.db import signals as _signals

    monkeypatch.setattr(_signals.pre_delete, "has_receivers_for", lambda _s: False)
    monkeypatch.setattr(_signals.post_delete, "has_receivers_for", lambda _s: False)


@pytest.fixture
def small_bounds(monkeypatch):
    """Shrink the regime constants so the chunked path runs on dozens of
    pks: buffer 10, chunk 4."""
    monkeypatch.setattr(qs_base, "_BULK_DEINDEX_BUFFER", 10)
    monkeypatch.setattr(qs_base, "_BULK_DELETE_CHUNK", 4)


@pytest.fixture
def deindexed(monkeypatch):
    calls = []
    monkeypatch.setattr(
        db_sync, "deindex_many", lambda pks: (calls.append(list(pks)), True)[-1]
    )
    return calls


@pytest.fixture
def logged(monkeypatch):
    messages = []
    monkeypatch.setattr(qs_base, "log", lambda m, *a, **kw: messages.append(str(m)))
    return messages


def _flat(batches):
    return [pk for batch in batches for pk in batch]


# ===========================================================================
# 1. Constants — retuning any of these is a deliberate act
# ===========================================================================


class TestBounds:
    def test_buffer_is_one_hundred_thousand(self):
        assert qs_base._BULK_DEINDEX_BUFFER == 100_000

    def test_delete_chunk_is_ten_thousand(self):
        assert qs_base._BULK_DELETE_CHUNK == 10_000

    def test_refill_cap_is_dedicated_and_one_thousand(self):
        # A dedicated constant: retuning the memory buffer must not
        # silently retune the loop cap (review finding on the first cut).
        assert qs_base._MAX_REFILLS == 1_000

    def test_deindex_breaker_is_two_calls(self):
        assert qs_base._DEINDEX_DOWN_CALLS == 2


# ===========================================================================
# 2. The vector_index gate — bulk path
# ===========================================================================


class TestBulkGate:
    def test_opt_out_skips_scan_and_deindex_but_deletes(self, deindexed):
        pks = [ObjectId() for _ in range(3)]
        collection = _StatefulCollection(pks)
        qs = _QuerySetStub(collection, _DocClass({"vector_index": False}))

        assert BaseQuerySet.delete(qs) == 3
        assert collection.scan_calls == [], (
            "an opted-out model must pay nothing — no pre-scan at all"
        )
        assert deindexed == []
        assert collection.delete_queries == [{"world": "w1"}], (
            "skipping the bookkeeping must not touch the delete itself"
        )

    def test_absent_key_defaults_to_scanning(self, deindexed):
        pks = [ObjectId() for _ in range(2)]
        collection = _StatefulCollection(pks)
        qs = _QuerySetStub(collection, _DocClass())

        BaseQuerySet.delete(qs)

        assert len(collection.scan_calls) == 1
        assert deindexed == [pks], (
            "every pre-#215 model carries no key and must keep de-indexing"
        )

    def test_base_opt_out_with_indexed_child_still_scans(self, deindexed):
        # Base.objects.delete() matches Child documents (the _cls $in
        # query), so Base's False must not silence Child's True.
        class _Base:
            _meta = {"delete_rules": {}, "vector_index": False}
            _collection = "c"

        class _Child(_Base):
            _meta = {"delete_rules": {}, "vector_index": True}

        pks = [ObjectId() for _ in range(2)]
        collection = _StatefulCollection(pks)
        qs = _QuerySetStub(collection, _Base)

        BaseQuerySet.delete(qs)

        assert len(collection.scan_calls) == 1
        assert deindexed == [pks]

    def test_whole_subtree_opt_out_skips(self, deindexed):
        class _Base2:
            _meta = {"delete_rules": {}, "vector_index": False}
            _collection = "c"

        class _Child2(_Base2):
            _meta = {"delete_rules": {}, "vector_index": False}

        collection = _StatefulCollection([ObjectId()])
        qs = _QuerySetStub(collection, _Base2)

        BaseQuerySet.delete(qs)

        assert collection.scan_calls == []
        assert deindexed == []

    def test_grandchild_override_is_found(self):
        class _A:
            _meta = {"vector_index": False}

        class _B(_A):
            _meta = {"vector_index": False}

        class _C(_B):
            _meta = {"vector_index": True}

        assert _any_vector_indexed(_A) is True

    def test_default_true_short_circuits_before_subclasses(self):
        # The committed funnel suite passes _meta-only stub INSTANCES as
        # queryset._document; the gate must answer from the default
        # without ever needing __subclasses__ on them.
        class _InstanceOnly:
            _meta = {}

        assert _any_vector_indexed(_InstanceOnly()) is True


# ===========================================================================
# 3. The gate — single-document and save-side surfaces
# ===========================================================================


def _automodel_probe(monkeypatch, meta_extra):
    from autonomous.db import Document
    from autonomous.model import automodel as am

    class _DeindexGateProbe(am.AutoModel):
        meta = dict(meta_extra)

    seen = {"deindexed": [], "indexed": [], "saved": 0, "deleted": 0}
    monkeypatch.setattr(
        Document, "delete", lambda self, *a, **kw: seen.__setitem__(
            "deleted", seen["deleted"] + 1
        )
    )
    monkeypatch.setattr(
        Document, "save", lambda self, *a, **kw: seen.__setitem__(
            "saved", seen["saved"] + 1
        )
    )
    monkeypatch.setattr(
        am.db_sync, "deindex", lambda pk: (seen["deindexed"].append(pk), True)[-1]
    )
    monkeypatch.setattr(
        am.db_sync,
        "request_indexing",
        lambda pk, collection_name=None: seen["indexed"].append(pk),
    )
    return am, _DeindexGateProbe, seen


class TestSingleDocGate:
    def test_opt_out_delete_skips_the_del_but_deletes(self, monkeypatch):
        am, cls, seen = _automodel_probe(monkeypatch, {"vector_index": False})
        with patch.object(am, "_ensure_connected"):
            obj = cls()
            obj.pk = "pk-1"
            obj.delete()
        assert seen["deleted"] == 1
        assert seen["deindexed"] == []

    def test_default_delete_still_deindexes(self, monkeypatch):
        am, cls, seen = _automodel_probe(monkeypatch, {})
        with patch.object(am, "_ensure_connected"):
            obj = cls()
            obj.pk = "pk-2"
            obj.delete()
        assert seen["deindexed"] == ["pk-2"]


class TestSaveSyncGate:
    def test_opt_out_save_sync_refuses_and_warns(self, monkeypatch):
        # The write side is the only place hashes are created; if this
        # gate were missing, an opted-out model could accumulate hashes
        # that neither delete path would ever remove.
        am, cls, seen = _automodel_probe(monkeypatch, {"vector_index": False})
        messages = []
        with patch.object(am, "_ensure_connected"), patch.object(
            am, "log", lambda m, *a, **kw: messages.append(str(m))
        ):
            cls().save(sync=True)
        assert seen["saved"] == 1, "refusing to index must not refuse to save"
        assert seen["indexed"] == []
        assert any("vector_index" in m for m in messages), (
            "the refusal must be loud — a silent no-op would hide the "
            "caller's bug"
        )

    def test_default_save_sync_still_indexes(self, monkeypatch):
        am, cls, seen = _automodel_probe(monkeypatch, {})
        with patch.object(am, "_ensure_connected"):
            cls().save(sync=True)
        assert len(seen["indexed"]) == 1

    def test_save_without_sync_never_indexes_either_way(self, monkeypatch):
        am, cls, seen = _automodel_probe(monkeypatch, {"vector_index": False})
        with patch.object(am, "_ensure_connected"):
            cls().save()
        assert seen["indexed"] == []


# ===========================================================================
# 4. Regime selection
# ===========================================================================


class TestRegimeSelection:
    def test_at_the_buffer_boundary_stays_single_pass(
        self, small_bounds, deindexed
    ):
        pks = [ObjectId() for _ in range(10)]  # == patched buffer
        collection = _StatefulCollection(pks)
        qs = _QuerySetStub(collection, _DocClass())

        assert BaseQuerySet.delete(qs) == 10
        assert collection.delete_queries == [{"world": "w1"}]
        assert deindexed == [pks]

    def test_one_past_the_buffer_chunks(self, small_bounds, deindexed):
        pks = [ObjectId() for _ in range(11)]
        collection = _StatefulCollection(pks)
        qs = _QuerySetStub(collection, _DocClass())

        assert BaseQuerySet.delete(qs) == 11
        assert all("$and" in q for q in collection.delete_queries), (
            "past the buffer every delete must be $in-restricted"
        )

    def test_ruled_model_never_chunks(self, small_bounds, deindexed):
        # Rule enforcement ran once, against the pre-teardown match set;
        # the chunked path's refill sweep would delete late-matching
        # documents with DENY/CASCADE/NULLIFY/PULL bypassed. Ruled
        # models keep the #207 single-pass shape at any size.
        class _RuleTarget:
            _meta = {"abstract": False}

        pks = [ObjectId() for _ in range(30)]
        collection = _StatefulCollection(pks)
        doc = _DocClass()
        doc._meta["delete_rules"] = {(_RuleTarget, "ref"): DO_NOTHING}
        qs = _QuerySetStub(collection, doc)

        assert BaseQuerySet.delete(qs) == 30
        assert collection.delete_queries == [{"world": "w1"}]
        assert deindexed == [pks], (
            "the unbounded single-pass scan must still cover every pk "
            "past the buffer cap"
        )


# ===========================================================================
# 5. The chunked teardown
# ===========================================================================


class TestChunkedTeardown:
    def test_deletes_and_deindexes_everything(self, small_bounds, deindexed):
        pks = [ObjectId() for _ in range(27)]
        collection = _StatefulCollection(pks)
        qs = _QuerySetStub(collection, _DocClass())

        assert BaseQuerySet.delete(qs) == 27
        assert collection.matching == [] and collection.alive == set()
        assert sorted(map(str, _flat(deindexed))) == sorted(map(str, pks))

    def test_chunk_shape_is_filter_and_capped_in(self, small_bounds, deindexed):
        pks = [ObjectId() for _ in range(13)]
        collection = _StatefulCollection(pks)
        qs = _QuerySetStub(collection, _DocClass(), query={"world": "w7"})

        BaseQuerySet.delete(qs)

        for q in collection.delete_queries:
            assert list(q) == ["$and"]
            base, idq = q["$and"]
            assert base == {"world": "w7"}, (
                "dropping the caller's filter from the chunk delete "
                "would remove documents mutated out of it — the "
                "unrecoverable direction"
            )
            assert 0 < len(idq["_id"]["$in"]) <= 4

    def test_late_matching_documents_are_swept(self, small_bounds, deindexed):
        # A rule-free delete's contract is "everything matching": docs
        # that enter the filter mid-teardown are caught by a refill.
        pks = [ObjectId() for _ in range(12)]
        late = [ObjectId() for _ in range(3)]
        collection = _StatefulCollection(pks)
        state = {"inserted": False}

        def _insert_late(coll):
            if not state["inserted"] and len(coll.scan_calls) == 2:
                state["inserted"] = True
                coll.matching.extend(late)
                coll.alive.update(late)

        collection.on_scan = _insert_late
        qs = _QuerySetStub(collection, _DocClass())

        assert BaseQuerySet.delete(qs) == 15
        assert set(map(str, _flat(deindexed))) == set(map(str, pks + late))

    def test_survivor_mutated_out_keeps_its_vector(self, small_bounds, deindexed):
        pks = [ObjectId() for _ in range(12)]
        survivor = pks[1]
        collection = _StatefulCollection(pks)
        original = collection.delete_many

        def _mutating_delete(query):
            if survivor in collection.matching:
                collection.matching.remove(survivor)  # leaves filter, lives
            return original(query)

        collection.delete_many = _mutating_delete
        qs = _QuerySetStub(collection, _DocClass())

        BaseQuerySet.delete(qs)

        assert survivor in collection.alive
        assert survivor not in _flat(deindexed), (
            "de-indexing a live document is the unrecoverable direction"
        )
        assert all(len(c) <= 4 for c in collection.confirm_chunks), (
            "the mismatch re-check must be bounded per chunk, not run "
            "over the whole match set"
        )

    def test_unacknowledged_returns_none_and_still_drains(
        self, small_bounds, deindexed
    ):
        pks = [ObjectId() for _ in range(15)]
        collection = _StatefulCollection(pks, acknowledged=False)
        qs = _QuerySetStub(collection, _DocClass())

        assert BaseQuerySet.delete(qs) is None
        assert collection.matching == []


# ===========================================================================
# 6. Failure containment
# ===========================================================================


class TestFailureContainment:
    def test_chunk_delete_failure_falls_back_and_completes(
        self, small_bounds, deindexed, logged
    ):
        pks = [ObjectId() for _ in range(25)]
        collection = _StatefulCollection(pks)
        collection.fail_next_chunk_deletes = 1
        qs = _QuerySetStub(collection, _DocClass())

        assert BaseQuerySet.delete(qs) == 25
        assert collection.matching == []
        assert collection.delete_queries[-1] == {"world": "w1"}, (
            "the fallback must finish the caller's delete on the filter"
        )
        assert any("without de-indexing" in m for m in logged)

    def test_refill_scan_failure_falls_back_and_completes(
        self, small_bounds, deindexed, logged
    ):
        pks = [ObjectId() for _ in range(25)]
        collection = _StatefulCollection(pks)
        collection.fail_scans_from = 2  # detection scan ok, refill dies
        qs = _QuerySetStub(collection, _DocClass())

        assert BaseQuerySet.delete(qs) == 25
        assert collection.matching == []
        assert collection.delete_queries[-1] == {"world": "w1"}
        # the 11 buffered pks were still confirmed and de-indexed first
        assert len(_flat(deindexed)) == 11

    def test_refill_cap_fires_the_fallback(
        self, small_bounds, monkeypatch, deindexed, logged
    ):
        monkeypatch.setattr(qs_base, "_MAX_REFILLS", 2)
        pks = [ObjectId() for _ in range(11)]
        collection = _StatefulCollection(pks)

        def _relentless_writer(coll):
            fresh = [ObjectId() for _ in range(11)]
            coll.matching.extend(fresh)
            coll.alive.update(fresh)

        collection.on_scan = _relentless_writer
        qs = _QuerySetStub(collection, _DocClass())

        result = BaseQuerySet.delete(qs)

        assert result is not None and result > 0
        assert collection.delete_queries[-1] == {"world": "w1"}, (
            "a writer racing inserts must hit the cap and finish via "
            "the fallback, not loop forever"
        )
        assert any("refill cap" in m for m in logged)

    def test_redis_outage_stops_after_two_failing_calls(
        self, small_bounds, monkeypatch
    ):
        calls = []
        monkeypatch.setattr(
            db_sync, "deindex_many", lambda pks: (calls.append(list(pks)), False)[-1]
        )
        pks = [ObjectId() for _ in range(25)]
        collection = _StatefulCollection(pks)
        qs = _QuerySetStub(collection, _DocClass())

        assert BaseQuerySet.delete(qs) == 25
        assert len(calls) == qs_base._DEINDEX_DOWN_CALLS, (
            "each failing call against a downed Redis pays connect "
            "timeouts; the teardown must stop after the breaker trips"
        )

    def test_one_deindex_success_resets_the_breaker(
        self, small_bounds, monkeypatch
    ):
        # fail, success, fail, fail, ... — the isolated failure must not
        # count toward the give-up.
        results = iter([False, True, False, False, False, False, False])
        calls = []

        def _flaky(pks):
            calls.append(list(pks))
            return next(results, False)

        monkeypatch.setattr(db_sync, "deindex_many", _flaky)
        pks = [ObjectId() for _ in range(25)]  # 7 chunks of <=4
        collection = _StatefulCollection(pks)
        qs = _QuerySetStub(collection, _DocClass())

        BaseQuerySet.delete(qs)

        assert len(calls) == 4, (
            "fail(1) success fail(1) fail(2)->trip: exactly four calls"
        )
