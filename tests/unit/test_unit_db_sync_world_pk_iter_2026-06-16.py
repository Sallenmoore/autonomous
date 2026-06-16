"""Independent test-agent coverage for PR #133 (#132).

Adds ``world_pk`` to the ``lore:<pk>`` Redis hash so multi-tenant
consumers can run world-scoped KNN retrieval. Wire shape gained one
field and one helper:

- ``_extract_world_pk(doc)`` — translates the raw BSON ``world``
  field (whatever shape the ODM persisted) into a string pk, with
  ``""`` as the no-reference sentinel. Never dereferences.
- ``process_single_object_sync`` — calls the helper after the
  ``get_vector`` success branch and writes the result as the
  ``world_pk`` field on the lore hash.

Independent perspective:
- The PR body asserts five inbound shapes (GenericReferenceField SON,
  bare DBRef, bare ObjectId, plain string, None/missing). Test pins
  each one separately so a future refactor that drops a branch
  fails one row instead of silently degrading.
- The PR description says the field is "purely additive" — the
  end-to-end test asserts the **pre-existing** fields are still
  written verbatim alongside, so a regression that swaps the mapping
  for a side-effect would fail.
- The PR claims no extra Mongo round-trip is taken. Test pins that
  ``find_one`` is called once and the helper takes its input from
  the same doc dict (no second dereference).
- Hash field name + value are asserted as string ``"world_pk"`` (not
  bytes, not nested under another key) because consumers driving the
  ``@world_pk:{...}`` Redis-Search tag filter depend on exact RESP
  key naming.
"""

from unittest.mock import MagicMock

import pytest
from bson.dbref import DBRef
from bson.objectid import ObjectId

from autonomous.db import db_sync
from autonomous.db.db_sync import _extract_world_pk


# ---------------------------------------------------------------------------
# _extract_world_pk — pure helper, per-shape coverage
# ---------------------------------------------------------------------------


class TestExtractWorldPkShapes:
    """One test per inbound shape the PR description enumerates. Each
    pins the contract from the PR body's "Wire shape" + helper
    docstring as a per-shape regression guard."""

    def test_missing_world_field_returns_empty_string(self):
        # The single-tenant path: lore docs that don't carry a
        # ``world`` ref at all (world itself, lore in single-world
        # installs) MUST degrade to "" — not None, not raise, not the
        # string "None". Consumers test-equal against "" in the
        # ``@world_pk:{...}`` filter.
        assert _extract_world_pk({"_id": "x"}) == ""

    def test_explicit_none_world_returns_empty_string(self):
        # ``world: None`` (explicit null on disk) MUST take the same
        # path as missing — not stringify to "None". An operator
        # search for canon-with-no-world relies on the "" sentinel.
        assert _extract_world_pk({"_id": "x", "world": None}) == ""

    def test_generic_reference_field_son_shape(self):
        # The shape ``ReferenceAttr`` (which inherits
        # ``GenericReferenceField``) writes:
        #   {"_cls": "World", "_ref": DBRef("world", ObjectId(...))}
        # This is the dominant production shape — StoryTeller's lore
        # references world via ReferenceAttr → GenericReferenceField.
        # The pk MUST come from ``_ref.id``, the BSON-level pointer,
        # not the ``_cls`` string.
        oid = ObjectId()
        doc = {
            "_id": "lore_x",
            "world": {
                "_cls": "World",
                "_ref": DBRef("world", oid),
            },
        }
        assert _extract_world_pk(doc) == str(oid)

    def test_plain_dbref_shape(self):
        # ``ReferenceField`` (mongoengine default, ``dbref=True``)
        # writes a bare DBRef rather than the GenericReferenceField
        # SON envelope. Helper MUST handle it via the hasattr "id"
        # branch — not fall through to ``str()`` (which would emit
        # the full DBRef repr like
        # "DBRef('world', ObjectId('...'))").
        oid = ObjectId()
        doc = {"_id": "lore_x", "world": DBRef("world", oid)}
        assert _extract_world_pk(doc) == str(oid)

    def test_bare_object_id_shape(self):
        # ``ReferenceField(dbref=False)`` persists a bare ObjectId.
        # ObjectId does not have an ``.id`` attribute, so it falls
        # through to ``str(world)`` which yields the 24-char hex —
        # which IS the pk every consumer expects.
        oid = ObjectId()
        doc = {"_id": "lore_x", "world": oid}
        assert _extract_world_pk(doc) == str(oid)

    def test_plain_string_pk_shape(self):
        # Non-MongoEngine consumer schemas may already store the pk
        # as a string. Helper MUST pass it through unchanged — the
        # round-trip ``str(s)`` is a no-op but must not corrupt.
        doc = {"_id": "lore_x", "world": "world-pk-abc-123"}
        assert _extract_world_pk(doc) == "world-pk-abc-123"

    def test_partial_son_missing_ref_returns_empty_string(self):
        # A partially-written GenericReferenceField doc (in the wild
        # we see ``_cls`` without ``_ref`` from interrupted writes)
        # MUST NOT raise from this observability path — fall through
        # to "". Docstring explicitly calls out the .get over [] for
        # this case.
        doc = {"_id": "x", "world": {"_cls": "World"}}
        assert _extract_world_pk(doc) == ""

    def test_son_with_ref_lacking_id_attr_falls_back_to_str(self):
        # The "unexpected dict shape" branch — ``_ref`` is present
        # but doesn't expose ``.id``. Helper MUST still emit
        # SOMETHING grep-able rather than raising. We pin
        # ``str(ref)`` to anchor the contract.
        sentinel = "not-a-dbref"
        doc = {"_id": "x", "world": {"_cls": "World", "_ref": sentinel}}
        assert _extract_world_pk(doc) == sentinel

    def test_unexpected_ref_shape_logs_warning(self, monkeypatch):
        # The /review-pr silent-failure-hunter flagged this branch:
        # a degraded write of a garbage tag value into the consumer-
        # facing ``world_pk`` field would otherwise be invisible to
        # storyteller's /debug/lore/health. The fix is a log call —
        # not a raise — preserving the "observability path, no
        # impact on indexing throughput" intent of the helper.
        # Pin the log so a future refactor can't silently drop it.
        log_calls = []
        monkeypatch.setattr(
            "autonomous.db.db_sync.log",
            lambda msg, *args, **kwargs: log_calls.append(str(msg)),
        )
        doc = {"_id": "x", "world": {"_cls": "World", "_ref": "garbage"}}
        result = _extract_world_pk(doc)
        # Behavior unchanged: still returns the str(ref).
        assert result == "garbage"
        # New observability contract: a warning lands.
        assert any("_extract_world_pk" in m and "WARNING" in m for m in log_calls), (
            f"unexpected-shape branch MUST log; got log calls: {log_calls!r}"
        )


class TestExtractWorldPkContract:
    """Contracts the helper docstring asserts beyond shape coverage —
    properties future refactors might silently break."""

    def test_never_dereferences(self):
        # The docstring contract: "Dereference is **not** performed
        # here — the worker is meant to be Mongo-light". A real
        # regression would be a future refactor that takes a ``db``
        # arg and pulls the world doc. Pin the arity to one arg.
        import inspect

        sig = inspect.signature(_extract_world_pk)
        assert len(sig.parameters) == 1, (
            "_extract_world_pk MUST take only the doc — adding a db "
            "param re-introduces the round-trip the PR description "
            "rules out"
        )

    def test_always_returns_str(self):
        # ``world_pk`` rides into a Redis hset mapping, which serializes
        # values to bytes via str. Returning None would yield the string
        # "None" downstream — pin the str-only return for every shape
        # tested above plus the empty fallback.
        cases = [
            {"_id": "x"},
            {"_id": "x", "world": None},
            {"_id": "x", "world": DBRef("world", ObjectId())},
            {"_id": "x", "world": ObjectId()},
            {"_id": "x", "world": "string-pk"},
        ]
        for doc in cases:
            result = _extract_world_pk(doc)
            assert isinstance(result, str), (
                f"world_pk MUST be str for downstream HSET; "
                f"got {type(result).__name__} from doc={doc!r}"
            )

    def test_dict_branch_uses_get_not_brackets(self):
        # Wedge: the docstring calls out ``.get`` over ``[]`` so a
        # ``_cls``-only partial dict doesn't raise. If a refactor
        # switches to ``world["_ref"]`` this raises KeyError instead
        # of returning "". Drive the partial-dict case again and
        # assert it doesn't raise. (Yes, the shape test above also
        # covers this — this test pins the *non-raising* aspect
        # explicitly, which is the load-bearing contract.)
        try:
            result = _extract_world_pk({"_id": "x", "world": {"_cls": "W"}})
        except (KeyError, AttributeError) as exc:
            pytest.fail(
                "_extract_world_pk MUST NOT raise on partial dict; "
                f"docstring requires .get fallback. Got: {exc!r}"
            )
        assert result == ""


# ---------------------------------------------------------------------------
# End-to-end via process_single_object_sync — world_pk lands on the hash
# ---------------------------------------------------------------------------


@pytest.fixture
def stubbed_sync(monkeypatch):
    """Wire up _get_redis, _get_mongo_db, time.sleep, get_vector, and
    record_embedding_sync_event so we can drive
    ``process_single_object_sync`` end-to-end without real services.

    Returns a (redis_mock, hset_capture, set_doc) tuple:
    - redis_mock is the MagicMock standing in for the Redis client
    - hset_capture is a list that the test reads after the call —
      ``hset_capture[0]`` is the mapping kwargs the worker emitted
    - set_doc(doc) is a closure the test calls to inject the mongo doc
    """
    redis = MagicMock()
    redis.get.return_value = "tok"

    hset_capture = []

    def _capture_hset(key, mapping):
        hset_capture.append({"key": key, "mapping": mapping})

    redis.hset.side_effect = _capture_hset

    mongo_db = MagicMock()

    def set_doc(doc):
        mongo_db.__getitem__.return_value.find_one.return_value = doc

    monkeypatch.setattr(db_sync, "_get_redis", lambda: redis)
    monkeypatch.setattr(db_sync, "_get_mongo_db", lambda: mongo_db)
    monkeypatch.setattr(db_sync.time, "sleep", lambda _: None)
    # Non-empty vector so the success branch fires (where world_pk
    # is written). Same fixed value across tests so the bytes
    # comparison in the additive-fields test is deterministic.
    monkeypatch.setattr(db_sync, "get_vector", lambda _: [0.1, 0.2, 0.3])
    monkeypatch.setattr(db_sync, "record_embedding_sync_event", MagicMock())

    return redis, hset_capture, set_doc, mongo_db


class TestWorldPkOnTheWire:
    """Drive process_single_object_sync to a success and inspect what
    landed on the Redis hash. The PR body claims the field is
    additive — these tests pin both the new field and the unchanged
    pre-existing wire shape."""

    def test_world_pk_field_present_on_success(self, stubbed_sync):
        # The headline contract: a doc with a world ref produces a
        # hash that carries the new world_pk field. Empty result
        # would silently regress every multi-tenant consumer.
        _, hset_capture, set_doc, _ = stubbed_sync
        oid = ObjectId()
        doc = {
            "_id": "lore_x",
            "name": "long-enough name to clear MIN_CONTENT_CHARS",
            "history": "",
            "associations": [],
            "world": {"_cls": "World", "_ref": DBRef("world", oid)},
        }
        set_doc(doc)

        db_sync.process_single_object_sync("lore_x", "lore", "tok")

        assert len(hset_capture) == 1, (
            "expected exactly one hset write on success path"
        )
        mapping = hset_capture[0]["mapping"]
        assert "world_pk" in mapping, (
            f"world_pk MUST be in hset mapping; got keys: "
            f"{sorted(mapping.keys())}"
        )
        assert mapping["world_pk"] == str(oid)

    def test_no_world_yields_empty_string_field(self, stubbed_sync):
        # Single-tenant docs (no world ref) MUST still get the field
        # written — additive-always means the wire shape is stable
        # across single- and multi-tenant deployments. Empty string
        # is the documented sentinel.
        _, hset_capture, set_doc, _ = stubbed_sync
        doc = {
            "_id": "lore_x",
            "name": "long-enough name to clear MIN_CONTENT_CHARS",
            "history": "",
            "associations": [],
            # no "world" key
        }
        set_doc(doc)

        db_sync.process_single_object_sync("lore_x", "lore", "tok")

        mapping = hset_capture[0]["mapping"]
        assert mapping["world_pk"] == "", (
            f"missing world ref MUST yield empty string; "
            f"got {mapping['world_pk']!r}"
        )

    def test_additive_pre_existing_fields_unchanged(self, stubbed_sync):
        # PR body: "Purely additive. Single-world consumers ignore the
        # new field and the existing named-field reads keep working
        # unchanged." Pin the five pre-existing field names so a
        # future "consolidation" can't drop one silently.
        _, hset_capture, set_doc, _ = stubbed_sync
        doc = {
            "_id": "lore_y",
            "name": "long-enough name to clear MIN_CONTENT_CHARS",
            "history": "",
            "associations": [],
            "world": None,
        }
        set_doc(doc)

        db_sync.process_single_object_sync("lore_y", "lore", "tok")

        mapping = hset_capture[0]["mapping"]
        # Pre-existing wire shape MUST still be intact.
        pre_existing = {
            "mongo_id",
            "collection",
            "content",
            "vector",
            "last_synced",
        }
        missing = pre_existing - set(mapping.keys())
        assert not missing, (
            f"world_pk addition stripped pre-existing fields: "
            f"missing {missing}"
        )
        assert mapping["mongo_id"] == "lore_y"
        assert mapping["collection"] == "lore"
        # last_synced is a tz-aware ISO string per the #47 fix —
        # the test agent's previous coverage pins the +00:00 suffix;
        # here we only assert the field type didn't regress to None.
        assert isinstance(mapping["last_synced"], str)

    def test_hash_key_namespace_unchanged(self, stubbed_sync):
        # The Redis key is the storyteller-facing namespace
        # (``lore:<id>``). PR #133 must not have changed the key
        # shape — only the hash field set. Pin the key.
        _, hset_capture, set_doc, _ = stubbed_sync
        doc = {
            "_id": "abc",
            "name": "long-enough name to clear MIN_CONTENT_CHARS",
            "history": "",
            "associations": [],
            "world": ObjectId(),
        }
        set_doc(doc)

        db_sync.process_single_object_sync("abc", "lore", "tok")
        assert hset_capture[0]["key"] == "lore:abc"

    def test_no_extra_mongo_round_trip(self, stubbed_sync):
        # The PR body asserts "no extra Mongo round-trip is taken"
        # for the new helper. Pin that ``find_one`` is called
        # exactly once across the whole process — a refactor that
        # dereferences ``world`` via a second find_one would fail.
        _, _, set_doc, mongo_db = stubbed_sync
        oid = ObjectId()
        doc = {
            "_id": "lore_x",
            "name": "long-enough name to clear MIN_CONTENT_CHARS",
            "history": "",
            "associations": [],
            "world": {"_cls": "World", "_ref": DBRef("world", oid)},
        }
        set_doc(doc)

        db_sync.process_single_object_sync("lore_x", "lore", "tok")

        collection_proxy = mongo_db.__getitem__.return_value
        assert collection_proxy.find_one.call_count == 1, (
            "world_pk extraction MUST stay Mongo-light; "
            "a second find_one means the helper started "
            "dereferencing the world doc"
        )

    def test_world_pk_not_written_when_vector_fails(self, stubbed_sync):
        # The PR adds world_pk INSIDE the ``if vector:`` branch.
        # When ``get_vector`` returns None, the entire hset block is
        # skipped — including the new field. Pin that no hash is
        # written so a refactor that moves world_pk out of the
        # vector-success branch (and into a phantom write that
        # silently bumps success counters) would fail.
        _, hset_capture, set_doc, _ = stubbed_sync
        doc = {
            "_id": "lore_x",
            "name": "long-enough name to clear MIN_CONTENT_CHARS",
            "history": "",
            "associations": [],
            "world": ObjectId(),
        }
        set_doc(doc)

        # Override the success-path vector with a failure (None).
        # Use monkeypatch via fixture wiring: re-patch directly.
        import autonomous.db.db_sync as dbs
        original = dbs.get_vector
        dbs.get_vector = lambda _: None
        try:
            db_sync.process_single_object_sync("lore_x", "lore", "tok")
        finally:
            dbs.get_vector = original

        assert hset_capture == [], (
            "vector failure path MUST NOT write the hash at all; "
            "world_pk write must stay gated by `if vector:`"
        )
