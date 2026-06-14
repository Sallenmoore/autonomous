"""Independent committed coverage for PR #118 / issue #117.

PR #118 fixes catastrophic cold-read perf on ``FileAttr`` GridFS buckets
that are missing the standard ``{files_id: 1, n: 1}`` unique index — a
condition that arises on every bucket ``mongorestore``'d, live-migrated,
or hand-ported from a dump where the chunks collection already had data
when the index was missing (pymongo's ``GridIn._ensure_indexes`` is
gated on an empty collection, so it never fires there).

The fix adds ``GridFSProxy._ensure_chunks_index()``, called from the
``fs`` property on first materialization per process, with a class-level
``_ensured_chunks_indexes: set`` cache keyed by ``(db_alias,
collection_name)`` so we incur at most one ``create_index`` call per
bucket per process. ``OperationFailure`` is logged and swallowed so a
pre-existing conflicting index spec can't break upload paths.

Independent perspective (no peek at dev's ``tests/_dev_local/``):

- First ``fs`` access calls ``create_index`` with the documented spec —
  ``[("files_id", ASC), ("n", ASC)], unique=True, name="files_id_1_n_1"``
  (name matches pymongo's auto-generated name so a future vanilla
  ``_ensure_indexes`` call is also a no-op).
- Second ``fs`` access on a fresh proxy with the same ``(db_alias,
  collection_name)`` is a cache hit — ``create_index`` is NOT called
  again. This is the whole point of the fix: at most one call per
  bucket per process.
- Different ``collection_name`` values (same alias) DO trigger separate
  ``create_index`` calls — the cache key is the pair, not just the
  alias.
- Different ``db_alias`` values (same collection_name) DO trigger
  separate calls — symmetric to the above.
- ``OperationFailure`` is swallowed AND the cache entry is still added
  (forward progress: a pre-existing conflicting index must not cause us
  to retry the failing ``create_index`` every upload — the cache pins
  it as "we tried, move on"). Logged via ``autonomous.log``.
- Non-``OperationFailure`` exceptions are NOT swallowed — the swallow
  is narrowly scoped to the documented index-conflict case; an
  unrelated ``ConnectionFailure`` or ``ValueError`` must propagate so
  callers see real wire errors instead of silently degraded uploads.
"""

from unittest.mock import MagicMock, patch

import pymongo
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_chunks_index_cache():
    """The cache is a class attribute on ``GridFSProxy``, so it leaks
    across tests. Snapshot + restore around every test in this file so
    tests are order-independent (and don't contaminate other unit tests
    that import GridFSProxy after this module runs)."""
    from autonomous.db.fields import GridFSProxy

    snapshot = set(GridFSProxy._ensured_chunks_indexes)
    GridFSProxy._ensured_chunks_indexes.clear()
    try:
        yield
    finally:
        GridFSProxy._ensured_chunks_indexes.clear()
        GridFSProxy._ensured_chunks_indexes.update(snapshot)


def _make_fake_db(chunks_collection):
    """Fake db: ``db["<name>.chunks"]`` returns the chunks collection."""
    db = MagicMock(name="fake_db")
    db.__getitem__.side_effect = lambda key: (
        chunks_collection if key.endswith(".chunks") else MagicMock(name=key)
    )
    return db


# ---------------------------------------------------------------------------
# First-materialization behavior
# ---------------------------------------------------------------------------


def test_first_fs_access_calls_create_index_with_documented_spec():
    """The whole point of the fix: on first materialization, the chunks
    collection's ``create_index`` is called with the exact spec pymongo
    would have used had it run ``_ensure_indexes`` on an empty bucket."""
    from autonomous.db import fields
    from autonomous.db.fields import GridFSProxy

    chunks = MagicMock(name="fs.chunks")
    db = _make_fake_db(chunks)

    with patch.object(fields, "get_db", return_value=db), patch.object(
        fields.gridfs, "GridFS", MagicMock(name="GridFS")
    ):
        proxy = GridFSProxy(db_alias="default", collection_name="fs")
        # Trigger materialization
        _ = proxy.fs

    assert chunks.create_index.call_count == 1, (
        f"expected exactly one create_index call on first fs access, "
        f"got {chunks.create_index.call_count}"
    )
    call = chunks.create_index.call_args
    # Positional: the keys list
    keys = call.args[0]
    assert keys == [
        ("files_id", pymongo.ASCENDING),
        ("n", pymongo.ASCENDING),
    ], f"keys must match pymongo's GridFS spec; got {keys!r}"
    # Kwargs: unique + auto-name
    assert call.kwargs.get("unique") is True, (
        f"unique=True is required so duplicate chunk inserts fail loudly; "
        f"got kwargs={call.kwargs!r}"
    )
    assert call.kwargs.get("name") == "files_id_1_n_1", (
        f"name must match pymongo's auto-generated name "
        f"(otherwise a future vanilla _ensure_indexes will create a "
        f"second index with the same spec); got {call.kwargs.get('name')!r}"
    )


def test_second_fs_access_does_not_recall_create_index():
    """Cache hit: a fresh proxy on the same ``(db_alias, collection_name)``
    must NOT re-trigger ``create_index``. ``at most one call per bucket
    per process`` is the documented contract — repeat calls would
    re-acquire collMod locks on a hot path."""
    from autonomous.db import fields
    from autonomous.db.fields import GridFSProxy

    chunks = MagicMock(name="fs.chunks")
    db = _make_fake_db(chunks)

    with patch.object(fields, "get_db", return_value=db), patch.object(
        fields.gridfs, "GridFS", MagicMock(name="GridFS")
    ):
        # First proxy primes the cache
        first = GridFSProxy(db_alias="default", collection_name="fs")
        _ = first.fs
        # Second proxy (fresh instance, same alias+collection) — cache hit
        second = GridFSProxy(db_alias="default", collection_name="fs")
        _ = second.fs

    assert chunks.create_index.call_count == 1, (
        f"second fs access on same (alias, collection) must hit the "
        f"class-level cache and skip create_index; got "
        f"call_count={chunks.create_index.call_count}"
    )


def test_different_collection_names_each_get_their_own_index_call():
    """The cache key is ``(db_alias, collection_name)``, not just alias.
    Two GridFS buckets on the same db (e.g. ``fs`` and ``images``) must
    each get their own ``create_index`` call — otherwise a non-default
    bucket silently inherits the gate-by-cache-key and never gets
    indexed."""
    from autonomous.db import fields
    from autonomous.db.fields import GridFSProxy

    chunks_fs = MagicMock(name="fs.chunks")
    chunks_img = MagicMock(name="images.chunks")

    def db_for_alias(_alias):
        db = MagicMock(name="db")
        db.__getitem__.side_effect = lambda key: (
            chunks_fs if key == "fs.chunks"
            else chunks_img if key == "images.chunks"
            else MagicMock(name=key)
        )
        return db

    with patch.object(fields, "get_db", side_effect=db_for_alias), patch.object(
        fields.gridfs, "GridFS", MagicMock(name="GridFS")
    ):
        a = GridFSProxy(db_alias="default", collection_name="fs")
        _ = a.fs
        b = GridFSProxy(db_alias="default", collection_name="images")
        _ = b.fs

    assert chunks_fs.create_index.call_count == 1, "fs bucket must be indexed once"
    assert chunks_img.create_index.call_count == 1, "images bucket must be indexed once"


def test_different_db_aliases_each_get_their_own_index_call():
    """Symmetric to the collection_name case: two buckets named ``fs`` on
    two different db aliases (e.g. tenant sharding) are distinct
    buckets and must each get their own ``create_index`` call."""
    from autonomous.db import fields
    from autonomous.db.fields import GridFSProxy

    chunks_per_alias = {
        "tenant_a": MagicMock(name="tenant_a.fs.chunks"),
        "tenant_b": MagicMock(name="tenant_b.fs.chunks"),
    }

    def db_for_alias(alias):
        db = MagicMock(name=f"db[{alias}]")
        db.__getitem__.side_effect = lambda key: (
            chunks_per_alias[alias] if key == "fs.chunks"
            else MagicMock(name=key)
        )
        return db

    with patch.object(fields, "get_db", side_effect=db_for_alias), patch.object(
        fields.gridfs, "GridFS", MagicMock(name="GridFS")
    ):
        a = GridFSProxy(db_alias="tenant_a", collection_name="fs")
        _ = a.fs
        b = GridFSProxy(db_alias="tenant_b", collection_name="fs")
        _ = b.fs

    assert chunks_per_alias["tenant_a"].create_index.call_count == 1
    assert chunks_per_alias["tenant_b"].create_index.call_count == 1


# ---------------------------------------------------------------------------
# Error path: OperationFailure on create_index is swallowed + logged
# ---------------------------------------------------------------------------


def test_operation_failure_on_create_index_is_swallowed_and_cached():
    """Swallow-on-OperationFailure has two requirements:
    1. The ``fs`` property still returns a usable GridFS handle — i.e.
       upload paths don't propagate the index-conflict.
    2. The cache entry is STILL added — otherwise every subsequent
       upload would retry the failing ``create_index`` and re-hit the
       same OperationFailure (turning the fix into a perf regression).
    """
    from autonomous.db import fields
    from autonomous.db.fields import GridFSProxy

    chunks = MagicMock(name="fs.chunks")
    chunks.create_index.side_effect = pymongo.errors.OperationFailure(
        "Index with name files_id_1_n_1 already exists with a different spec"
    )
    db = _make_fake_db(chunks)

    fake_gridfs = MagicMock(name="GridFS_instance")
    GridFS_cls = MagicMock(name="GridFS_class", return_value=fake_gridfs)

    with patch.object(fields, "get_db", return_value=db), patch.object(
        fields.gridfs, "GridFS", GridFS_cls
    ):
        proxy = GridFSProxy(db_alias="default", collection_name="fs")
        # Must NOT raise
        result = proxy.fs

    assert result is fake_gridfs, (
        "fs property must still return the GridFS handle even when "
        "create_index raised OperationFailure"
    )
    assert ("default", "fs") in GridFSProxy._ensured_chunks_indexes, (
        "cache key must be added even when create_index raised — "
        "otherwise every upload retries the same failing create_index"
    )


def test_operation_failure_is_logged():
    """The swallow must produce a log line so an operator can see that
    the index couldn't be created. Patches the module-level ``log``
    symbol that ``_ensure_chunks_index`` calls directly."""
    from autonomous.db import fields
    from autonomous.db.fields import GridFSProxy

    chunks = MagicMock(name="fs.chunks")
    failure_msg = "duplicate-key error during index build"
    chunks.create_index.side_effect = pymongo.errors.OperationFailure(failure_msg)
    db = _make_fake_db(chunks)

    fake_log = MagicMock(name="log")

    with patch.object(fields, "get_db", return_value=db), patch.object(
        fields.gridfs, "GridFS", MagicMock()
    ), patch.object(fields, "log", fake_log):
        proxy = GridFSProxy(db_alias="default", collection_name="fs")
        _ = proxy.fs

    assert fake_log.call_count >= 1, (
        f"OperationFailure must produce a log call so operators see the "
        f"failure; got call_count={fake_log.call_count}"
    )
    logged_msg = " ".join(str(arg) for arg in fake_log.call_args.args)
    assert "GridFSProxy" in logged_msg, (
        f"log line must mention GridFSProxy for greppability; got: {logged_msg!r}"
    )
    assert "default" in logged_msg and "fs" in logged_msg, (
        f"log line must include the (db_alias, collection_name) the failure "
        f"is on, so operators can identify the bucket; got: {logged_msg!r}"
    )


def test_non_operation_failure_exceptions_propagate():
    """The except is narrowly scoped to ``pymongo.errors.OperationFailure``.
    A ``ConnectionFailure`` (wire dead), a ``ValueError`` (programmer
    bug in the keys spec), or any other class must NOT be swallowed —
    swallowing those would mask real bugs as silently-degraded uploads.
    """
    from autonomous.db import fields
    from autonomous.db.fields import GridFSProxy

    chunks = MagicMock(name="fs.chunks")
    chunks.create_index.side_effect = pymongo.errors.ConnectionFailure("dead")
    db = _make_fake_db(chunks)

    with patch.object(fields, "get_db", return_value=db), patch.object(
        fields.gridfs, "GridFS", MagicMock()
    ):
        proxy = GridFSProxy(db_alias="default", collection_name="fs")
        with pytest.raises(pymongo.errors.ConnectionFailure):
            _ = proxy.fs

    assert ("default", "fs") not in GridFSProxy._ensured_chunks_indexes, (
        "cache key must NOT be added when a non-OperationFailure exception "
        "propagates — otherwise a transient ConnectionFailure on first "
        "materialization would permanently disable index-ensure for that bucket"
    )


# ---------------------------------------------------------------------------
# Static surface pin
# ---------------------------------------------------------------------------


def test_ensured_chunks_indexes_is_class_level_set():
    """The cache is documented as a class-level set so subclasses
    (``ImageGridFsProxy``) share it. If a future change accidentally
    flips it to an instance attribute, the cache stops working across
    proxy instances — the perf fix degrades silently."""
    from autonomous.db.fields import GridFSProxy

    assert isinstance(GridFSProxy._ensured_chunks_indexes, set), (
        "_ensured_chunks_indexes must be a set on the class"
    )
    # ImageGridFsProxy inherits — confirm it shares the same object
    from autonomous.db.fields import ImageGridFsProxy

    assert (
        ImageGridFsProxy._ensured_chunks_indexes
        is GridFSProxy._ensured_chunks_indexes
    ), (
        "subclasses must share the cache — otherwise an ImageField bucket "
        "and a FileField bucket on the same (alias, collection) would each "
        "fire their own create_index call"
    )
