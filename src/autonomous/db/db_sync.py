import os
import threading
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Literal, get_args

import bson
import pymongo
import requests

from autonomous import log
from autonomous.config import env_float, env_int
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


# Default lifetime of a ``sync_token:<coll>:<pk>`` key (#183). The token
# only has to outlive the real-time dedup window — the 5s debounce plus a
# margin for a rapid second save to overwrite it — so the legacy 300s is
# generous and preserved as the default. It is NOT a correctness gate on
# bulk reindex anymore: as of #183 an expired/absent token falls through
# to process rather than skipping, so a backlog that outlasts the TTL
# still indexes. The knob exists so operators can widen the dedup window
# (e.g. on a deployment with bursty, closely-spaced saves) without a
# code change.
_DEFAULT_SYNC_TOKEN_TTL_SECONDS = 300


def _sync_token_ttl_seconds() -> int:
    """Read the sync-token TTL from env each call so a config flip lands
    without restart (mirrors :func:`_throttle_window_seconds`). Falls back
    to ``_DEFAULT_SYNC_TOKEN_TTL_SECONDS`` when the var is unset, empty, or
    malformed (via the shared ``env_int`` guard, issue #49). Clamped to
    ≥1: redis rejects ``set(ex=0)``, so a zero from a config typo would
    turn every sync request into a RedisError (#220 review)."""
    return max(1, env_int("SYNC_TOKEN_TTL_SECONDS", _DEFAULT_SYNC_TOKEN_TTL_SECONDS))


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


def vector_indexed(doc_cls) -> bool:
    """Whether ``doc_cls`` participates in vector indexing (#215/#220).

    THE shared read of the ``vector_index`` meta key. The ``True``
    default is the leak-safety invariant — an undeclared model must
    index and de-index exactly as every model did before #215 — and it
    is enforced from every gate site (both delete gates,
    ``save(sync=True)``, the enqueue gate, and the worker's hash-write
    check), so the read lives here once rather than as scattered
    literals that can drift.
    """
    return doc_cls._meta.get("vector_index", True)


def _requested_doc_vector_indexed(object_id, collection_name) -> bool:
    """Whether the document behind a sync request may index (#220).

    The enqueue gate's resolver — INSTANCE-accurate and fail-open. It
    reads the document's stored ``_cls`` with a projected point-read
    (in the calling process, the one place the registry is reliably
    populated) and answers from an EXACT registry hit on that class.
    Everything unresolvable answers ``True`` — enqueue, the pre-#220
    behavior — because refusing on a guess is the dangerous direction:
    a collection-wide rule was tried first and refused indexing for an
    indexed subclass whenever the caller's process happened to import
    only the opted-out base (test-gate review). Cases that fail open:
    document not found (the worker's not-found branch cleans up),
    ``_cls`` absent (``allow_inheritance: False`` models — also
    invisible to the worker check; the sweep advice in MIGRATIONS is
    their backstop), and ``_cls`` not registered here. The point-read
    is one ``{"_cls": 1}``-projected ``_id`` lookup, trivial next to
    the save round-trip that precedes every normal call.
    """
    from autonomous.db.base.common import _document_registry

    try:
        query = {"_id": bson.ObjectId(object_id)}
    except (bson.errors.InvalidId, TypeError):
        query = {"_id": object_id}
    doc = _get_mongo_db()[collection_name].find_one(query, {"_cls": 1})
    if not doc:
        return True
    doc_cls_name = doc.get("_cls")
    if not doc_cls_name:
        return True
    doc_cls = _document_registry.get(doc_cls_name)
    if doc_cls is None:
        return True
    return vector_indexed(doc_cls)

# redis, rq, and autonomous.taskrunner are imported lazily inside the
# functions that need them. They live in the [tasks] extra (and numpy
# in [all]); module-top imports here would prevent ORM-only consumers
# from running ``from autonomous.db import Document`` without those
# extras installed. See parallel treatment for numpy in
# process_single_object_sync below.

_redis_client = None
_mongo_client = None
_mongo_db = None
# Guards first construction of the clients above (#273): concurrent first
# callers (RQ worker threads) each built a client and leaked connections.
# Double-checked, so the steady-state read never takes the lock.
_client_lock = threading.Lock()


def _get_redis():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    with _client_lock:
        if _redis_client is None:
            import redis
            from redis.backoff import NoBackoff
            from redis.retry import Retry

            # ``env_float``, not env_int: the natural tuning direction for a
            # DEL on the request path is sub-second. A non-positive value is
            # refused rather than honored — redis-py hands it to
            # ``socket.settimeout``, where 0 switches the socket to
            # non-blocking (every command fails) and a negative raises
            # ValueError inside the worker.
            timeout = env_float("REDIS_SOCKET_TIMEOUT_SECONDS", 2.0)
            if timeout <= 0:
                log(
                    f"[WARNING] _get_redis: REDIS_SOCKET_TIMEOUT_SECONDS="
                    f"{timeout!r} must be > 0; using 2.0"
                )
                timeout = 2.0
            _redis_client = redis.Redis(
                host=os.getenv("REDIS_HOST", "cachedb"),
                port=int(os.getenv("REDIS_PORT", 6379)),
                decode_responses=True,
                # Bound the blocking window. ``AutoModel.delete()`` issues a
                # DEL on every delete now, and ``request_indexing`` sets its
                # token on the request path ("MUST BE FAST"), so a host that
                # resolves but blackholes (container network partition)
                # would otherwise hang for minutes per call — redis-py sets
                # no socket timeout by default. deindex's best-effort
                # contract catches the exception but cannot catch the
                # latency; only a timeout can.
                socket_connect_timeout=timeout,
                socket_timeout=timeout,
                # The timeouts alone do NOT bound the call: redis-py's
                # default policy is 3 retries with exponential-plus-jitter
                # backoff, so a refused Redis measured 4.9s per DEL and a
                # blackholed host 4×timeout plus ~3.5s of sleeping. Disabled
                # here so the timeout above is the bound the comment claims.
                # Losing the retries is the right trade for these callers:
                # the worker's failed job is re-queued by RQ, deindex is
                # best-effort by contract, and both would rather fail in 2s
                # than succeed in 15.
                retry=Retry(NoBackoff(), 0),
            )
    return _redis_client


def _index_key(object_id) -> str:
    """Redis key holding one object's vector-index hash.

    Single source of truth for the key shape. It used to be inlined at
    each site, and the two sites disagreed: the writer produced
    ``lore:<pk>`` while the sync worker's not-found self-heal deleted
    ``<collection>:<pk>``, a prefix nothing ever wrote — so the self-heal
    silently cleaned nothing (#204). One helper makes that class of drift
    impossible.
    """
    return f"lore:{object_id}"


def _get_mongo_db():
    global _mongo_client, _mongo_db
    if _mongo_db is not None:
        return _mongo_db
    with _client_lock:
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

      - ``[embeddings]`` extra not installed (sentence-transformers or
        its torch dep missing) → ``ImportError`` →
        ``in_process:ImportError:<module>`` signature where
        ``<module>`` is the failing import (``sentence_transformers``,
        ``torch``, etc.). The library still boots without the extra;
        only callers that flip ``EMBEDDING_AI_AGENT=in_process`` ever
        exercise this path. Distinguishing the missing-module case in
        the signature lets operators tell a forgot-the-extra install
        apart from a partial install (sentence-transformers present
        but torch missing — a real shape, verified locally) without
        opening the log body.
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
        # Catches both "sentence-transformers not installed" AND
        # "sentence-transformers installed but its torch dep is missing"
        # (the latter is a ``ModuleNotFoundError: No module named 'torch'``
        # raised mid-traceback from ``sentence_transformers/util/...``).
        # ``ModuleNotFoundError`` is a subclass of ``ImportError`` so
        # both route here. Including ``e.name`` in the signature lets
        # operators tell the cases apart from the marker alone; the
        # remediation (``pip install autonomous-app[embeddings]``) is
        # the same either way because the extra pulls both transitives.
        missing = getattr(e, "name", None) or "in_process embedding deps"
        record_embedding_sync_event("hpc_failure")
        _emit_hpc_unreachable(
            f"in_process:ImportError:{missing}",
            f"[HPC-UNREACHABLE] in_process embedding failed: "
            f"missing {missing!r} (pip install autonomous-app[embeddings]): {e}",
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


def _extract_world_pk(doc) -> str:
    """Extract a string world pk from a raw mongo document (#132).

    Returns ``""`` for docs that have no ``world`` reference (single-
    tenant installs, world objects themselves, lore that legitimately
    isn't world-scoped). Multi-tenant consumers add a matching
    ``TagField("world_pk")`` to their search_index schema and pass a
    ``@world_pk:{...}`` pre-filter into the KNN query.

    The worker reads the raw BSON via ``pymongo.find_one``, NOT the ORM,
    so ``doc["world"]`` is whatever the field stored on disk — not the
    dereferenced model object. Handles the shapes autonomous's ODM
    writes:

      * ``GenericReferenceField`` (incl. ``ReferenceAttr``):
        ``SON({"_cls": "ClassName", "_ref": DBRef(coll, ObjectId(...))})``
      * ``ReferenceField``: a bare ``DBRef`` or, with ``dbref=False``, a
        bare ``ObjectId``.
      * Already-string pk (e.g. a non-MongoEngine consumer schema).
      * ``None`` / missing.

    Dereference is **not** performed here — the worker is meant to be
    Mongo-light and pulling the world doc would double its database
    round-trips. The pk string is all the consumer needs for the
    ``@world_pk:{...}`` tag filter; humans never read this field.
    """
    world = doc.get("world")
    if world is None:
        return ""
    if isinstance(world, dict):
        # GenericReferenceField shape: {"_cls": ..., "_ref": DBRef}.
        # ``.get`` rather than ``[]`` because partially-written docs in
        # the wild may carry one key without the other; an empty string
        # is safer than raising from an observability path.
        ref = world.get("_ref")
        if ref is not None and hasattr(ref, "id"):
            return str(ref.id)
        # Last-ditch fallback: an unexpected dict shape gets stringified
        # so we still emit *something* the operator can grep. Unknown
        # shapes are programmer error elsewhere, not this function's
        # problem to raise on — but we DO log it, because a silent
        # degraded write into the consumer's tag-filter would otherwise
        # be invisible in storyteller's /debug/lore/health.
        if ref is not None:
            log(
                f"[WARNING] _extract_world_pk: unexpected `_ref` shape "
                f"{type(ref).__name__}={ref!r}; emitting str(ref) as "
                "world_pk — multi-world KNN may degrade"
            )
            return str(ref)
        return ""
    # Plain DBRef (ReferenceField with dbref=True, the default).
    if hasattr(world, "id"):
        return str(world.id)
    # ObjectId, string pk, or anything else stringifiable.
    return str(world)


class _TextExtractor(HTMLParser):
    # convert_charrefs (the default) already unescapes &amp; etc.
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _plain(html) -> str:
    """Strip HTML to whitespace-collapsed text for embedding (#269)."""
    parser = _TextExtractor()
    parser.feed(html or "")
    parser.close()
    return " ".join(" ".join(parser.parts).split())


def _association_names(db, associations) -> list[str]:
    """Resolve raw association values to entity names (#269), in order.

    Refs (``{"_cls", "_ref": DBRef}`` or a bare ``DBRef``) are resolved
    with one ``$in`` find per collection; ``None``, dangling refs and
    bare ObjectIds (no collection to look in) are skipped. Plain strings
    are kept as-is.
    """
    refs = [a.get("_ref") if isinstance(a, dict) else a for a in associations]
    ids_by_coll = {}
    for ref in refs:
        if isinstance(ref, bson.DBRef):
            ids_by_coll.setdefault(ref.collection, []).append(ref.id)
    names = {}
    for coll, ids in ids_by_coll.items():
        for row in db[coll].find({"_id": {"$in": ids}}, {"name": 1}):
            if row.get("name"):
                names[(coll, row["_id"])] = str(row["name"])
    out = []
    for ref in refs:
        if isinstance(ref, bson.DBRef):
            name = names.get((ref.collection, ref.id))
        else:
            name = ref if isinstance(ref, str) else None
        if name:
            out.append(name)
    return out


def process_single_object_sync(object_id, collection_name, token, debounce=True):
    """
    THE WORKER FUNCTION (Runs in Background).
    It is safe to sleep here because we are not in the web request.

    ``debounce=False`` (#281) skips the 5s wait, for bulk reindex jobs
    where no burst of saves is coming to coalesce. The supersede check
    below still runs, so a real save landing mid-reindex still wins.
    """
    str_id = str(object_id)
    token_key = f"sync_token:{collection_name}:{str_id}"
    r = _get_redis()
    db = _get_mongo_db()

    # 1. THE DEBOUNCE WAIT (Happens in background): gives a burst of
    # rapid re-saves time to overwrite the token, so only the newest job
    # embeds.
    if debounce:
        time.sleep(5)

    # 2. THE VERIFICATION
    # Check if a newer save happened while we slept.
    #
    # The supersede guard dedupes rapid real-time re-saves: a second
    # ``request_indexing`` overwrites ``token_key`` with a fresh token, so
    # the first (now-stale) job sees a *different* live token here and
    # bows out, letting the newest job carry the index forward.
    #
    # The guard must distinguish two ``r.get`` outcomes that both differ
    # from ``token`` (#183):
    #   * a DIFFERENT, still-live token  -> genuinely superseded -> skip;
    #   * ``None`` (the key's 5-min TTL expired, or it was deleted)
    #     -> NOT superseded, just aged out -> process.
    # On a bulk reindex a single worker drains the backlog far slower than
    # the TTL (~5-20s/object vs 300s), so most jobs woke after their
    # token's TTL had lapsed; ``None != token`` then mis-fired the skip and
    # the reindex silently no-opped past the first ~15 objects. Gating the
    # skip on a present-and-different token leaves the real-time dedup
    # intact (a live ``t2`` still supersedes a stale ``t1``) while letting
    # an expired/absent token fall through to execute.
    current_active_token = r.get(token_key)

    if current_active_token is not None and current_active_token != token:
        print(f"Skipping sync for {str_id}: Superseded by a newer save.")
        return

    # 3. THE EXECUTION (Embedding generation)
    from bson.objectid import ObjectId

    # The filter is built once and kept: the existence re-check before
    # the write below (#210) has to look the document up the same way
    # this did, and re-deriving it there would let the two drift.
    try:
        query = {"_id": ObjectId(object_id)}
    except (bson.errors.InvalidId, TypeError):
        query = {"_id": object_id}
    doc = db[collection_name].find_one(query)

    if not doc:
        print(f"Object {object_id} not found in collection '{collection_name}'")
        # Via the helper, not a raw DEL: same key, plus the documented
        # best-effort swallow — a Redis blip here must not fail the job
        # while the opt-out branch below swallows the identical failure.
        deindex(object_id)
        return

    # THE FLAG CHECK (#220), defense-in-depth behind the enqueue-side
    # gate in ``request_indexing``. ``vector_index: False`` is the
    # class-level "never indexed" declaration (#215); a hash written
    # here for an opted-out model would leak permanently, so a job that
    # slipped past the gate (queued before the flag landed, or enqueued
    # from a process whose registry couldn't resolve the collection) is
    # re-checked at the write itself.
    #
    # Best-effort, honestly bounded: the lookup is an EXACT registry
    # hit — never ``get_document``'s fuzzy suffix fallback, which could
    # resolve a stale ``_cls`` to a same-named different class and
    # drive the destructive ``deindex`` below off a guess. A bare
    # ``rq worker`` imports no consumer models, so the registry is
    # typically empty there and this check passes through (printed, not
    # silent); a model with ``allow_inheritance: False`` stores no
    # ``_cls`` at all. Both fall through to indexing — the pre-#220
    # default — which is why the ENQUEUE gate, running where the
    # registry is populated, is the load-bearing one.
    doc_cls_name = doc.get("_cls")
    if doc_cls_name:
        from autonomous.db.base.common import _document_registry

        doc_cls = _document_registry.get(doc_cls_name)
        if doc_cls is None:
            print(
                f"vector_index unverified for {collection_name}:{object_id}: "
                f"_cls {doc_cls_name!r} not registered in this process; "
                "indexing by default"
            )
        elif not vector_indexed(doc_cls):
            # Drop any stale hash a pre-flag save left behind (same
            # cleanup shape as the not-found branch above). ``deindex``
            # carries the documented best-effort swallow, so a Redis
            # blip here cannot fail the job; the event is recorded
            # either way so the health hash sees the skip.
            print(
                f"Skipping embedding for {collection_name}:{object_id}: "
                f"{doc_cls_name} declares vector_index: False"
            )
            deindex(object_id)
            # ``silent_skip`` is shared with the short-content branch —
            # the print above disambiguates per-doc, and with the
            # enqueue gate in place this branch only sees stale queued
            # jobs, so the shared counter stays low-volume. A distinct
            # event would flip the committed valid-event-set pin, which
            # is the test agent's surface.
            record_embedding_sync_event("silent_skip")
            return

    # 2. Construct Searchable Text
    log(doc.get("associations"))

    name = _plain(doc.get("name"))
    history = _plain(doc.get("history"))
    # Public digests only (#269) — never GM-only fields (secrets,
    # gm_notes, ...). Digest goes FIRST so it survives the embedder's
    # 256-word-piece truncation; the history tail is what gets cut.
    digest = " ".join(x for x in (
        _plain(doc.get("desc_summary") or (doc.get("desc") or doc.get("description") or "")[:400]),
        _plain(doc.get("backstory_summary")),
    ) if x)
    related = ", ".join(_association_names(db, (doc.get("associations") or [])[:20]))

    # Threshold is computed on actual user content only. The previous
    # `len(searchable_text) < 10` check ran AFTER the f-string below
    # added a literal "Related: " prefix, so the branch never fired on
    # empty docs in production (fixed #48). Threshold value lives in
    # MIN_CONTENT_CHARS at module top (#56).
    content_chars = name + digest + history + related
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

    searchable_text = f"{name}: {digest}\nRelated: {related}\n{history}"

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
        # The doc was read BEFORE get_vector()'s multi-second HTTP call.
        # A delete landing in that window issues its DEL first, and
        # nothing re-enqueues an index job for a deleted pk — so the
        # hash below would resurrect the vector permanently (#210).
        # Re-check existence immediately before the write; the
        # ``{"_id": 1}`` projection keeps it a covered-index lookup and
        # reuses the same filter the original lookup used.
        #
        # ponytail: a check, not a lock. A delete landing between this
        # find_one and the hset still resurrects — closing that needs a
        # Redis-side compare-and-set (or a tombstone key the writer
        # honors), which is not worth it for a window this short. What
        # shipped narrows the exposure from seconds to microseconds.
        if db[collection_name].find_one(query, {"_id": 1}) is None:
            print(
                f"Object {object_id} deleted during embedding; "
                "skipping index write"
            )
            return

        # numpy is only needed when actually writing a vector — keep it
        # out of the autonomous.db import-time graph so consumers that
        # don't use vector embeddings (most ORM usage) can install
        # without it.
        import numpy as np
        world_pk = _extract_world_pk(doc)
        _get_redis().hset(
            _index_key(object_id),
            mapping={
                "mongo_id": str(object_id),
                "collection": collection_name,  # Useful for debugging
                "content": searchable_text,
                "vector": np.array(vector, dtype=np.float32).tobytes(),
                "last_synced": datetime.now(timezone.utc).isoformat(),
                # World/tenant discriminator (#132). Empty string for
                # single-world consumers and for docs without a ``world``
                # reference; multi-world consumers (StoryTeller) add a
                # ``TagField("world_pk")`` to their search_index schema
                # and pass a ``@world_pk:{...}`` pre-filter into the KNN
                # query to keep retrieval world-scoped. Additive: the
                # field is always written, but single-world reads ignore
                # it and the wire shape is unchanged for them.
                "world_pk": world_pk,
            },
        )
        # Counter must follow the hset — only count writes that landed.
        # If hset raises, the worker's existing degrade path takes over.
        record_embedding_sync_event("success")
        print(f"Successfully Indexed: {doc.get('name')}")


def deindex(object_id) -> bool:
    """Remove one object's vector-index entry. Best-effort, never raises.

    The inverse of ``request_indexing`` — called by ``AutoModel.delete``
    so a deleted document stops answering KNN queries instead of leaking
    its embedding forever (#204, #205). Deletion is immediate rather than
    enqueued: it's a single ``DEL`` with nothing to debounce, and routing
    it through the low-priority queue would leave the stale vector
    readable for the length of the backlog.

    Returns True when the key was deleted (or was already gone), False
    when Redis could not be reached. Every failure is swallowed and
    logged: the Mongo document is the source of truth and its delete has
    already happened, so an unreachable Redis must not turn a successful
    delete into an exception.

    **A False return leaks that hash permanently.** There is no
    reconciliation path: once the Mongo document is gone nothing calls
    ``request_indexing`` for that pk again, so no future worker will ever
    look at it. Consumers that cannot tolerate the leak need a periodic
    sweep (``FT.SEARCH`` for hashes whose ``mongo_id`` no longer resolves,
    or a tenant-scoped sweep at teardown) — de-indexing at delete time
    reduces the sweep to a backstop, it does not remove the need for one.

    A pending index job for the same pk needs no cancellation. If it has
    not read the document yet it wakes after its debounce, finds no
    document, and takes the not-found branch — which deletes the key this
    function targets. If it is already PAST its lookup and inside
    ``get_vector()``, the existence re-check before its ``hset`` (#210)
    sees the document gone and skips the write. Only a delete landing in
    the microseconds between that re-check and the ``hset`` still
    resurrects the vector; see the ``ponytail:`` note at that write site.
    """
    try:
        _get_redis().delete(_index_key(object_id))
        return True
    except Exception as e:  # noqa: BLE001
        # Deliberately broad: the caller is mid-delete and any failure
        # here — RedisError, a connection timeout, redis not installed
        # (it's an optional extra) — must stay non-fatal.
        # ``log``, not ``print``: base installs without the [tasks]
        # extra fail the ``import redis`` above on EVERY delete, and a
        # print would spam stdout past LOG_LEVEL for all of them.
        # ``[WARNING]`` prefix per this module's convention (see
        # ``record_embedding_sync_event`` / ``_extract_world_pk``):
        # bare ``log()`` emits at DEBUG, and the default LOG_LEVEL is
        # WARNING — without the prefix the one condition an operator
        # must know about (this return leaks the hash permanently, with
        # no reconciliation path) is the one that produces no signal.
        log(f"[WARNING] De-index failed for {_index_key(object_id)}: {e}")
        return False


# One ``DEL`` per this many keys. Not a tunable — see ``deindex_many``.
_DEINDEX_CHUNK = 500

# Consecutive chunk failures before ``deindex_many`` stops trying. One
# failure is a blip worth stepping over; two in a row is an outage, and
# every further chunk then costs a fresh connect timeout on a delete
# Mongo has already committed.
_DEINDEX_MAX_CONSECUTIVE_FAILURES = 2


class DeindexOutcome(int):
    """``bool``-compatible result of :func:`deindex_many` (#215 review).

    Truthiness keeps the documented contract — truthy when every chunk
    landed, falsy otherwise — so existing ``if not deindex_many(...)``
    consumers see no change. ``gave_up`` additionally marks the
    consecutive-failure early return, the actual outage signature: it
    lets the chunked delete funnel's across-calls breaker distinguish
    "Redis is down" (stop paying connect timeouts) from "one chunk
    blipped inside an otherwise-landed call" (keep de-indexing).
    """

    def __new__(cls, ok, gave_up=False):
        self = super().__new__(cls, bool(ok))
        self.gave_up = gave_up
        return self


def deindex_many(object_ids) -> "DeindexOutcome":
    """Remove many objects' vector-index entries. Best-effort, never raises.

    Batch form of :func:`deindex`, called from the QuerySet delete
    funnel (#207) where one bulk or CASCADE delete removes N documents
    at once. Sending N separate ``DEL``s would drop N round-trips into
    the path of a single ``delete_many`` — and each one is bounded by
    ``REDIS_SOCKET_TIMEOUT_SECONDS``, so an unreachable Redis would
    cost N×2s on a delete that has already succeeded. redis-py's
    ``delete`` is variadic: a chunk is one round-trip and one
    server-side command.

    Chunked rather than one giant ``DEL`` because that command is O(N)
    and runs to completion on Redis's single thread, with the whole
    argument list buffered on both ends. Capping the chunk keeps a
    100k-document teardown from stalling every other Redis client;
    N/500 round-trips is still the right order of magnitude versus N.

    Same contract as :func:`deindex` — truthy when every chunk landed,
    falsy when any could not be sent, and a falsy return leaks those
    hashes permanently (see :func:`deindex` for why nothing reconciles
    them afterwards). The return is a :class:`DeindexOutcome`, whose
    ``gave_up`` flag additionally distinguishes the
    consecutive-failure early return (outage) from an isolated blip.

    Two failure shapes, handled differently. A single chunk failing is a
    blip: the loop steps over it, because every key it skips leaks with
    nothing to reconcile it, and 0.3.171 disabled redis-py's retry policy
    so even a momentary error surfaces here immediately. Redis being
    *down*, though, fails chunk 1 and chunk 200 alike — and with retries
    off, each of those pays a fresh ``socket_connect_timeout`` against a
    host that is not answering. Continuing would put N/500×2s of blocking
    on a delete Mongo already committed (~6.7 min for a 100k-document
    teardown), which is the very cost the batching exists to avoid. So
    the loop steps over isolated failures but gives up after
    ``_DEINDEX_MAX_CONSECUTIVE_FAILURES`` in a row, logging what it never
    attempted so the leak is sweepable.
    """
    keys = [_index_key(object_id) for object_id in object_ids]
    if not keys:
        # The common case for a filtered bulk delete that matched
        # nothing. Return before ``_get_redis()`` so an empty delete
        # neither builds a client nor pays a round-trip.
        return DeindexOutcome(True)
    ok = True
    consecutive_failures = 0
    for start in range(0, len(keys), _DEINDEX_CHUNK):
        chunk = keys[start : start + _DEINDEX_CHUNK]
        try:
            # Per chunk, not around the loop: an isolated failure must
            # not abandon the chunks after it.
            _get_redis().delete(*chunk)
            consecutive_failures = 0
        except Exception as e:  # noqa: BLE001
            # Deliberately broad, and logged at ``[WARNING]``, for exactly
            # the reasons spelled out in ``deindex`` above.
            log(f"[WARNING] De-index failed for {len(chunk)} keys ({chunk[0]}, ...): {e}")
            ok = False
            consecutive_failures += 1
            if consecutive_failures >= _DEINDEX_MAX_CONSECUTIVE_FAILURES:
                unattempted = len(keys) - (start + len(chunk))
                log(
                    f"[WARNING] De-index abandoned after "
                    f"{consecutive_failures} consecutive chunk failures; "
                    f"{unattempted} key(s) never attempted"
                )
                return DeindexOutcome(False, gave_up=True)
    return DeindexOutcome(ok)


def request_indexing(object_id, collection_name, debounce=True):
    """
    THE TRIGGER FUNCTION (Runs in Main App).
    MUST BE FAST. NO SLEEPING HERE.

    Pass ``debounce=False`` from a bulk reindex (#281): the worker then
    skips its 5s coalescing wait, which otherwise dominates a large
    reindex (~9.5h for ~6.8k docs vs ~3 min of embedding).
    """
    # THE ENQUEUE GATE (#220). This is the load-bearing enforcement of
    # ``vector_index: False``: it runs in the process that imported the
    # model (so the registry can resolve the document's stored class),
    # unlike the worker, whose re-check is defense-in-depth that a bare
    # ``rq worker``'s empty registry cannot honor. Skipping here also
    # spares the queue the 5s debounce stall per no-op job.
    #
    # Its own try, failing OPEN: a gate error must enqueue (the
    # pre-#220 behavior), never raise through ``save(sync=True)`` after
    # the Mongo commit, and never be mistaken for the umbrella's
    # "couldn't enqueue" False. The skip is logged and counted under
    # ``silent_skip`` — a bulk skip printed to stdout only would be
    # invisible to the health hash and to LOG_LEVEL-filtered logs.
    try:
        if not _requested_doc_vector_indexed(object_id, collection_name):
            log(
                f"Skipping sync request for {collection_name}:{object_id}: "
                "its model declares vector_index: False"
            )
            record_embedding_sync_event("silent_skip")
            return False
    except Exception as e:  # noqa: BLE001 — fail open, never block an index
        log(f"[WARNING] vector_index enqueue gate errored (indexing anyway): {e}")

    print("Requesting Indexing...")

    str_id = str(object_id)
    token_key = f"sync_token:{collection_name}:{str_id}"

    # 1. GENERATE NEW TOKEN
    current_token = str(uuid.uuid4())

    # 2. SAVE TOKEN TO REDIS + 3. ENQUEUE THE TASK (both instant)
    # TTL governs the real-time supersede-dedup window (#183), not bulk
    # reindex correctness — env-configurable via SYNC_TOKEN_TTL_SECONDS.
    #
    # One umbrella for the whole request (#220): the enqueue always
    # reported an unreachable Redis as ``return False``, but the token
    # ``set`` above it sat outside the try — so the same outage instead
    # raised ``redis.ConnectionError`` up through ``save(sync=True)``
    # for a document Mongo had already committed. Deliberately broad,
    # like the delete side: the lazy imports (an ORM-only install
    # without the ``[tasks]`` extra), a malformed ``REDIS_PORT``, and
    # auth/config RedisErrors all land here too, logged at [WARNING] so
    # a standing misconfiguration is visible in the logs operators
    # actually watch — a bare print was the old sole signal.
    try:
        # Lazy imports — see module-top comment. ``import redis`` doubles
        # as the [tasks]-extra probe: on an ORM-only install it raises
        # here, inside the umbrella, instead of at module import time.
        import redis  # noqa: F401
        from autonomous.taskrunner.autotasks import AutoTasks, TaskPriority

        task_runner = AutoTasks()
        _get_redis().set(token_key, current_token, ex=_sync_token_ttl_seconds())
        # Only sent when opted out, so a default job's payload is
        # unchanged and a not-yet-upgraded worker can still run it.
        extra = {} if debounce else {"debounce": False}
        task_runner.task(
            process_single_object_sync,  # The function to run later
            object_id=str_id,
            collection_name=collection_name,
            token=current_token,
            priority=TaskPriority.LOW,
            **extra,
        )
        return True
    except Exception as e:  # noqa: BLE001 — never raise post-Mongo-commit
        log(f"[WARNING] Sync request failed for {collection_name}:{str_id}: {e}")
        # A token that landed before the enqueue failed would make an
        # in-flight predecessor job skip itself as "superseded" while no
        # successor exists — best-effort removal keeps the older job
        # authoritative.
        try:
            _get_redis().delete(token_key)
        except Exception:  # noqa: BLE001
            pass
        return False
