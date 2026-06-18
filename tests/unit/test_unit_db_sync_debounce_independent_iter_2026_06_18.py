"""Independent second-perspective coverage for PR #159.

PR #159 (closes #148) ships 6 hermetic tests pinning the supersede
+ not-found branches of ``db_sync.process_single_object_sync``. This
file is the test-agent's independent coverage, written from a fresh
read of ``db_sync.py:660-693`` rather than dev's tests, with stubs
rebuilt from scratch.

Gaps targeted (corners dev's tests did not pin):

- ``redis.Redis(..., decode_responses=True)`` is the **configured
  contract** at ``db_sync.py:206-210``. The supersede check
  ``current_active_token != token`` works only because Redis returns
  ``str`` (not ``bytes``). If someone flips that flag, every job
  becomes "superseded" because ``b"tok" != "tok"`` is True. Pin the
  bytes-vs-str sensitivity so the configuration assumption surfaces
  if changed.
- ``mongo_db.__getitem__`` is called with the **exact** ``collection_name``.
  Dev's test verifies the doc isn't fetched on supersede; it does NOT
  verify the collection-name selector on the happy path.
- The invalid-ObjectId fallback (``db_sync.py:687-688``): when the
  ``ObjectId(object_id)`` coercion raises ``InvalidId`` / ``TypeError``,
  the function should still try ``find_one({"_id": object_id})`` with
  the raw value. Dev pinned the happy-path object_id; this corner is
  untouched.
- The debounce wait happens BEFORE the supersede check
  (``time.sleep(5)`` at db_sync.py:671, then ``r.get`` at db_sync.py:675).
  Pin the order so a refactor that hoists the supersede check before
  the sleep — making the debounce ineffective — gets caught.
- Empty-string and whitespace token-key returns from Redis: the !=
  comparison still treats them as "different from token" → supersede.
  A refactor to ``not current_active_token or current_active_token != token``
  would change this; pin the current behavior so the choice is
  deliberate.

Hermetic — no Redis or Mongo. Stubs rebuild the dependency injection
from scratch (no `_setup` shared helper) so a bug that breaks the
stub contract surfaces differently in the two test files.
"""

import bson
import pytest

from autonomous.db import db_sync


# ---------------------------------------------------------------------------
# Independent stub builder
# ---------------------------------------------------------------------------


class _RedisStub:
    """Record-and-replay stand-in for the Redis client."""

    def __init__(self, *, get_returns):
        self._get_returns = get_returns
        self.get_calls = []
        self.delete_calls = []
        self.hset_calls = []

    def get(self, key):
        self.get_calls.append(key)
        return self._get_returns

    def delete(self, key):
        self.delete_calls.append(key)

    def hset(self, *args, **kwargs):
        self.hset_calls.append((args, kwargs))


class _CollectionStub:
    """The object returned by ``mongo_db[collection_name]``. Its
    ``find_one`` returns the test's pre-arranged doc."""

    def __init__(self, find_one_returns):
        self._find_one_returns = find_one_returns
        self.find_one_calls = []

    def find_one(self, query):
        self.find_one_calls.append(query)
        return self._find_one_returns


class _MongoDbStub:
    """Records the collection_name passed to ``db[collection_name]``."""

    def __init__(self, collection):
        self._collection = collection
        self.subscript_calls = []

    def __getitem__(self, key):
        self.subscript_calls.append(key)
        return self._collection


@pytest.fixture
def wire_stubs(monkeypatch):
    """Helper to wire the function's two dependency-injection seams
    plus ``time.sleep`` / ``record_embedding_sync_event`` /
    ``get_vector``. Returns a builder so each test chooses what
    Redis ``.get`` returns and what Mongo ``find_one`` returns."""

    sleep_calls = []

    def _build(*, get_returns, find_one_returns):
        redis_stub = _RedisStub(get_returns=get_returns)
        collection = _CollectionStub(find_one_returns)
        mongo = _MongoDbStub(collection)

        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis_stub)
        monkeypatch.setattr(db_sync, "_get_mongo_db", lambda: mongo)
        monkeypatch.setattr(
            db_sync.time, "sleep", lambda s: sleep_calls.append(s)
        )
        monkeypatch.setattr(
            db_sync, "record_embedding_sync_event", lambda *a, **k: None
        )
        # Block get_vector — the tests target branches that should
        # not reach the embedding step.
        monkeypatch.setattr(
            db_sync,
            "get_vector",
            lambda _: (_ for _ in ()).throw(
                AssertionError(
                    "get_vector reached on a debounce-branch test"
                )
            ),
        )

        return redis_stub, mongo, collection, sleep_calls

    return _build


# ===========================================================================
# 1. decode_responses=True configuration assumption — bytes vs str
# ===========================================================================


class TestDecodeResponsesConfigurationAssumption:
    """The supersede check ``current_active_token != token`` only works
    when Redis returns ``str``. If someone changes
    ``decode_responses=True`` to ``False`` at db_sync.py:209, Redis
    would return ``bytes``, and ``b"tok" != "tok"`` is ``True`` — so
    every job would supersede. These tests pin the assumption."""

    def test_bytes_token_does_not_match_str_token(self, wire_stubs):
        # Simulate the misconfiguration: Redis returns bytes despite
        # the caller passing str. The current code's != comparison
        # treats them as different → supersede.
        redis_stub, mongo, collection, _ = wire_stubs(
            get_returns=b"tok", find_one_returns={"_id": "x"}
        )

        db_sync.process_single_object_sync("abc123", "lore", "tok")

        # Must NOT have reached find_one (= supersede branch fired).
        assert collection.find_one_calls == []
        # Redis WAS queried (so the comparison happened).
        assert len(redis_stub.get_calls) == 1

    def test_str_token_matches_str_token_reaches_find_one(self, wire_stubs):
        # The opposite: when both sides are str AND match, the function
        # proceeds to find_one (and then to the not-found branch
        # because we returned None below). Sanity check that the
        # str-vs-str comparison works as the code expects.
        redis_stub, mongo, collection, _ = wire_stubs(
            get_returns="tok", find_one_returns=None
        )

        db_sync.process_single_object_sync("abc123", "lore", "tok")

        assert len(collection.find_one_calls) == 1
        # Cleanup delete fired on the not-found branch — proves we
        # reached the second half of the function.
        assert redis_stub.delete_calls == ["lore:abc123"]


# ===========================================================================
# 2. Mongo subscript selector identity
# ===========================================================================


class TestMongoCollectionSelectorIdentity:
    """``mongo_db[collection_name]`` must be invoked with the
    ``collection_name`` arg verbatim. Dev's tests don't assert on the
    subscript arg — a refactor that hardcoded the collection or
    routed through a lookup would silently work for the matching
    case but pollute the queries shape."""

    def test_subscript_uses_exact_collection_name(self, wire_stubs):
        _, mongo, _, _ = wire_stubs(
            get_returns="tok", find_one_returns=None
        )

        db_sync.process_single_object_sync(
            "abc123", "lore_arbitrary_name", "tok"
        )

        # The function does the subscript exactly once for find_one
        # (after the supersede check). With find_one returning None
        # the not-found branch fires — which does NOT touch the
        # collection again, so the subscript count is exactly 1.
        assert mongo.subscript_calls == ["lore_arbitrary_name"]


# ===========================================================================
# 3. Invalid-ObjectId fallback — the raw-id path
# ===========================================================================


class TestInvalidObjectIdFallback:
    """``db_sync.py:687-688`` catches ``InvalidId`` / ``TypeError`` from
    the ``ObjectId(object_id)`` coercion and retries find_one with the
    raw ``object_id`` instead. Dev's happy-path tests use a string ID
    that happens to fail ObjectId coercion (``"abc123"`` is too short
    for a 24-hex-char ObjectId) — exercising this branch incidentally
    but never asserting on it. Pin it explicitly."""

    def test_non_objectid_string_reaches_find_one_with_raw_id(
        self, wire_stubs
    ):
        # "abc123" is NOT 24 hex chars → bson.ObjectId raises InvalidId
        # → the except branch retries with the raw string.
        _, _, collection, _ = wire_stubs(
            get_returns="tok",
            find_one_returns=None,
        )

        with pytest.raises(bson.errors.InvalidId):
            # Sanity-pin: confirm the test's input would in fact raise
            # InvalidId via the same coercion the function uses.
            bson.ObjectId("abc123")

        db_sync.process_single_object_sync("abc123", "lore", "tok")

        # find_one called exactly once, with the RAW string ID (not a
        # coerced ObjectId — the coercion failed and the fallback ran).
        assert len(collection.find_one_calls) == 1
        assert collection.find_one_calls[0] == {"_id": "abc123"}

    def test_valid_objectid_string_is_coerced(self, wire_stubs):
        # The positive case: a valid 24-hex-char string IS coerced to
        # ObjectId before find_one. Pins that the fallback branch
        # only fires on InvalidId, not on every string input.
        oid = bson.ObjectId()
        oid_str = str(oid)
        _, _, collection, _ = wire_stubs(
            get_returns="tok", find_one_returns=None
        )

        db_sync.process_single_object_sync(oid_str, "lore", "tok")

        assert len(collection.find_one_calls) == 1
        query = collection.find_one_calls[0]
        # The query's _id should be an ObjectId (from the try branch),
        # NOT the raw string (which would mean the fallback ran).
        assert isinstance(query["_id"], bson.ObjectId)
        assert query["_id"] == oid


# ===========================================================================
# 4. The debounce wait happens BEFORE the supersede check
# ===========================================================================


class TestSleepBeforeSupersedeCheck:
    """``time.sleep(5)`` must run before ``r.get(token_key)`` — the
    whole point of debounce is that newer saves get a chance to bump
    the token during the sleep window. A refactor that swaps the two
    (e.g. "check supersede first to short-circuit") defeats debounce
    silently because no save can possibly happen in the zero-time
    window before the sleep."""

    def test_sleep_was_called_with_5_seconds(self, wire_stubs):
        _, _, _, sleep_calls = wire_stubs(
            get_returns="tok", find_one_returns=None
        )

        db_sync.process_single_object_sync("abc123", "lore", "tok")

        assert sleep_calls == [5], (
            f"expected time.sleep(5) once; got {sleep_calls}"
        )

    def test_sleep_runs_even_on_supersede_path(self, wire_stubs):
        # Critical pin: even when supersede WILL fire, the sleep
        # still happens. If it didn't, debounce would be a no-op for
        # the supersede path — the very path debounce exists to
        # support.
        _, _, _, sleep_calls = wire_stubs(
            get_returns="newer-token", find_one_returns={"_id": "x"}
        )

        db_sync.process_single_object_sync("abc123", "lore", "stale-token")

        assert sleep_calls == [5]


# ===========================================================================
# 5. Empty-string and whitespace token returns — supersede semantics
# ===========================================================================


class TestEmptyAndWhitespaceTokenSupersedes:
    """Empty-string or whitespace from Redis must supersede the same
    way ``None`` does — they all represent "the key under inspection
    is not what was enqueued." Dev's None test is one corner; these
    pin the other falsy-but-non-None cases so a refactor to
    ``not current_active_token or ...`` makes a deliberate choice
    rather than accidentally collapsing the distinction."""

    def test_empty_string_token_supersedes(self, wire_stubs):
        _, _, collection, _ = wire_stubs(
            get_returns="", find_one_returns={"_id": "x"}
        )

        db_sync.process_single_object_sync("abc123", "lore", "tok")

        # Empty string != "tok" → supersede; find_one untouched.
        assert collection.find_one_calls == []

    def test_whitespace_token_supersedes(self, wire_stubs):
        _, _, collection, _ = wire_stubs(
            get_returns="  ", find_one_returns={"_id": "x"}
        )

        db_sync.process_single_object_sync("abc123", "lore", "tok")

        # The function does NOT strip whitespace before comparison —
        # raw inequality means "  " != "tok" → supersede.
        assert collection.find_one_calls == []
