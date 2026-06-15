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
from autonomous.config import env_int
from autonomous.http import HttpClient
from autonomous.observability import counter

# Module-level HTTP client for the media_ai embeddings POST (#50 slice D).
# Pre-migration this was ``_HTTP_SESSION = requests.Session()`` with
# ``_HTTP_SESSION.post`` invoked at the embedding call site. HttpClient holds
# its own internal requests.Session so connection pooling is preserved
# across the RQ worker's process lifetime; the swap brings db_sync onto
# the same HTTP shape as autoauth (#50 slice B) and local_model (#50
# slice C).
#
# Defaults:
# - ``timeout=None``: the call site below already passes ``timeout=30``;
#   no client-level default needed (would only conflict).
# - ``max_attempts=1``: preserves pre-migration no-retry behavior. The
#   embedding sync is best-effort — the function's contract is "return
#   None on any failure" — and the RQ taskrunner re-queues failed jobs
#   at its layer.
# - ``transport_error_cls=requests.RequestException``: keeps transport-
#   class failures catchable by the existing ``except Exception`` block
#   AND by future callers writing ``except requests.RequestException``.
#   Per slice C's /code-review finding: HttpClient's default
#   ``TransportError`` is a ``RuntimeError`` subclass; without this
#   override, connection / 5xx failures would bypass the catch contract
#   most call sites expect.
#
# Tests monkeypatch ``autonomous.db.db_sync._HTTP`` (or ``_HTTP.post``)
# to a stub. The pre-migration ``_HTTP_SESSION`` patch target is NOT
# preserved as an alias — same reasoning as slice C: HttpClient routes
# through ``session.request("POST", ...)`` rather than
# ``session.post(...)``, so a stale ``_HTTP_SESSION.post`` patch would
# silently no-op. Honest break; the lockstep test updates are in the
# same PR as this migration.
_HTTP = HttpClient(
    timeout=None,
    max_attempts=1,
    transport_error_cls=requests.RequestException,
)

# Per-process log throttle for ``[HPC-UNREACHABLE]`` prints (#39).
# OPT-IN via ``HPC_UNREACHABLE_THROTTLE_SECONDS`` env var — default 0
# (disabled). During a sustained upstream degradation StoryTeller
# observed ~60 identical-signature prints per 24h drowning unrelated
# signal; operators can set the env var (e.g. ``60``) to enable
# per-signature deduplication within that window. Within the window:
# first occurrence prints verbatim; subsequent occurrences increment a
# suppression counter and the next print outside the window includes
# ``(N suppressed in last Ws)``.
#
# Default-off keeps existing observability tests passing unchanged —
# each ``[HPC-UNREACHABLE]`` print fires exactly as before until ops
# enable the throttle. Granularity is per-process, not per-worker-
# cluster: a worker restart clears throttle state, which matches the
# goal (operators care about steady-state floods, not the first batch
# after restart). The upstream-health counter
# (``record_embedding_sync_event``) is NEVER throttled regardless of
# this setting — every failure still counts in the Redis bucket so the
# health dashboard remains accurate.
_HPC_UNREACHABLE_LAST_LOGGED: dict[str, float] = {}
_HPC_UNREACHABLE_SUPPRESSED: dict[str, int] = {}

# Process-wide counter for HPC-unreachable events (#51 slice 2).
# Bumped on every emit attempt — including throttle-suppressed ones —
# so dashboards see the true rate even when the printed-line stream is
# silenced. The Redis hour-bucket counter
# (``record_embedding_sync_event``) is unchanged; this is the in-process
# observability layer that will eventually replace it once a Redis
# backend lands for ``autonomous.observability.Counter``.
_HPC_UNREACHABLE_COUNTER = counter(
    "hpc_unreachable_total",
    description="HPC transport-class failures (db_sync embedding path)",
    label_names=("signature",),
)

# Process-wide counter for embedding-sync state transitions (#51 step 4).
# Bumped on every valid event from ``record_embedding_sync_event`` —
# independent of the Redis hour-bucket write, so a Redis blip is visible
# as a counter-vs-bucket-count divergence rather than as a metric gap.
# The Redis hour-bucket (``embedding_sync_health:<YYYYMMDDHH>``) is
# preserved for back-compat with the storyteller /debug/lore/health
# scraper; consumers migrate to this in-process Counter (and any future
# Redis/Prometheus backend) over time.
_EMBEDDING_SYNC_EVENTS_COUNTER = counter(
    "embedding_sync_events_total",
    description="Embedding sync state transitions (success/hpc_failure/silent_skip)",
    label_names=("event",),
)


def _throttle_window_seconds() -> int:
    """Read the throttle window from env each call so a config flip
    lands without restart. Returns 0 (disabled) when the var is unset
    or malformed.

    Uses the shared ``autonomous.config.env_int`` guard (issue #49) — the
    bespoke try/except this replaced was the poster-child for the missing
    central parser. ``env_int`` reads ``os.environ`` live on each call, so
    the no-restart semantics are preserved.
    """
    return env_int("HPC_UNREACHABLE_THROTTLE_SECONDS", 0)


def _emit_hpc_unreachable(signature: str, message: str) -> None:
    """Print an ``[HPC-UNREACHABLE]`` line, optionally throttled, and
    bump the in-process counter (#51 slice 2).

    With ``HPC_UNREACHABLE_THROTTLE_SECONDS=0`` (the default) the
    message prints verbatim — identical to the pre-#39 contract.

    With the env var set to a positive integer N, prints are
    per-signature throttled within an N-second window. ``signature``
    keys the throttle bucket — pick something stable across the same
    failure class (e.g. ``"openai:HPCUnreachableError"``,
    ``"local:http:500"``) so the dedup actually fires. New error
    shapes should use a distinct signature so they print on first
    occurrence rather than being swept into an unrelated bucket.

    The Counter (``hpc_unreachable_total``) is bumped on every call —
    INCLUDING throttle-suppressed ones — so dashboards see the true
    rate even when the printed-line stream is silenced. This matches
    the existing contract that ``record_embedding_sync_event`` is
    never throttled.

    The printed-line wire shape (raw stdout, no logger banner,
    ``[HPC-UNREACHABLE]`` prefix at line-start) is load-bearing for
    existing scrapers (storyteller ``/debug/lore/health``) and is
    pinned by committed tests; this slice intentionally does NOT
    re-route through ``observability.event()`` because the structured
    line shape (``[MARKER] event=<name> key=value ...``) is
    incompatible with that contract. A later slice can flip the wire
    shape once scrapers are migrated; for now the Counter is the
    structured observability layer.
    """
    # Best-effort — a metrics-layer failure must not replace the
    # in-flight HPC error. The swallow logs the exception so a latent
    # ``Counter.inc`` bug isn't permanently invisible.
    try:
        _HPC_UNREACHABLE_COUNTER.inc(signature=signature)
    except Exception as exc:  # noqa: BLE001
        log(f"[db_sync] hpc_unreachable_total counter inc failed: {exc!r}")

    window = _throttle_window_seconds()
    if window <= 0:
        # Throttle disabled — print verbatim, preserves old behavior.
        print(message)
        return
    now = time.monotonic()
    last = _HPC_UNREACHABLE_LAST_LOGGED.get(signature)
    if last is not None and (now - last) < window:
        _HPC_UNREACHABLE_SUPPRESSED[signature] = (
            _HPC_UNREACHABLE_SUPPRESSED.get(signature, 0) + 1
        )
        return
    suppressed = _HPC_UNREACHABLE_SUPPRESSED.pop(signature, 0)
    if suppressed:
        print(
            f"{message} ({suppressed} suppressed in last {window}s)"
        )
    else:
        print(message)
    _HPC_UNREACHABLE_LAST_LOGGED[signature] = now

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
    # Bump the in-process Counter for every valid event (#51 step 4).
    # Bumped BEFORE the Redis write so a Redis blip is visible as a
    # counter-vs-bucket divergence rather than as a metric gap. Best-
    # effort, matching the function's no-raise / no-control-flow
    # contract — a Counter failure must not surface to the caller.
    try:
        _EMBEDDING_SYNC_EVENTS_COUNTER.inc(event=event)
    except Exception as exc:  # noqa: BLE001
        try:
            log(
                f"[db_sync] embedding_sync_events_total counter inc "
                f"failed for event={event!r}: {exc!r}"
            )
        except Exception:
            pass
    try:
        r = redis_client if redis_client is not None else _get_redis()
        key = bucket_key_for()
        # Pipeline both ops into one Redis round-trip. transaction=False
        # skips MULTI/EXEC — the two ops are commutative for the
        # consumer's HGETALL view (counter increment + TTL refresh order
        # doesn't matter), so the extra latency of a transaction would
        # buy nothing. pipe.execute() raises into the surrounding
        # try/except so the best-effort contract is preserved.
        with r.pipeline(transaction=False) as pipe:
            pipe.hincrby(key, event, 1)
            pipe.expire(key, _EMBEDDING_SYNC_HEALTH_TTL_SECONDS)
            pipe.execute()
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
        resp = _HTTP.post(
            f"{_media_url()}/embeddings", json={"text": text}, timeout=30
        )
        # In production HttpClient's raise_for_status fires on non-2xx
        # before this point, so the ``status_code == 200`` check is
        # effectively dead code there. It stays as defense-in-depth for
        # test contexts that patch ``_HTTP.post`` directly with a mock
        # response — those bypass HttpClient's internal wrapping entirely
        # and rely on the in-flow check to emit the marker. Without it,
        # ``_get_vector_local`` would silently call ``.json()["embedding"]``
        # on a MagicMock and return the mock value instead of ``None``.
        if resp.status_code == 200:
            return resp.json()["embedding"]
        # Mock-driven non-200 path: same signature shape as pre-migration.
        record_embedding_sync_event("hpc_failure")
        _emit_hpc_unreachable(
            f"local:http:{resp.status_code}",
            f"[HPC-UNREACHABLE] local embedding failed: HTTP {resp.status_code}",
        )
    except requests.HTTPError as e:
        # Production non-transport 4xx (HttpClient.raise_for_status path).
        # Preserve the per-status-code signature the pre-migration
        # in-flow non-200 branch emitted — the consumer dashboard regex
        # matches on ``local:http:{code}``.
        record_embedding_sync_event("hpc_failure")
        status = e.response.status_code if e.response is not None else "unknown"
        _emit_hpc_unreachable(
            f"local:http:{status}",
            f"[HPC-UNREACHABLE] local embedding failed: HTTP {status}",
        )
    except Exception as e:
        # Transport-class (5xx + connection failures, wrapped by HttpClient
        # into the configured transport_error_cls=requests.RequestException)
        # OR anything else (KeyError on .json(), etc.). Unwrap one level
        # of ``__cause__`` so the signature reports the original requests
        # exception class (e.g. ``ConnectionError`` rather than the
        # generic ``RequestException``) when HttpClient wrapped a lower-
        # level adapter exception. 5xx-from-status raises don't carry a
        # ``__cause__``, so the wrapper class surfaces directly there —
        # documented behavior change vs the pre-migration in-flow signature
        # (see MIGRATIONS.md entry for #50 slice D).
        underlying = e.__cause__ if e.__cause__ is not None else e
        record_embedding_sync_event("hpc_failure")
        _emit_hpc_unreachable(
            f"local:exc:{type(underlying).__name__}",
            f"[HPC-UNREACHABLE] local embedding failed: "
            f"{type(underlying).__name__}: {underlying}",
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
        _emit_hpc_unreachable(
            "openai:HPCUnreachableError",
            f"[HPC-UNREACHABLE] openai embedding failed: {e}",
        )
        return None
    except Exception as e:
        # Same sentinel for unexpected errors so any HPC-path failure
        # surfaces under one marker family.
        record_embedding_sync_event("hpc_failure")
        _emit_hpc_unreachable(
            f"openai:exc:{type(e).__name__}",
            f"[HPC-UNREACHABLE] openai embedding failed "
            f"(unexpected {type(e).__name__}): {e}",
        )
        return None


def _get_vector_mock(text):
    """Deterministic stub for tests. Matches MockAIModel.get_embedding."""
    return [1.0] + [0.0] * 383


# Lazy per-process singleton for the sentence-transformers model
# (issue #125). The encoder is heavy — ~80MB model + torch — and the
# first ``SentenceTransformer(...)`` call takes seconds. Pinning it
# at module-scope (rather than reinstantiating per call) is what makes
# the in-process path competitive with the network path in latency.
_IN_PROCESS_EMBEDDER = None


def _default_in_process_model() -> str:
    """Default sentence-transformers model id for the in-process backend.

    ``sentence-transformers/all-MiniLM-L6-v2`` is 384-dim, ~80MB, and
    matches the StoryTeller vector index's pinned dimension
    (``search_index``, 384 FLOAT32 COSINE — see #125). Operators
    override via ``LOCAL_EMBEDDING_MODEL`` when an index uses a
    different dim or they want a stronger model (e.g.
    ``all-mpnet-base-v2`` for 768-dim).
    """
    return os.getenv(
        "LOCAL_EMBEDDING_MODEL",
        "sentence-transformers/all-MiniLM-L6-v2",
    )


def _get_in_process_embedder():
    """Return the per-process sentence-transformers model, loading it
    on first call. Raises ``ImportError`` when the ``[embeddings]``
    extra is not installed; the caller (``_get_vector_in_process``)
    translates that into the standard ``[HPC-UNREACHABLE]`` degrade
    path so the worker doesn't crash.
    """
    global _IN_PROCESS_EMBEDDER
    if _IN_PROCESS_EMBEDDER is None:
        # Lazy import: sentence_transformers + torch are large
        # (~700MB on Linux) and not installed by default. Consumers
        # opt in via ``pip install autonomous-app[embeddings]``.
        from sentence_transformers import SentenceTransformer

        _IN_PROCESS_EMBEDDER = SentenceTransformer(_default_in_process_model())
    return _IN_PROCESS_EMBEDDER


def _get_vector_in_process(text):
    """In-process embedding backend (#125).

    No network call — eliminates the external-endpoint single point of
    failure that ``_get_vector_local`` (media_ai HTTP) and
    ``_get_vector_openai`` (HPC) carry. The model is lazily loaded per
    process and pinned for the worker's lifetime via
    ``_IN_PROCESS_EMBEDDER``.

    Failure modes follow the same ``hpc_failure`` /
    ``[HPC-UNREACHABLE]`` sentinel contract as the other providers
    (#60, #65) so dashboards can grep a single marker family:

      - ``[embeddings]`` extra not installed → ``ImportError`` →
        ``in_process:ImportError`` signature. The library still boots
        without the extra; only callers that flip
        ``EMBEDDING_AI_AGENT=in_process`` ever exercise this path.
      - model load error or encode exception →
        ``in_process:exc:<ExcType>`` signature.

    Return value: ``list[float]`` on success (sentence-transformers
    returns ``numpy.ndarray``; ``.tolist()`` is the documented stable
    conversion to plain Python floats for the downstream
    ``np.array(..., dtype=np.float32).tobytes()`` path).
    """
    try:
        embedder = _get_in_process_embedder()
        vec = embedder.encode(text)
        return vec.tolist()
    except ImportError as e:
        record_embedding_sync_event("hpc_failure")
        _emit_hpc_unreachable(
            "in_process:ImportError",
            f"[HPC-UNREACHABLE] in_process embedding failed: "
            f"sentence-transformers not installed "
            f"(pip install autonomous-app[embeddings]): {e}",
        )
        return None
    except Exception as e:
        record_embedding_sync_event("hpc_failure")
        _emit_hpc_unreachable(
            f"in_process:exc:{type(e).__name__}",
            f"[HPC-UNREACHABLE] in_process embedding failed: "
            f"{type(e).__name__}: {e}",
        )
        return None


_VECTOR_PROVIDERS = {
    "local": _get_vector_local,
    "openai": _get_vector_openai,
    "in_process": _get_vector_in_process,
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
