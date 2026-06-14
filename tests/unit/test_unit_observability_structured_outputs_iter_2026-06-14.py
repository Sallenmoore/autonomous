"""Independent committed coverage for PR #119 / issue #51 steps 3+4.

PR #119 migrates two `log()` emission sites onto the `observability`
foundation (slice 1+2's `event()` / `Counter` / `Registry`) and adds
the first metric-backed wrapper:

**Step 3 — `[STRUCTURED-OUTPUTS-UNAVAILABLE]` emission migration.**
Both `autonomous.ai.models.local_model.generate_json` and
`autonomous.ai.models.openai_compat.generate_json` switch their
fallback log from `log(...)` to `observability.event(...)` with the
`STRUCTURED-OUTPUTS-UNAVAILABLE` marker, then bump a shared
`structured_outputs_unavailable_total` Counter labeled by `provider`
(`"local"` / `"openai_compat"`). The Counter is the same singleton in
both modules — by-name lookup in the observability registry returns
the existing Counter on the second `counter(...)` call.

**Step 4 — `record_embedding_sync_event` Counter wrapper.**
`autonomous.db.db_sync.record_embedding_sync_event` now bumps an
`embedding_sync_events_total` Counter (label: `event`) BEFORE the
Redis hour-bucket write. The Redis blip ⇒ Counter-vs-bucket
divergence design — bumping after Redis would mean a Redis blip is
just a metric gap, indistinguishable from an absence of events.

Independent perspective (no peek at dev's `tests/_dev_local/`):

- Counter API contract pins: the documented `name` + `label_names`
  for both new counters.
- Singleton sharing: the registry's idempotent-by-name semantic means
  both adapter modules see the same `Counter` object — verified by
  identity, not just by-value equality.
- Grep-compat contract: the line `event()` writes via `log` starts
  with `[STRUCTURED-OUTPUTS-UNAVAILABLE]` so storyteller's grep
  scrapers keep matching after the migration.
- Embedding-sync wrapper: each valid event (`success`,
  `hpc_failure`, `silent_skip`) increments under the right label;
  invalid events do NOT bump (typo-guard contract preserved); Counter
  fires BEFORE Redis (verified by a raise-from-Redis fixture);
  Counter inc failure does not propagate (best-effort observability
  contract — the wrapper's caller must never see an exception from
  the recorder).
- End-to-end via `local_model.generate_json`: a JSON-schema call on
  the first-detection path bumps the shared counter with
  `provider="local"`. Mirrors the existing log-gate test but asserts
  on the new metric surface.
"""

from unittest.mock import MagicMock

import pytest

from autonomous.observability.metrics import Counter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _counter_total(counter, **labels) -> float:
    """Total observed value at the given label combination (0.0 if
    never bumped). Works even when the Counter has been bumped under
    multiple label combinations — we only count the one the caller
    asked about."""
    key = tuple(str(labels.get(n, "")) for n in counter.label_names)
    return counter.collect().get(key, 0.0)


# ---------------------------------------------------------------------------
# Counter API contract: structured_outputs_unavailable_total
# ---------------------------------------------------------------------------


def test_structured_outputs_counter_spec():
    """Pins the documented Counter shape. Renaming the metric or
    re-labeling silently after this lands would break the consumer's
    dashboard query without a CI failure."""
    from autonomous.ai.models import local_model

    c = local_model._STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER
    assert isinstance(c, Counter), (
        f"_STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER must be a Counter, "
        f"got {type(c).__name__}"
    )
    assert c.name == "structured_outputs_unavailable_total", (
        f"metric name is the dashboard contract; got {c.name!r}"
    )
    assert c.label_names == ("provider",), (
        f"label_names must be ('provider',) so consumers can split by "
        f"adapter; got {c.label_names!r}"
    )


def test_structured_outputs_counter_is_shared_singleton_across_modules():
    """Both `local_model` and `openai_compat` declare the same Counter
    name. The observability registry returns the existing Counter on
    the second `counter(...)` call (idempotent-by-name) — without this
    sharing, two adapters would observe into separate series and a
    dashboard query summing both would have to know about each adapter
    individually."""
    from autonomous.ai.models import local_model, openai_compat

    assert (
        local_model._STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER
        is openai_compat._STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER
    ), (
        "Counter must be the SAME object — by-name lookup in the "
        "observability REGISTRY is the documented sharing mechanism; "
        "if they're separate objects, increments from one adapter are "
        "invisible to the other module's view of the series"
    )


# ---------------------------------------------------------------------------
# Counter API contract: embedding_sync_events_total
# ---------------------------------------------------------------------------


def test_embedding_sync_counter_spec():
    """Pins the documented Counter shape for the embedding-sync wrapper."""
    from autonomous.db import db_sync

    c = db_sync._EMBEDDING_SYNC_EVENTS_COUNTER
    assert isinstance(c, Counter)
    assert c.name == "embedding_sync_events_total"
    assert c.label_names == ("event",), (
        f"label_names must be ('event',) so consumers split by "
        f"state-transition kind; got {c.label_names!r}"
    )


# ---------------------------------------------------------------------------
# Grep-compat: event() preserves the [STRUCTURED-OUTPUTS-UNAVAILABLE]
# line-start that storyteller's scrapers key on
# ---------------------------------------------------------------------------


def test_event_marker_renders_at_line_start_for_grep_compat(monkeypatch):
    """The whole point of the `marker=` field is grep-compat: the
    scraper at `storyteller/...health` greps for the bracketed marker
    at line-start, so the migration must preserve that shape. If a
    future refactor of `format_event` moves the marker into the middle
    of the line (or drops the brackets), the scraper goes silent."""
    captured = []
    monkeypatch.setattr(
        "autonomous.log",
        lambda msg, *a, **kw: captured.append(str(msg)),
    )

    from autonomous.observability import event

    event(
        "structured_outputs_unavailable",
        level="warning",
        marker="STRUCTURED-OUTPUTS-UNAVAILABLE",
        print_to_stdout=False,
        provider="local",
        model="m",
        endpoint="http://x",
    )

    assert len(captured) == 1
    line = captured[0]
    assert line.startswith("[STRUCTURED-OUTPUTS-UNAVAILABLE]"), (
        f"line must start with the bracketed marker for greppability; "
        f"got: {line!r}"
    )


def test_event_payload_carries_required_fields():
    """Return value from `event()` is the structured payload consumers
    will eventually consume directly (e.g. `job.meta` attachment in
    RQ-backed callers). Pin the shape so a future refactor doesn't
    quietly drop the `provider`/`model`/`endpoint` fields — or, for
    the openai_compat-specific call site, the operator-grade triage
    fields (`status`, `body_excerpt`, `detection`,
    `cached_for_process`) that the scraper at storyteller's
    `/debug/lore/health` is the most-likely future consumer of."""
    from autonomous.observability import event

    payload = event(
        "structured_outputs_unavailable",
        level="warning",
        marker="STRUCTURED-OUTPUTS-UNAVAILABLE",
        print_to_stdout=False,
        provider="openai_compat",
        model="gpt-x",
        endpoint="http://gw",
        status=400,
        body_excerpt="error: ...",
        detection="first",
        cached_for_process=True,
    )
    assert payload["event"] == "structured_outputs_unavailable"
    assert payload["level"] == "warning"
    assert payload["marker"] == "STRUCTURED-OUTPUTS-UNAVAILABLE"
    assert payload["provider"] == "openai_compat"
    assert payload["model"] == "gpt-x"
    assert payload["endpoint"] == "http://gw"
    # openai_compat-specific operator-triage fields — the call site at
    # ``openai_compat.generate_json`` passes these on the first-
    # detection branch (`detection="first"`, `cached_for_process=True`)
    # alongside the 4xx response body excerpt that makes the
    # unsupported-ness diagnosable.
    assert payload["status"] == 400
    assert payload["body_excerpt"] == "error: ..."
    assert payload["detection"] == "first"
    assert payload["cached_for_process"] is True


# ---------------------------------------------------------------------------
# record_embedding_sync_event Counter behavior
# ---------------------------------------------------------------------------


@pytest.fixture
def _reset_embedding_sync_counter():
    """The counter is process-wide. Reset before and after so tests
    here don't bleed observations into other suites and vice versa."""
    from autonomous.db import db_sync

    db_sync._EMBEDDING_SYNC_EVENTS_COUNTER.reset()
    try:
        yield db_sync._EMBEDDING_SYNC_EVENTS_COUNTER
    finally:
        db_sync._EMBEDDING_SYNC_EVENTS_COUNTER.reset()


@pytest.fixture
def _redis_no_op(monkeypatch):
    """Make ``record_embedding_sync_event``'s Redis path a no-op so
    the test isolates the Counter bump."""
    from autonomous.db import db_sync

    fake_redis = MagicMock(name="redis")
    pipe_cm = MagicMock(name="pipeline_cm")
    pipe = MagicMock(name="pipeline")
    pipe_cm.__enter__.return_value = pipe
    pipe_cm.__exit__.return_value = False
    fake_redis.pipeline.return_value = pipe_cm
    monkeypatch.setattr(db_sync, "_get_redis", lambda: fake_redis)
    return fake_redis


@pytest.mark.parametrize("event_name", ["success", "hpc_failure", "silent_skip"])
def test_record_embedding_sync_bumps_counter_for_each_valid_event(
    event_name, _reset_embedding_sync_counter, _redis_no_op
):
    """The three documented event types each bump the counter once at
    their own label slot — no cross-pollination."""
    from autonomous.db.db_sync import record_embedding_sync_event

    record_embedding_sync_event(event_name)

    assert _counter_total(_reset_embedding_sync_counter, event=event_name) == 1.0
    # Other labels must remain at zero — proves the label isn't
    # silently broadcasting across all event types.
    for other in ("success", "hpc_failure", "silent_skip"):
        if other == event_name:
            continue
        assert _counter_total(_reset_embedding_sync_counter, event=other) == 0.0


def test_record_embedding_sync_does_not_bump_for_invalid_event(
    _reset_embedding_sync_counter, _redis_no_op, monkeypatch
):
    """Typo-guard: an unknown event string must NOT touch the counter.
    The docstring is explicit — `record_embedding_sync_event` returns
    early after the typo log, before any observability surface gets
    touched. If the counter were bumped on typos, dashboards would
    silently absorb programmer errors into the `success`-like aggregate
    and operators would mistake the bug for a real spike."""
    # Suppress the typo-warning log to keep test output clean
    monkeypatch.setattr("autonomous.db.db_sync.log", lambda *a, **kw: None)

    from autonomous.db.db_sync import record_embedding_sync_event

    record_embedding_sync_event("succes")  # typo

    snapshot = _reset_embedding_sync_counter.collect()
    assert snapshot == {}, (
        f"typo event must NOT bump the counter; got {snapshot!r}"
    )


def test_counter_bumped_before_redis_so_redis_blip_leaves_divergence(
    _reset_embedding_sync_counter, monkeypatch
):
    """The contract is "Counter ahead of Redis ⇒ Redis blip; Counter
    matches Redis ⇒ wire is healthy". Verified by making the Redis
    pipeline raise — counter must still reflect the increment.

    If the order ever flipped (counter after Redis), a Redis blip
    would leave the counter at zero AND the Redis bucket missing the
    event — indistinguishable from "this event never happened" — and
    the divergence-detection alert would be silenced.
    """
    from autonomous.db import db_sync

    # Redis pipeline raises on .execute() — simulates a wire failure
    fake_redis = MagicMock(name="redis")
    pipe_cm = MagicMock(name="pipeline_cm")
    pipe = MagicMock(name="pipeline")
    pipe.execute.side_effect = ConnectionError("redis dead")
    pipe_cm.__enter__.return_value = pipe
    pipe_cm.__exit__.return_value = False
    fake_redis.pipeline.return_value = pipe_cm
    monkeypatch.setattr(db_sync, "_get_redis", lambda: fake_redis)

    db_sync.record_embedding_sync_event("success")

    # Counter MUST be incremented even though Redis failed
    assert _counter_total(_reset_embedding_sync_counter, event="success") == 1.0, (
        "counter must be bumped BEFORE the Redis write so a Redis blip "
        "is visible as a counter-vs-bucket divergence; an increment of 0 "
        "here means the order flipped and divergence detection is dead"
    )


def test_counter_inc_failure_does_not_propagate(monkeypatch):
    """Best-effort contract: a Counter failure must not surface to the
    `record_embedding_sync_event` caller — the recorder is an
    observability surface, NOT control flow. A bug in the Counter
    backend (or a future Redis-backed Counter going unreachable) must
    not turn embedding sync into a write barrier."""
    from autonomous.db import db_sync

    # Force the counter's inc() to raise
    broken = MagicMock(spec=db_sync._EMBEDDING_SYNC_EVENTS_COUNTER)
    broken.inc.side_effect = RuntimeError("metric backend dead")
    monkeypatch.setattr(db_sync, "_EMBEDDING_SYNC_EVENTS_COUNTER", broken)

    # Redis path: keep healthy so we isolate the counter failure
    fake_redis = MagicMock(name="redis")
    pipe_cm = MagicMock(name="pipeline_cm")
    pipe_cm.__enter__.return_value = MagicMock()
    pipe_cm.__exit__.return_value = False
    fake_redis.pipeline.return_value = pipe_cm
    monkeypatch.setattr(db_sync, "_get_redis", lambda: fake_redis)
    monkeypatch.setattr("autonomous.db.db_sync.log", lambda *a, **kw: None)

    # Must NOT raise
    db_sync.record_embedding_sync_event("success")

    # Redis write still proceeded after the counter swallowed
    assert fake_redis.pipeline.called, (
        "counter failure must not short-circuit the Redis write — "
        "they're independent best-effort layers"
    )


# ---------------------------------------------------------------------------
# End-to-end: local_model.generate_json bumps the shared counter
# ---------------------------------------------------------------------------


def _local_instance():
    """Bare LocalAIModel without DB persistence. Mirrors the existing
    helper in ``test_unit_local_model_json_schema.py`` — keeping this
    file self-contained so it survives reverts of that file in isolation."""
    from autonomous.ai.models.local_model import LocalAIModel

    inst = LocalAIModel.__new__(LocalAIModel)
    object.__setattr__(
        inst, "_data", {"instructions": "You are a helpful AI.", "name": "test"}
    )
    object.__setattr__(inst, "_dynamic_fields", {})
    object.__setattr__(inst, "_changed_fields", [])
    object.__setattr__(inst, "_initialised", True)
    object.__setattr__(inst, "_created", False)
    return inst


def test_local_model_generate_json_bumps_shared_counter_with_provider_local(
    monkeypatch,
):
    """End-to-end: the JSON-schema-supplied path on `LocalAIModel`
    bumps the shared counter exactly once, labeled `provider="local"`.
    Mirrors the existing log-gate test but asserts on the new metric
    surface — proves the wire-up at the call site, not just the
    Counter API in isolation."""
    from autonomous.ai.models import local_model
    from autonomous.ai.models.local_model import LocalAIModel

    # Fresh detection cache (the gate that decides whether to bump)
    local_model._STRUCTURED_OUTPUTS_LOGGED.clear()
    # Fresh counter snapshot
    local_model._STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER.reset()

    inst = _local_instance()
    object.__setattr__(inst, "_text_model", "test-model")
    object.__setattr__(inst, "_ollama_url", "http://test-host:11434")

    # Suppress event()'s log emission — only the counter matters here
    monkeypatch.setattr("autonomous.log", lambda *a, **kw: None)

    # Short-circuit generate_json after the gate runs
    monkeypatch.setattr(
        local_model._HTTP,
        "post",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("stop")),
    )

    try:
        LocalAIModel.generate_json(inst, "prompt", json_schema={"type": "object"})
    except RuntimeError:
        pass

    bumped = _counter_total(
        local_model._STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER, provider="local"
    )
    assert bumped == 1.0, (
        f"first-detection JSON-schema call must bump the shared counter "
        f"with provider='local'; got {bumped}"
    )

    # Second call on same (model, endpoint): must NOT re-bump (same
    # gate as the log emission). Without this property, the metric
    # would describe per-call traffic, not first-detection.
    try:
        LocalAIModel.generate_json(inst, "prompt2", json_schema={"type": "string"})
    except RuntimeError:
        pass

    bumped = _counter_total(
        local_model._STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER, provider="local"
    )
    assert bumped == 1.0, (
        f"second call on same (model, endpoint) must NOT re-bump — "
        f"counter mirrors the log gate; got {bumped}"
    )

    # Cleanup: don't leak observations into other suites
    local_model._STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER.reset()
    local_model._STRUCTURED_OUTPUTS_LOGGED.clear()
