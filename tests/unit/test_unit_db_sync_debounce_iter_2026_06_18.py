"""Pinning tests for ``process_single_object_sync`` debounce branches
(closes #148).

The function's two debounce-correctness branches were never exercised
by the existing test suite — every test that drives the function set
``redis_client.get.return_value = token`` (a matching token) to reach
the happy path. That left:

- ``db_sync.py:677`` — **mismatched token** → "Superseded by a newer
  save" early return. A newer save invalidates the in-flight job and
  embedding generation must be skipped.
- ``db_sync.py:690-693`` — **document not found** → ``r.delete(
  f"<collection>:<id>")`` cleanup + return. Cleans up the stored
  embedding key when the source doc was deleted between enqueue and
  run.

A refactor of the token comparison (``!=`` vs a normalized compare,
decode_responses interaction, etc.) or the not-found cleanup site could
silently break either branch with no test signal. These tests pin both.

Stub pattern adapted from
``tests/unit/test_unit_db_sync_batch_iter_2026_05_13.py:_setup``.
"""

from unittest.mock import MagicMock

from autonomous.db import db_sync


def _setup_stubs(monkeypatch, *, get_token_return, find_one_doc):
    """Wire ``_get_redis`` / ``_get_mongo_db`` / ``time.sleep`` /
    ``record_embedding_sync_event`` so ``process_single_object_sync``
    runs hermetically.

    ``get_token_return`` controls what ``redis_client.get(token_key)``
    returns during the verification step at db_sync.py:675. Pass the
    expected token for the happy-path; pass anything else (or ``None``)
    to drive the supersede branch.

    ``find_one_doc`` controls what the (Mongo) collection's ``find_one``
    returns. Pass ``None`` to drive the not-found branch.
    """
    redis_client = MagicMock(name="redis_client")
    redis_client.get.return_value = get_token_return

    mongo_db = MagicMock(name="mongo_db")
    mongo_db.__getitem__.return_value.find_one.return_value = find_one_doc

    monkeypatch.setattr(db_sync, "_get_redis", lambda: redis_client)
    monkeypatch.setattr(db_sync, "_get_mongo_db", lambda: mongo_db)
    monkeypatch.setattr(db_sync.time, "sleep", lambda _: None)
    # Silence the recorder so the assertion focuses on the branch's
    # observable side effects.
    monkeypatch.setattr(
        db_sync, "record_embedding_sync_event", lambda *a, **k: None
    )
    # Belt-and-suspenders: ensure ``get_vector`` is never called via the
    # happy-path machinery. Patch it to raise so accidental fall-through
    # would surface loudly.
    monkeypatch.setattr(
        db_sync,
        "get_vector",
        lambda _: (_ for _ in ()).throw(
            AssertionError(
                "get_vector reached on a debounce-branch test"
            )
        ),
    )
    return redis_client, mongo_db


# ---- 1. Token supersede --------------------------------------------------


class TestTokenSupersedeShortCircuits:
    """Mismatched token → early return, no embedding work."""

    def test_mismatched_token_returns_without_calling_get_vector(
        self, monkeypatch, capsys
    ):
        redis_client, mongo_db = _setup_stubs(
            monkeypatch,
            # Redis returns a NEWER token than the one this job was
            # enqueued with — a newer save happened between enqueue and
            # the 5s debounce window.
            get_token_return="newer-token",
            find_one_doc={"_id": "ignored", "name": "x" * 20},
        )

        db_sync.process_single_object_sync(
            "abc123", "lore", "stale-token"
        )

        # The function must short-circuit before touching the doc — the
        # whole point of debounce is that this job's embedding payload
        # is stale.
        mongo_db.__getitem__.return_value.find_one.assert_not_called()
        # No embedding key written.
        redis_client.hset.assert_not_called()

    def test_mismatched_token_logs_supersede_breadcrumb(
        self, monkeypatch, capsys
    ):
        _setup_stubs(
            monkeypatch,
            get_token_return="newer-token",
            find_one_doc={"_id": "ignored"},
        )

        db_sync.process_single_object_sync(
            "abc123", "lore", "stale-token"
        )

        out = capsys.readouterr().out
        assert "abc123" in out, (
            "supersede breadcrumb must name the doc id so operators "
            "investigating embedding-health can attribute the skip"
        )
        assert "Superseded" in out, (
            "the literal 'Superseded' string is the prod-watch "
            "fingerprint for this branch"
        )

    def test_none_token_response_also_supersedes(self, monkeypatch):
        """``redis.get`` returns ``None`` for a missing key — must also
        be treated as "this job is stale" rather than matching the
        ``token`` arg by accident."""
        redis_client, mongo_db = _setup_stubs(
            monkeypatch,
            get_token_return=None,
            find_one_doc={"_id": "ignored"},
        )

        db_sync.process_single_object_sync("abc123", "lore", "tok")

        mongo_db.__getitem__.return_value.find_one.assert_not_called()
        redis_client.hset.assert_not_called()


# ---- 2. Document not found ------------------------------------------------


class TestNotFoundCleanup:
    """``find_one`` → None → cleanup the embedding cache key + return."""

    def test_not_found_deletes_embedding_key(self, monkeypatch):
        redis_client, mongo_db = _setup_stubs(
            monkeypatch,
            get_token_return="tok",  # matches, so verification passes
            find_one_doc=None,        # but the source doc is gone
        )

        db_sync.process_single_object_sync("abc123", "lore", "tok")

        # Cleanup key shape is ``f"{collection_name}:{object_id}"`` per
        # db_sync.py:692.
        redis_client.delete.assert_called_once_with("lore:abc123")
        # No embedding hash should be written when the source is gone.
        redis_client.hset.assert_not_called()

    def test_not_found_logs_breadcrumb(self, monkeypatch, capsys):
        _setup_stubs(
            monkeypatch,
            get_token_return="tok",
            find_one_doc=None,
        )

        db_sync.process_single_object_sync("abc123", "lore", "tok")

        out = capsys.readouterr().out
        assert "abc123" in out, "not-found breadcrumb must name the doc id"
        assert "not found" in out, (
            "the literal 'not found' string is the prod-watch "
            "fingerprint for this branch"
        )


# ---- 3. Negative-space sanity --------------------------------------------


class TestHappyPathStillReachable:
    """Sanity check: with a matching token and a present doc whose
    content meets the threshold, the function reaches the embedding
    step. Negative-space pin against a refactor that accidentally
    early-returns from one of the new gates."""

    def test_matching_token_and_present_doc_calls_get_vector(
        self, monkeypatch
    ):
        # Don't use the suite-shared stubs (which patch get_vector to
        # raise on call) — wire the stubs manually so get_vector is the
        # observed call.
        redis_client = MagicMock(name="redis_client")
        redis_client.get.return_value = "tok"
        mongo_db = MagicMock(name="mongo_db")
        mongo_db.__getitem__.return_value.find_one.return_value = {
            "_id": "abc123",
            "name": "a-name-well-above-the-ten-char-threshold",
            "history": "",
            "associations": [],
        }
        monkeypatch.setattr(db_sync, "_get_redis", lambda: redis_client)
        monkeypatch.setattr(db_sync, "_get_mongo_db", lambda: mongo_db)
        monkeypatch.setattr(db_sync.time, "sleep", lambda _: None)
        monkeypatch.setattr(
            db_sync, "record_embedding_sync_event", lambda *a, **k: None
        )
        get_vector_spy = MagicMock(return_value=None)
        monkeypatch.setattr(db_sync, "get_vector", get_vector_spy)

        db_sync.process_single_object_sync("abc123", "lore", "tok")

        # The embedding step ran — the new tests can't have moved the
        # short-circuit gate too eagerly.
        get_vector_spy.assert_called_once()
        # And the not-found cleanup did NOT fire.
        redis_client.delete.assert_not_called()
