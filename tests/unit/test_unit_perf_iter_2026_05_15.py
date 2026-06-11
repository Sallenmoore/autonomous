"""Tests for the iter/2026-05-15 perf batch (PR #76).

Independent test-agent coverage for the five-optimization batch.
Each class targets a behavioral angle dev's regression-pin tests
in the iter/2026-05-15 file family did NOT cover from a fresh
perspective.

- **(A) HTTP Session reuse** — `_HTTP_SESSION` (db_sync) and
  `_SESSION` (local_model, openai_compat) are module-level
  `requests.Session()` objects. Dev's
  `test_unit_http_session_pooling.py` pins that the session is
  *used* via the new attribute name; this file pins the harder
  *identity* contract — the same object across calls within a
  module — which is what actually delivers the TCP+TLS handshake
  reuse the PR claims. A fresh `Session()` per call would pass
  dev's "uses the Session" test but defeat the perf optimization.

- **(B) Redis pipelining in `record_embedding_sync_event`** —
  Dev's pipelining test pins "two commands in one round trip";
  this file pins `transaction=False` is the actual kwarg (a
  drive-by to `transaction=True` would re-introduce MULTI/EXEC
  overhead the PR specifically called out as unnecessary) and
  pins pipeline-`execute()`-raise is swallowed (best-effort
  observability symmetric with the rest of the recorder's
  contract).

- **(C) `AutoModel.load_model()` memoization** — Dev's tests pin
  cache hits, case-insensitivity, invalidation, and miss-not-
  cached as a *property*. This file pins the *positive
  consequence* of miss-not-cached: after a cache hit on name
  `"X"`, registering a new subclass `Y` (a likely production
  pattern with dynamic model loading) is still findable on the
  next `load_model("Y")` call. The pre-cache behavior had this
  for free (every call walked subclasses); a buggy
  implementation that cached the whole tree on first hit would
  silently break it.

- **(D) Retry jitter** — Dev's tests pin the happy path
  (multiplier applied, validation rejects out-of-range, no
  random call when jitter=0). This file pins the boundary:
  `jitter` near 1.0 must never produce a NEGATIVE sleep
  duration (a regression that allowed jitter==1.0 or computed
  `1 - jitter` wrongly would either crash `time.sleep` or
  reduce reliability under contention — the very scenario
  jitter was added to handle).

- **(E) `BaseAgent.get_client(persist=False)`** — Dev's tests
  pin the persist semantics (skip save, skip delete-of-old).
  This file pins resilience: `persist=False` when there's NO
  old client to delete must not crash (the delete-skip branch
  needs to be guarded by the existence check, not just the
  persist flag).
"""

import random
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# (A) HTTP Session — same-object identity across calls
# ===========================================================================


class TestHttpSessionIdentity:
    """Pin: each module's session attribute IS a ``requests.Session``
    (post-PR-#76 shape, not bare ``requests``) AND is the same object
    on repeated access (catches the unusual case where a future
    refactor exposes it as a property/__getattr__ that returns a
    fresh Session). The behavioral coverage that the session is
    USED inside actual calls is provided by dev's
    ``test_unit_http_session_pooling.py``; this file adds the
    identity-level pin that the SAME Session is reused — which is
    what delivers TCP+TLS handshake reuse.

    Cross-module distinctness is NOT pinned here — the PR doesn't
    claim each module must own its own Session, and a future
    "shared Session per base-url" refactor would be a legitimate
    design choice."""

    def test_each_module_exposes_a_session_attr_with_stable_identity(self):
        # Consolidated test: each module has the new pooled-HTTP attr
        # (proving the PR #76 shape landed) AND repeated access
        # returns the SAME object (catching the property /
        # __getattr__ shenanigan case — unusual but possible).
        #
        # Type expectation per module:
        # - db_sync, openai_compat: still bare ``requests.Session``
        #   (pre-#50-migration shape).
        # - local_model: migrated to ``HttpClient`` in #50 slice C — the
        #   pooled session lives one layer down at ``_HTTP.session``,
        #   but the identity-stability contract is on ``_HTTP`` itself
        #   (the HttpClient instance must be a singleton).
        import requests
        from autonomous.db import db_sync
        from autonomous.ai.models import local_model, openai_compat
        from autonomous.http import HttpClient

        # Type expectation per module — all three migrated to HttpClient
        # by the close of #50 (slice C: local_model; slice D: db_sync;
        # slice F: openai_compat). Bare ``requests.Session`` no longer
        # appears in any of these modules.

        candidates = [
            ("db_sync", db_sync, "_HTTP", HttpClient),
            ("local_model", local_model, "_HTTP", HttpClient),
            ("openai_compat", openai_compat, "_HTTP", HttpClient),
        ]
        for label, mod, attr, expected_type in candidates:
            obj = getattr(mod, attr)
            assert isinstance(obj, expected_type), (
                f"{label}.{attr} must be a {expected_type.__name__} "
                f"(post-#50 slices C/D/F for HttpClient); "
                f"got: {type(obj).__name__}"
            )
            # Repeated access returns same object — pool-reuse contract.
            assert getattr(mod, attr) is obj, (
                f"{label}.{attr} must return the SAME instance on "
                f"every access; a property/factory would defeat "
                f"connection pooling"
            )


# ===========================================================================
# (B) Redis pipelining — transaction=False explicit + best-effort raise swallow
# ===========================================================================


class TestPipelineContractDetails:
    """Pin: the pipeline is opened with ``transaction=False`` (the
    perf claim is wire-MULTI/EXEC overhead is avoided), AND a
    raise during ``pipe.execute()`` is swallowed (the recorder's
    best-effort observability contract holds — adding pipelining
    must not change that)."""

    def test_pipeline_opened_with_transaction_false(self):
        # The perf comment in the PR explicitly says transaction=False
        # skips unnecessary MULTI/EXEC. A drive-by to True (or just
        # the default) would silently regress the round-trip
        # savings. Pin by inspecting the kwarg passed to
        # `client.pipeline(...)`.
        from autonomous.db import db_sync
        client = MagicMock()
        # The pipeline context manager needs __enter__/__exit__ to
        # behave; we don't care what the pipe does, only what kwargs
        # were used to OPEN it.
        pipe_cm = MagicMock()
        pipe_cm.__enter__ = MagicMock(return_value=pipe_cm)
        pipe_cm.__exit__ = MagicMock(return_value=False)
        client.pipeline.return_value = pipe_cm
        db_sync.record_embedding_sync_event(
            "success", redis_client=client
        )
        # The first (and only) pipeline() call must be transaction=False.
        client.pipeline.assert_called_once()
        _, kwargs = client.pipeline.call_args
        assert kwargs.get("transaction") is False, (
            "pipeline() must be opened with transaction=False per "
            "the perf claim; got kwargs="
            f"{kwargs!r}, args={client.pipeline.call_args.args!r}"
        )

    def test_pipeline_execute_raise_is_swallowed_best_effort(self):
        # The recorder's contract is "best-effort observability —
        # any failure (Redis unreachable, [tasks] extra absent,
        # network blip) is silently swallowed". Adding pipelining
        # broadened the surface where a Redis call can fail — pin
        # that the broader try/except still catches a raise from
        # pipe.execute(). A bug that wrapped only the HINCRBY/EXPIRE
        # calls but not execute() would propagate.
        from autonomous.db import db_sync
        client = MagicMock()
        pipe_cm = MagicMock()
        pipe_cm.__enter__ = MagicMock(return_value=pipe_cm)
        pipe_cm.__exit__ = MagicMock(return_value=False)
        pipe_cm.execute = MagicMock(
            side_effect=RuntimeError("Redis dropped mid-execute")
        )
        client.pipeline.return_value = pipe_cm
        # MUST NOT raise. If it does, control flow propagates to the
        # AI agents that call the recorder — turning the
        # observability surface into a fragile leg of the AI path.
        db_sync.record_embedding_sync_event(
            "hpc_failure", redis_client=client
        )
        # And: execute was actually attempted (proves the test
        # exercises the post-construction failure path, not a pre-
        # construction guard).
        pipe_cm.execute.assert_called_once()


# ===========================================================================
# (C) load_model cache — forward-compat after first cache hit
# ===========================================================================


class TestLoadModelCacheForwardCompat:
    """Pin the positive consequence of "misses not cached" (#76's
    invariant): after a cache hit on one model name, registering a
    new subclass and calling ``load_model`` for it still works.
    Dev's test pins the property; this pins the *user-observable
    consequence* that depends on it."""

    @pytest.fixture(autouse=True)
    def _isolate_cache(self):
        from autonomous.model.automodel import AutoModel
        AutoModel._invalidate_load_model_cache()
        yield
        AutoModel._invalidate_load_model_cache()

    def test_new_subclass_findable_after_warm_cache_hit_on_another(self):
        from autonomous.model.automodel import AutoModel

        class _AlreadyKnown(AutoModel):
            pass

        # Prime cache on one name.
        first = AutoModel.load_model("_AlreadyKnown")
        assert first is _AlreadyKnown
        # Now register a NEW subclass post-cache-hit. If the cache
        # had stored the whole subclass tree (rather than name→class
        # entries) on the first miss-then-hit, this new class would
        # be invisible.

        class _RegisteredLater(AutoModel):
            pass

        second = AutoModel.load_model("_RegisteredLater")
        assert second is _RegisteredLater, (
            "load_model must find subclasses registered AFTER the "
            "cache was warmed on another name — the cache is per-"
            "name, not a frozen snapshot of the subclass tree"
        )
        # And the original cached entry is still correct.
        assert AutoModel.load_model("_AlreadyKnown") is _AlreadyKnown


# ===========================================================================
# (D) Retry jitter — never produces negative sleep
# ===========================================================================


class TestJitterNeverNegative:
    """Pin: jitter at the upper bound of its valid range never
    causes a negative sleep duration. The formula is
    ``sleep * uniform(1 - jitter, 1 + jitter)``. The validation
    rejects ``jitter >= 1.0`` precisely so that ``1 - jitter > 0``;
    a regression to ``jitter <= 1.0`` (off-by-one in the bound)
    would let jitter=1.0 produce a sleep of exactly zero (harmless
    but inert) AND raise a math concern if someone "fixed" the
    bound to `<=` thinking it should be inclusive."""

    def test_jitter_just_below_one_keeps_sleep_positive(self, monkeypatch):
        # Boundary check: jitter=0.999... must keep the minimum
        # multiplier strictly positive. ``retry`` is a function (not
        # a decorator) — call it with a failing callable and inspect
        # the sleep durations.
        from autonomous.ai import retry as retry_mod

        captured: list[float] = []
        monkeypatch.setattr(
            retry_mod.time, "sleep", lambda s: captured.append(s)
        )
        # Drive `random.uniform(a, b)` to its minimum so we hit the
        # lowest possible multiplier (=1-jitter).
        monkeypatch.setattr(
            retry_mod.random, "uniform", lambda a, b: a
        )

        def _always_fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            retry_mod.retry(
                _always_fail,
                max_attempts=3,
                sleep_seconds=1.0,
                jitter=0.99,
            )

        assert captured, "retry should have invoked sleep at least once"
        for s in captured:
            assert s > 0, (
                f"jitter near 1.0 must keep sleep strictly positive; "
                f"got s={s} (would break time.sleep on some platforms)"
            )

    def test_jitter_is_multiplicative_at_lower_bound(self, monkeypatch):
        # Dev's `test_jitter_positive_multiplies_sleep` pins ONLY the
        # upper bound (uniform → max → 1+jitter). A regression to
        # ADDITIVE jitter (`sleep + uniform(-j, +j)` instead of
        # `sleep * uniform(1-j, 1+j)`) with sleep_seconds=1 would
        # still produce a multiplier-like value and pass dev's
        # 1.0-base happy path. Pin the LOWER bound with a non-unity
        # base to expose the difference:
        #
        #   multiplicative: 4.0 * (1 - 0.5) = 2.0
        #   additive:       4.0 + (-0.5)   = 3.5
        #
        # If the formula ever silently swaps, this test catches it.
        from autonomous.ai import retry as retry_mod

        captured: list[float] = []
        monkeypatch.setattr(
            retry_mod.time, "sleep", lambda s: captured.append(s)
        )
        # Drive uniform to its minimum (1 - jitter).
        monkeypatch.setattr(
            retry_mod.random, "uniform", lambda a, b: a
        )

        def _always_fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            retry_mod.retry(
                _always_fail,
                max_attempts=2,
                sleep_seconds=4.0,
                jitter=0.5,
            )
        assert captured, "retry should have invoked sleep"
        # The exact multiplicative result. Additive would give 3.5.
        assert captured[0] == pytest.approx(2.0), (
            f"jitter must multiply sleep_seconds, not add to it. "
            f"For sleep=4, jitter=0.5, uniform→0.5: multiplicative "
            f"gives 4*0.5=2.0; additive would give 4+(-0.5)=3.5. "
            f"Got: {captured[0]}"
        )


# ===========================================================================
# (E) get_client(persist=False) — re-instantiation log silenced silently
# ===========================================================================


class TestPersistFalseLogAsymmetry:
    """Pin: when ``get_client(persist=False)`` swaps providers, the
    ``"Re-instantiating client..."`` log line still fires (or NOT —
    whatever the current source delivers). The current implementation
    has the log INSIDE ``if self.client and persist:``, so a
    ``persist=False`` provider switch is silent — no log, no Mongo
    trace. Operators investigating ''when did the agent switch
    provider'' lose attribution.

    This test pins the **current** observable behavior so any future
    fix that lifts the log out of the persist gate (or otherwise
    changes log-emission semantics) surfaces a deliberate test
    update. The asymmetry between the persist=True (logged) and
    persist=False (silent) paths is documented as a follow-up
    issue."""

    def _make_stub_agent_and_client_class(self, monkeypatch):
        # Mirror dev's _StubAgent pattern from
        # test_unit_baseagent_get_client_persist.py — bypass
        # AutoModel construction (which needs a Mongo connection).
        from autonomous.ai.baseagent import BaseAgent

        class _OldClient:
            """Old client of a DIFFERENT type than the registered
            'mock' provider — forces the provider-switch slow path.
            Has delete() so persist=True doesn't AttributeError."""
            def delete(self):
                pass

        class _NewClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def save(self):
                pass

            def delete(self):
                pass

        class _StubAgent:
            MODEL_REGISTRY = BaseAgent.MODEL_REGISTRY

            def __init__(self):
                self.provider = "mock"
                self.name = "stub"
                self.instructions = ""
                self.description = ""
                # Wrong type (not _NewClient) — forces slow path.
                self.client = _OldClient()
                self.save_calls = 0

            def save(self):
                self.save_calls += 1

        monkeypatch.setitem(
            BaseAgent.MODEL_REGISTRY, "mock", _NewClient
        )
        return _StubAgent(), BaseAgent

    def test_persist_true_emits_reinstantiation_log(self, monkeypatch):
        # Sanity: legacy path emits the log. If this fails, the test
        # is broken (not the source).
        agent, BaseAgent = self._make_stub_agent_and_client_class(
            monkeypatch
        )
        log_calls = []
        monkeypatch.setattr(
            "autonomous.ai.baseagent.log",
            lambda msg, *a, **k: log_calls.append(msg),
        )
        # Make agent.client truthy-but-wrong-type so we hit the
        # `self.client and persist` branch on persist=True.
        # agent.client already a wrong-type _OldClient from the stub
        BaseAgent.get_client(agent, persist=True)
        assert any(
            "Re-instantiating" in c for c in log_calls
        ), (
            "persist=True provider switch must log re-instantiation "
            "(legacy attribution); pinning the legacy behavior here "
            "so the persist=False asymmetry below has a baseline"
        )

    def test_persist_false_emits_reinstantiation_log_with_orphan_note(
        self, monkeypatch
    ):
        # Post-#79: the log is lifted OUT of the persist gate so
        # provider switches under persist=False are still attributable
        # in the operator log. The message also notes the orphan-doc
        # trade-off ("persist=False: old doc orphaned") so debuggers
        # investigating "where's the old client doc?" have a
        # breadcrumb pointing at the deliberate skip.
        #
        # This test was previously pinned as
        # test_persist_false_currently_silent_on_reinstantiation; it
        # was flipped in lockstep with the #79 fix (the test agent
        # explicitly authorized the flip in the prior class docstring:
        # "this test will start failing and force a deliberate flip").
        agent, BaseAgent = self._make_stub_agent_and_client_class(
            monkeypatch
        )
        log_calls = []
        monkeypatch.setattr(
            "autonomous.ai.baseagent.log",
            lambda msg, *a, **k: log_calls.append(msg),
        )
        BaseAgent.get_client(agent, persist=False)
        reinstantiation_calls = [
            c for c in log_calls if "Re-instantiating" in c
        ]
        assert len(reinstantiation_calls) == 1, (
            f"persist=False provider switch must emit exactly one "
            f"Re-instantiating log line; got: {log_calls}"
        )
        msg = reinstantiation_calls[0]
        assert "persist=False" in msg, (
            "log line should flag that this is the persist=False path "
            "(operators investigating 'where's the old client?' need "
            "the breadcrumb pointing at the orphan-doc trade-off)"
        )
        assert "orphaned" in msg, (
            "log line should mention the old doc is orphaned (the "
            "documented trade-off — not silently deleted)"
        )


# ===========================================================================
# (F) tests/perf/ opt-in discipline — must NOT bleed into default unit run
# ===========================================================================


class TestPerfSuiteIsOptIn:
    """Pin: ``tests/perf/*`` benchmarks are marked ``@pytest.mark.perf``
    and do NOT register in the default ``pytest tests/unit/``
    invocation. A misconfigured marker (or forgetting it on a new
    benchmark) would silently slow every CI run and developer
    workflow to a crawl as the suite grows. The PR explicitly says
    'perf benchmarks don't gate CI because variance on shared GitHub
    runners would flake' — that contract depends on the marker
    discipline being enforced."""

    def test_perf_directory_exists_and_is_a_package(self):
        # Sanity: the new tests/perf/ tree shipped (the perf batch
        # introduces the directory). If it's accidentally dropped
        # from a future cleanup, the perf benchmarks silently stop
        # running on `make test-perf`.
        import pathlib
        perf_dir = pathlib.Path(__file__).resolve().parents[1] / "perf"
        assert perf_dir.is_dir(), (
            f"tests/perf/ should exist after PR #76; got missing: "
            f"{perf_dir}"
        )
        init = perf_dir / "__init__.py"
        assert init.is_file(), (
            "tests/perf/ must be an importable package (have "
            "__init__.py) so pytest collects from it via "
            "`make test-perf`"
        )

    def test_default_pytest_testpaths_excludes_perf(self):
        # The mechanism that keeps perf benchmarks out of CI's bare
        # `pytest` invocation is pyproject.toml's
        # ``testpaths = ["tests/unit"]`` — not the marker. The
        # conftest's ``pytestmark = pytest.mark.perf`` actually only
        # applies to tests defined IN conftest.py (well-known pytest
        # gotcha) and is a no-op for sibling test files. Pin what
        # actually delivers the CI exclusion: the testpaths
        # configuration. A future "simplification" that drops
        # testpaths or adds tests/perf to it would silently make
        # every CI run gate on flaky benchmarks.
        import pathlib
        try:
            import tomllib
        except ImportError:  # pragma: no cover
            import tomli as tomllib  # type: ignore[no-redef]
        pyproject = tomllib.loads(
            (pathlib.Path(__file__).resolve().parents[2]
             / "pyproject.toml").read_text()
        )
        testpaths = (
            pyproject.get("tool", {})
            .get("pytest", {})
            .get("ini_options", {})
            .get("testpaths", [])
        )
        assert testpaths, (
            "pyproject.toml must set [tool.pytest.ini_options] "
            "testpaths to exclude opt-in directories like tests/perf "
            "from the default `pytest` invocation"
        )
        # The contract: tests/perf must NOT be listed.
        assert not any(
            "perf" in tp for tp in testpaths
        ), (
            f"tests/perf/ must NOT be in pytest testpaths; CI would "
            f"then gate on flaky benchmark timings. Got: {testpaths}"
        )

    def test_perf_marker_is_declared_for_explicit_invocation(self):
        # Even though the marker isn't load-bearing for CI exclusion
        # (testpaths is), it MUST be registered in pyproject.toml so
        # `pytest -m perf` and `pytest -m 'not perf'` invocations work
        # without raising "unknown marker" warnings. Drive-by removal
        # of the marker registration would break the documented
        # explicit-invocation interface (`make test-perf`, etc.).
        import pathlib
        try:
            import tomllib
        except ImportError:  # pragma: no cover
            import tomli as tomllib  # type: ignore[no-redef]
        pyproject = tomllib.loads(
            (pathlib.Path(__file__).resolve().parents[2]
             / "pyproject.toml").read_text()
        )
        markers = (
            pyproject.get("tool", {})
            .get("pytest", {})
            .get("ini_options", {})
            .get("markers", [])
        )
        assert any(
            m.startswith("perf:") or m == "perf"
            for m in markers
        ), (
            f"`perf` marker must be registered in "
            f"[tool.pytest.ini_options].markers so `pytest -m perf` "
            f"works without warnings. Got: {markers}"
        )
