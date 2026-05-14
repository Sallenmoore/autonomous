import os
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Literal, get_args

import bson
import pymongo
import requests

from autonomous import log

EmbeddingSyncEvent = Literal["success", "hpc_failure", "silent_skip"]
EMBEDDING_SYNC_HEALTH_KEY_PREFIX = "embedding_sync_health"
_EMBEDDING_SYNC_HEALTH_TTL_SECONDS = 7 * 24 * 3600  # 7 days
# Below this content length the embedding would be dominated by the
# template prefix (and by stopwords/punctuation), producing a useless
# vector. Promoted to a module constant in #56 — was a load-bearing
# magic number after #48 made the silent_skip branch reachable.
MIN_CONTENT_CHARS = 10
# Frozenset for O(1) membership in record_embedding_sync_event's guard —
# prevents typo-induced bucket pollution (storyteller's HGETALL-on-named-
# fields read can't distinguish a phantom typo field from a future event,
# so an unknown event with no out-of-band signal silently underreports).
_VALID_EMBEDDING_SYNC_EVENTS = frozenset(get_args(EmbeddingSyncEvent))

# redis, rq, and autonomous.taskrunner are imported lazily inside the
# functions that need them. They live in the [tasks] extra (and numpy
# in [all]); module-top imports here would prevent ORM-only consumers
# from running ``from autonomous.db import Document`` without those
# extras installed. See parallel treatment for numpy in
# process_single_object_sync below.

_redis_client = None
_mongo_client = None
_mongo_db = None


def _get_redis():
    global _redis_client
    if _redis_client is None:
        import redis
        _redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "cachedb"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            decode_responses=True,
        )
    return _redis_client


def _get_mongo_db():
    global _mongo_client, _mongo_db
    if _mongo_db is None:
        password = urllib.parse.quote_plus(str(os.getenv("DB_PASSWORD")))
        username = urllib.parse.quote_plus(str(os.getenv("DB_USERNAME")))
        host = os.getenv("DB_HOST", "db")
        port = os.getenv("DB_PORT", 27017)
        uri = f"mongodb://{username}:{password}@{host}:{port}/?authSource=admin"
        _mongo_client = pymongo.MongoClient(uri)
        _mongo_db = _mongo_client[os.getenv("DB_DB")]
    return _mongo_db


def bucket_key_for(dt: datetime | None = None) -> str:
    """Return the embedding-sync-health Redis key for ``dt`` (default: now UTC).

    Key shape: ``embedding_sync_health:<YYYYMMDDHH>`` (UTC hour bucket).

    Consumers (e.g. storyteller's ``/debug/lore/health``) that parse these
    keys should call this helper rather than re-deriving the strftime
    format — pins the wire contract in one place. Pass an explicit ``dt``
    when reading historical buckets; default is now (UTC).

    When passing an explicit ``dt``, the caller is responsible for
    ensuring it is UTC. A naive datetime (no ``tzinfo``) emits a one-line
    WARNING and is treated as wall-clock — the resulting key may
    mis-align with what the recorder wrote from a non-UTC zone. Pass
    ``datetime.now(timezone.utc)`` or a converted UTC datetime to be
    safe. The helper does not raise on naive datetimes so existing
    callers keep working through the deprecation window.
    """
    if dt is not None and dt.tzinfo is None:
        # Best-effort warning, not an exception: callers passing naive
        # datetimes today must keep working, but the contract violation
        # should leave a breadcrumb that root-causes wrong-hour keys.
        # The autonomous logger always emits at DEBUG regardless of
        # level= kwarg (see logger.py:22); encode severity in the
        # message prefix so log scrapers and humans see it.
        try:
            log(
                f"[WARNING] bucket_key_for: naive datetime {dt!r} "
                "treated as wall-clock; pass a UTC-aware datetime "
                "to avoid mis-aligned keys"
            )
        except Exception:
            # Symmetry with record_embedding_sync_event — a logger
            # failure must not propagate from an observability path.
            pass
    effective = dt if dt is not None else datetime.now(timezone.utc)
    bucket = effective.strftime("%Y%m%d%H")
    return f"{EMBEDDING_SYNC_HEALTH_KEY_PREFIX}:{bucket}"


def record_embedding_sync_event(event: EmbeddingSyncEvent, redis_client=None) -> None:
    """Record an embedding-sync event in a Redis hour-bucketed counter.

    Storage shape:
        HASH ``embedding_sync_health:<YYYYMMDDHH>`` with integer counts
        in fields ``success`` / ``hpc_failure`` / ``silent_skip``.

    TTL is refreshed to 7 days on every HINCRBY, so each hash key
    self-expires a week after its last write — bounded storage without
    a separate sweeper.

    Multi-worker safe by construction: every RQ worker increments the
    same shared hash; no in-process state, no cross-worker drift.
    Survives worker restarts (the original deferral reason on #31 was
    that an in-process counter loses signal on exactly the failure
    modes — OOM, segfault, deploy — operators most need to see).

    Best-effort: any failure (Redis unreachable, [tasks] extra absent,
    network blip) is silently swallowed. Unknown ``event`` strings are
    a no-op for the Redis write (prevents typo-induced bucket pollution
    that the consumer's named-field read would otherwise underreport),
    but emit a one-line WARNING log so the typo is attributable at the
    call site — programmer-error swallowing is categorically different
    from infrastructure-failure swallowing and gets a breadcrumb. The
    recorder is an observability surface, NOT control flow — callers
    must not change behavior based on whether the record landed.
    Alerting on observability gaps lives in the consumer's monitoring
    layer, not here.

    Args:
        event: One of ``"success"``, ``"hpc_failure"``, ``"silent_skip"``.
            Other values produce a WARNING log and no Redis write.
        redis_client: Optional injected client. Defaults to the shared
            module client returned by :func:`_get_redis`. Consumers
            mirroring writes to a separate Redis can pass their own.
    """
    if event not in _VALID_EMBEDDING_SYNC_EVENTS:
        # Log the typo (programmer error) but don't write to Redis —
        # see docstring. Preserves the no-raise / no-control-flow
        # contract while restoring forensic attribution. The pre-PR-#52
        # behavior was a phantom HINCRBY field that left a Redis-side
        # breadcrumb; the guard added in #46 removed that without a
        # replacement signal. This log line is the replacement.
        try:
            # The autonomous logger always emits at DEBUG regardless of
            # level= kwarg (see logger.py:22); encode severity in the
            # message prefix so log scrapers and humans see it.
            log(
                f"[WARNING] record_embedding_sync_event: unknown event "
                f"{event!r}; valid: {sorted(_VALID_EMBEDDING_SYNC_EVENTS)}"
            )
        except Exception:
            # The log itself is best-effort — a logger failure must not
            # propagate and turn the observability surface into a
            # control-flow surface. See the module-level docstring on
            # best-effort contract.
            pass
        return
    try:
        r = redis_client if redis_client is not None else _get_redis()
        key = bucket_key_for()
        r.hincrby(key, event, 1)
        r.expire(key, _EMBEDDING_SYNC_HEALTH_TTL_SECONDS)
    except Exception:
        # See docstring — best-effort observability. A recorder failure
        # MUST NOT surface in the worker's log, stderr, or return path,
        # because doing so would couple worker reliability to a purely
        # diagnostic substrate.
        pass


def _media_url() -> str:
    return os.getenv("MEDIA_API_BASE_URL", "http://media_ai:5005")


def _get_vector_local(text):
    """Legacy media_ai HTTP path — preserved as the local-provider fallback.

    Failure observability is symmetric with ``_get_vector_openai``: every
    failure mode (transport exception OR non-200 status OR anything else
    raised from the HTTP stack) bumps the ``hpc_failure`` counter and
    emits a ``[HPC-UNREACHABLE]`` marker. The literal "HPC" name is
    provider-agnostic per the sentinel convention — all provider
    failures share one marker family so log scrapers match a single
    regex (#60).

    The except clause is intentionally a bare ``Exception`` to match
    ``_get_vector_openai`` (#65). The symmetric-observability claim
    above was previously false on non-tuple exceptions raised from
    transport adapters — those propagated uncaught and could kill the
    RQ worker. The function's documented contract is "return None on
    any failure"; programmer-error surfacing is the test suite's job,
    not this observability path.
    """
    try:
        resp = requests.post(
            f"{_media_url()}/embeddings", json={"text": text}, timeout=30
        )
        if resp.status_code == 200:
            return resp.json()["embedding"]
        # Non-200 was previously a silent None-return — no marker, no
        # counter. Surface it under the same marker family as the
        # except-clause case so the consumer dashboard captures both.
        record_embedding_sync_event("hpc_failure")
        print(
            f"[HPC-UNREACHABLE] local embedding failed: HTTP {resp.status_code}"
        )
    except Exception as e:
        record_embedding_sync_event("hpc_failure")
        print(
            f"[HPC-UNREACHABLE] local embedding failed: "
            f"{type(e).__name__}: {e}"
        )
    return None


def _get_vector_openai(text):
    """OpenAI-compatible HPC path. __new__ bypass keeps Mongo out of the
    RQ worker — `get_embedding` only reads class-level config."""
    from autonomous.ai.models.openai_compat import HPCUnreachableError, OpenAIClient

    client = OpenAIClient.__new__(OpenAIClient)
    try:
        return client.get_embedding(text)
    except HPCUnreachableError as e:
        # Returning None is the supported degrade path — the caller
        # tolerates a missing vector (see openai_compat.HPCUnreachableError).
        # The "[HPC-UNREACHABLE]" prefix is a stable observability sentinel;
        # downstream log scrapers match on it, so do not rename without
        # coordinating consumers. The "openai" substring (#66) lets
        # dashboards disambiguate provider in mixed-deployment grep —
        # the local path includes the same word in its marker lines.
        record_embedding_sync_event("hpc_failure")
        print(f"[HPC-UNREACHABLE] openai embedding failed: {e}")
        return None
    except Exception as e:
        # Same sentinel for unexpected errors so any HPC-path failure
        # surfaces under one marker family.
        record_embedding_sync_event("hpc_failure")
        print(
            f"[HPC-UNREACHABLE] openai embedding failed "
            f"(unexpected {type(e).__name__}): {e}"
        )
        return None


def _get_vector_mock(text):
    """Deterministic stub for tests. Matches MockAIModel.get_embedding."""
    return [1.0] + [0.0] * 383


_VECTOR_PROVIDERS = {
    "local": _get_vector_local,
    "openai": _get_vector_openai,
    "mock": _get_vector_mock,
}


def get_vector(text):
    """
    Returns an embedding vector for ``text`` using the provider selected
    by ``EMBEDDING_AI_AGENT`` (default ``local``).

    Returns None on failure so callers can degrade gracefully — the RAG
    layer treats a missing vector as "skip indexing this save".
    """
    provider = os.getenv("EMBEDDING_AI_AGENT", "local")
    fn = _VECTOR_PROVIDERS.get(provider, _get_vector_local)
    return fn(text)


def process_single_object_sync(object_id, collection_name, token):
    """
    THE WORKER FUNCTION (Runs in Background).
    It is safe to sleep here because we are not in the web request.
    """
    str_id = str(object_id)
    token_key = f"sync_token:{collection_name}:{str_id}"
    r = _get_redis()
    db = _get_mongo_db()

    # 1. THE DEBOUNCE WAIT (Happens in background)
    time.sleep(5)

    # 2. THE VERIFICATION
    # Check if a newer save happened while we slept
    current_active_token = r.get(token_key)

    if current_active_token != token:
        print(f"Skipping sync for {str_id}: Superseded by a newer save.")
        return

    # 3. THE EXECUTION (Embedding generation)
    from bson.objectid import ObjectId

    try:
        oid = ObjectId(object_id)
        doc = db[collection_name].find_one({"_id": oid})
    except (bson.errors.InvalidId, TypeError):
        doc = db[collection_name].find_one({"_id": object_id})

    if not doc:
        print(f"Object {object_id} not found in collection '{collection_name}'")
        r.delete(f"{collection_name}:{object_id}")
        return

    # 2. Construct Searchable Text
    log(doc.get("associations"))

    name = doc.get("name") or ""
    history = doc.get("history") or ""
    associations = doc.get("associations") or []

    # Threshold is computed on actual user content only. The previous
    # `len(searchable_text) < 10` check ran AFTER the f-string below
    # added a literal "Related: " prefix, so the branch never fired on
    # empty docs in production (fixed #48). Threshold value lives in
    # MIN_CONTENT_CHARS at module top (#56).
    content_chars = name + history + " ".join(str(a) for a in associations[:20])
    if len(content_chars) < MIN_CONTENT_CHARS:
        # Per-doc log so operators investigating storyteller
        # /debug/lore/health can attribute a silent_skip increment to a
        # specific document (#56). Parallel to the not-found branch
        # above, which has always been loud.
        print(
            f"Skipping embedding for {collection_name}:{object_id}: "
            f"only {len(content_chars)} content chars "
            f"(name={name!r}, threshold={MIN_CONTENT_CHARS})"
        )
        record_embedding_sync_event("silent_skip")
        return

    searchable_text = (
        f"{name}: {history}"
        f"Related: {', '.join([str(a) for a in associations[:20]]) if associations else ''}"
    )

    # 3. Generate Vector
    vector = get_vector(searchable_text)

    # 4. Save to Redis Index
    #
    # No `else` clause on the `if vector:` check by design (#57): each
    # provider in _VECTOR_PROVIDERS is responsible for bumping
    # ``hpc_failure`` on its own failure modes before returning None.
    # Adding a caller-side else would double-count every real failure.
    # See `_get_vector_local` / `_get_vector_openai` for the provider-
    # side observability contract.
    if vector:
        # numpy is only needed when actually writing a vector — keep it
        # out of the autonomous.db import-time graph so consumers that
        # don't use vector embeddings (most ORM usage) can install
        # without it.
        import numpy as np
        _get_redis().hset(
            f"lore:{object_id}",
            mapping={
                "mongo_id": str(object_id),
                "collection": collection_name,  # Useful for debugging
                "content": searchable_text,
                "vector": np.array(vector, dtype=np.float32).tobytes(),
                "last_synced": datetime.now(timezone.utc).isoformat(),
            },
        )
        # Counter must follow the hset — only count writes that landed.
        # If hset raises, the worker's existing degrade path takes over.
        record_embedding_sync_event("success")
        print(f"Successfully Indexed: {doc.get('name')}")


def request_indexing(object_id, collection_name):
    """
    THE TRIGGER FUNCTION (Runs in Main App).
    MUST BE FAST. NO SLEEPING HERE.
    """
    print("Requesting Indexing...")

    # Lazy imports — see module-top comment.
    import redis
    from autonomous.taskrunner.autotasks import AutoTasks, TaskPriority

    # Initialize the Task Runner
    task_runner = AutoTasks()

    str_id = str(object_id)
    token_key = f"sync_token:{collection_name}:{str_id}"

    # 1. GENERATE NEW TOKEN
    current_token = str(uuid.uuid4())

    # 2. SAVE TOKEN TO REDIS (Instant)
    _get_redis().set(token_key, current_token, ex=300)

    # 3. ENQUEUE THE TASK (Instant)
    try:
        task_runner.task(
            process_single_object_sync,  # The function to run later
            object_id=str_id,
            collection_name=collection_name,
            token=current_token,
            priority=TaskPriority.LOW,
        )
        return True
    except (redis.RedisError, ConnectionError) as e:
        print(f"Sync Enqueue failed: {e}")
        return False
