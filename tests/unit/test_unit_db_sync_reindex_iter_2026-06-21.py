"""Independent committed tests for the #183 bulk-reindex fix.

Issue #183: repopulating an emptied RAG store walks every object calling
``request_indexing`` once per object. On a single worker the queue drains
far slower than the ``sync_token:<coll>:<pk>`` key's 300s TTL (~5-20s per
object), so by the time most jobs run their token has expired and
``r.get(token_key)`` returns ``None``. The old verification guard
(``if current_active_token != token: skip``) treated ``None`` the same as
a genuinely-newer token and silently no-opped the reindex past the first
~15 objects.

The fix in ``src/autonomous/db/db_sync.py`` changes the guard to:

    if current_active_token is not None and current_active_token != token:
        skip

so an absent/expired token (``None``) PROCESSES while a *different,
still-live* token still SKIPS — preserving the real-time supersede-dedup.
It also parameterizes the token TTL via ``SYNC_TOKEN_TTL_SECONDS``
(default ``300``) read live through ``config.env_int``.

These tests are written from the diff + issue independently of the dev
agent's gitignored ephemeral tests. They cover all three guard branches
of ``process_single_object_sync`` plus the TTL knob on
``request_indexing``:

  (a) None / expired token  -> PROCESSES (find_one called, no supersede)
  (b) different LIVE token  -> SKIPS    (find_one/hset not called, log)
  (c) matching token        -> PROCESSES (find_one called)

``_get_redis()`` uses ``decode_responses=True``, so ``redis.get`` returns
a ``str`` or ``None`` on the wire — the stubs below mirror that.
"""

import importlib
from unittest.mock import MagicMock

from autonomous.db import db_sync


# A doc whose user content clears MIN_CONTENT_CHARS so that, once a job
# falls through the supersede guard, it reaches get_vector / hset rather
# than short-circuiting on the low-content gate. Lets the "processes"
# branches assert on the embedding step, not just on find_one.
_RICH_DOC = {
    "_id": "abc123",
    "name": "a-name-comfortably-above-the-content-threshold",
    "history": "some history text",
    "associations": [],
}


def _setup_process_stubs(monkeypatch, *, get_token_return, find_one_doc):
    """Wire ``_get_redis`` / ``_get_mongo_db`` / ``time.sleep`` /
    ``record_embedding_sync_event`` / ``get_vector`` so
    ``process_single_object_sync`` runs hermetically.

    ``get_token_return`` is what ``redis_client.get(token_key)`` returns
    at the verification step — a ``str`` for a live token, ``None`` for an
    expired/absent one (decode_responses=True semantics).

    Returns ``(redis_client, mongo_db, get_vector_spy)``.
    """
    redis_client = MagicMock(name="redis_client")
    redis_client.get.return_value = get_token_return

    mongo_db = MagicMock(name="mongo_db")
    mongo_db.__getitem__.return_value.find_one.return_value = find_one_doc

    monkeypatch.setattr(db_sync, "_get_redis", lambda: redis_client)
    monkeypatch.setattr(db_sync, "_get_mongo_db", lambda: mongo_db)
    monkeypatch.setattr(db_sync.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        db_sync, "record_embedding_sync_event", lambda *a, **k: None
    )
    # get_vector returns None so ``if vector:`` is False and the numpy
    # import inside that block (db_sync.py:780) is never reached — numpy
    # is deliberately kept out of autonomous.db's import graph and is NOT
    # installed in the unit-CI env. A spy (not a bare lambda) so "processed"
    # branches can still assert the embedding step was reached via
    # get_vector being CALLED; the actual hash write is the embedding
    # concern, covered by the batch tests, not the supersede-guard concern
    # these tests pin. Matches the established pattern in
    # test_unit_db_sync_batch_iter_2026_05_13.py.
    get_vector_spy = MagicMock(return_value=None)
    monkeypatch.setattr(db_sync, "get_vector", get_vector_spy)
    return redis_client, mongo_db, get_vector_spy


# ---- process_single_object_sync: the three guard branches ----------------


class TestExpiredTokenProcesses:
    """(a) None / expired / absent token -> PROCESS (the #183 bug fix).

    A bulk reindex outlasts the token TTL; the woken job sees ``None`` and
    must index, not skip. This is the branch that was inverted before the
    fix."""

    def test_none_token_falls_through_to_find_one(self, monkeypatch):
        _, mongo_db, _ = _setup_process_stubs(
            monkeypatch,
            get_token_return=None,
            find_one_doc=_RICH_DOC,
        )

        db_sync.process_single_object_sync("abc123", "lore", "tok")

        # Fell through the supersede guard and looked the doc up.
        mongo_db.__getitem__.return_value.find_one.assert_called_once()

    def test_none_token_does_not_log_supersede(self, monkeypatch, capsys):
        _setup_process_stubs(
            monkeypatch,
            get_token_return=None,
            find_one_doc=_RICH_DOC,
        )

        db_sync.process_single_object_sync("abc123", "lore", "tok")

        out = capsys.readouterr().out
        assert "Superseded" not in out, (
            "an expired/absent token is aged out, not superseded — "
            "reporting it as a supersede was the #183 bug"
        )

    def test_none_token_reaches_the_embedding_step(self, monkeypatch):
        """End-to-end for the bug branch: an expired token must drive the
        job all the way to the embedding step (``get_vector``) rather than
        bowing out at the supersede guard — that is the recovery path #183
        restores for a wiped store.

        The actual ``lore:<id>`` hash write is the embedding concern (it
        needs the numpy/vector path, covered by the batch tests); the
        supersede-guard fix this file pins is fully demonstrated by the job
        reaching ``get_vector`` after a ``None`` token."""
        _, mongo_db, get_vector_spy = _setup_process_stubs(
            monkeypatch,
            get_token_return=None,
            find_one_doc=_RICH_DOC,
        )

        db_sync.process_single_object_sync("abc123", "lore", "tok")

        # Looked the doc up and reached the embedding step — i.e. it
        # processed instead of skipping.
        mongo_db.__getitem__.return_value.find_one.assert_called_once()
        get_vector_spy.assert_called_once()


class TestDifferentLiveTokenSkips:
    """(b) different, still-live token -> SKIP (real-time dedup preserved).

    A rapid re-save overwrote the key with a fresh live token; the stale
    in-flight job must bow out so the newest job carries the index."""

    def test_different_live_token_does_not_find_one(self, monkeypatch):
        redis_client, mongo_db, get_vector_spy = _setup_process_stubs(
            monkeypatch,
            get_token_return="newer-live-token",
            find_one_doc=_RICH_DOC,
        )

        db_sync.process_single_object_sync("abc123", "lore", "stale-token")

        mongo_db.__getitem__.return_value.find_one.assert_not_called()
        get_vector_spy.assert_not_called()
        redis_client.hset.assert_not_called()

    def test_different_live_token_logs_supersede(self, monkeypatch, capsys):
        _setup_process_stubs(
            monkeypatch,
            get_token_return="newer-live-token",
            find_one_doc=_RICH_DOC,
        )

        db_sync.process_single_object_sync("abc123", "lore", "stale-token")

        out = capsys.readouterr().out
        assert "Superseded" in out and "abc123" in out, (
            "a genuinely-superseded job must log the supersede breadcrumb "
            "naming the doc id"
        )


class TestMatchingTokenProcesses:
    """(c) matching token -> PROCESS (unchanged happy path)."""

    def test_matching_token_finds_and_reaches_embedding(self, monkeypatch):
        _, mongo_db, get_vector_spy = _setup_process_stubs(
            monkeypatch,
            get_token_return="tok",
            find_one_doc=_RICH_DOC,
        )

        db_sync.process_single_object_sync("abc123", "lore", "tok")

        mongo_db.__getitem__.return_value.find_one.assert_called_once()
        get_vector_spy.assert_called_once()


# ---- request_indexing: the SYNC_TOKEN_TTL_SECONDS knob -------------------


def _setup_request_stubs(monkeypatch):
    """Patch ``db_sync._get_redis`` and the lazily-imported ``AutoTasks``
    so ``request_indexing`` runs without Redis/RQ. Returns the redis
    client mock so the test can inspect ``.set`` call kwargs."""
    redis_client = MagicMock(name="redis_client")
    monkeypatch.setattr(db_sync, "_get_redis", lambda: redis_client)
    # request_indexing does `from autonomous.taskrunner.autotasks import
    # AutoTasks, TaskPriority` at call time, so patch on that module.
    from autonomous.taskrunner import autotasks
    monkeypatch.setattr(autotasks, "AutoTasks", MagicMock(name="AutoTasks"))
    return redis_client


def _ttl_ex_kwarg(redis_client) -> int:
    """Pull the ``ex=`` kwarg from the recorded ``redis.set`` call."""
    redis_client.set.assert_called_once()
    return redis_client.set.call_args.kwargs["ex"]


class TestSyncTokenTTLKnob:
    """``request_indexing`` writes the supersede token with an
    env-configurable TTL (``SYNC_TOKEN_TTL_SECONDS``, default 300)."""

    def test_default_ttl_is_300(self, monkeypatch):
        monkeypatch.delenv("SYNC_TOKEN_TTL_SECONDS", raising=False)
        redis_client = _setup_request_stubs(monkeypatch)

        db_sync.request_indexing("abc123", "lore")

        assert _ttl_ex_kwarg(redis_client) == 300, (
            "default TTL must reproduce the legacy hardcoded ex=300"
        )

    def test_env_override_sets_ttl(self, monkeypatch):
        monkeypatch.setenv("SYNC_TOKEN_TTL_SECONDS", "600")
        redis_client = _setup_request_stubs(monkeypatch)

        db_sync.request_indexing("abc123", "lore")

        assert _ttl_ex_kwarg(redis_client) == 600, (
            "SYNC_TOKEN_TTL_SECONDS must drive the Redis key TTL — read "
            "live via env_int, no restart"
        )

    def test_malformed_ttl_falls_back_to_300(self, monkeypatch):
        # env_int (#49) returns the default on an unparseable value rather
        # than raising — a typo must not break indexing.
        monkeypatch.setenv("SYNC_TOKEN_TTL_SECONDS", "not-a-number")
        redis_client = _setup_request_stubs(monkeypatch)

        db_sync.request_indexing("abc123", "lore")

        assert _ttl_ex_kwarg(redis_client) == 300, (
            "a malformed SYNC_TOKEN_TTL_SECONDS must fall back to 300 via "
            "env_int, not raise"
        )

    def test_empty_ttl_falls_back_to_300(self, monkeypatch):
        # An empty string is the other env_int fallback path (distinct
        # from 'unset' and from 'malformed').
        monkeypatch.setenv("SYNC_TOKEN_TTL_SECONDS", "")
        redis_client = _setup_request_stubs(monkeypatch)

        db_sync.request_indexing("abc123", "lore")

        assert _ttl_ex_kwarg(redis_client) == 300

    def test_ttl_read_live_per_call(self, monkeypatch):
        """The TTL is read per call (mirrors _throttle_window_seconds), so
        flipping the env between two calls changes the second TTL without
        a restart."""
        redis_client = _setup_request_stubs(monkeypatch)

        monkeypatch.setenv("SYNC_TOKEN_TTL_SECONDS", "120")
        db_sync.request_indexing("abc123", "lore")
        first = redis_client.set.call_args.kwargs["ex"]

        monkeypatch.setenv("SYNC_TOKEN_TTL_SECONDS", "900")
        db_sync.request_indexing("abc123", "lore")
        second = redis_client.set.call_args.kwargs["ex"]

        assert (first, second) == (120, 900), (
            "TTL must be re-read each call, not cached at import"
        )


class TestSyncTokenTTLConfigSpec:
    """The knob is cataloged in config._SPEC so it surfaces in the
    generated env reference / validation rather than being an undocumented
    magic var."""

    def test_sync_token_ttl_in_config_spec(self):
        config = importlib.import_module("autonomous.config")
        env_keys = {f.env for f in config._SPEC}
        assert "SYNC_TOKEN_TTL_SECONDS" in env_keys, (
            "SYNC_TOKEN_TTL_SECONDS must be registered in config._SPEC so "
            "it is documented and validated like other env knobs"
        )
