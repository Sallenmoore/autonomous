"""Independent coverage for PR #7 (iter/2026-05-26-batch: rq worker +
autotask return_value + CI fixup).

PR #7 ships three roughly-orthogonal slices:

1. ``src/autonomous/taskrunner/autotasks.py`` — new ``AutoTask.return_value``
   property; ``AutoTask.result`` now delegates to ``job.return_value()``
   instead of the deprecated ``job.result`` attribute (silences rq's
   DeprecationWarning).
2. ``tests/docker-compose.yml`` + ``makefile`` — new ``worker`` service
   that runs ``rq worker high default low`` against the cachedb, plus
   an ``inittests`` wait-loop that blocks until the worker is registered.
3. ``requirements_dev.txt`` — adds ``pyyaml``, fixing a CI break the
   previous iter's test file introduced (it imports yaml but pyyaml
   wasn't declared, and CI doesn't install the docs extras that pull
   it in transitively).
4. ``tests/integration/test_int_tasks.py`` — fix two wait-loop bugs
   that polled ``while status == "running"`` (rq never reports that
   string; the loop never entered).

The dev perspective: "I added a worker, fixed two test wait-loops, and
silenced a deprecation by using rq's modern accessor." The test
agent's independent perspective: "is the new public API actually
present + correct, is the worker service actually wired into
docker-compose, and would a future revert of any of these slices
re-introduce the original symptoms?"

Hermetic: a small mock-job fake stands in for ``rq.job.Job`` so
``AutoTask`` can be exercised without a live Redis. Filesystem reads
for the structural pins. No subprocess work other than ``git``-free
file reads.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Any

import pytest
import yaml

from autonomous.taskrunner.autotasks import AutoTask


REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Mock job fake — minimal surface AutoTask actually touches
# ---------------------------------------------------------------------------


class _FakeJob:
    """Stands in for ``rq.job.Job`` so AutoTask can be exercised hermetically.

    Tracks call-counts on ``return_value()`` and ``result`` access so a
    test can prove which side AutoTask actually went through. ``result``
    is a property that raises if the caller bypasses ``return_value()``
    — that's how we detect a regression to the pre-PR-#7 path that the
    deprecation warning was originally complaining about.
    """

    def __init__(self, payload: Any = "fake-payload"):
        self._payload = payload
        self.return_value_calls = 0
        # Defensive: if a test reads .result, we want the test to fail
        # loudly — the new code must go through return_value() exclusively.
        self.result_reads = 0

    def return_value(self):
        self.return_value_calls += 1
        return self._payload

    @property
    def result(self):
        self.result_reads += 1
        return self._payload


# ---------------------------------------------------------------------------
# AutoTask.return_value (new public property)
# ---------------------------------------------------------------------------


class TestAutoTaskReturnValue:
    """The new property is the headline of PR #7's library slice.
    Consumers (storyteller currently) gain a stable accessor that won't
    emit DeprecationWarning when rq finally removes ``Job.result``."""

    def test_return_value_property_exists_on_autotask(self):
        # Descriptor lookup on the class avoids constructing a Job.
        attr = vars(AutoTask).get("return_value")
        assert attr is not None, (
            "AutoTask no longer exposes a return_value property — PR #7's "
            "whole point was to add this as a public accessor. Without "
            "it, downstream consumers have to either (a) use the still-"
            "deprecated .result, or (b) reach into .job.return_value() "
            "directly (which breaks the AutoTask abstraction)."
        )
        assert isinstance(attr, property), (
            "AutoTask.return_value is no longer a @property — losing the "
            "descriptor shape means callers writing `task.return_value` "
            "would need parens, breaking the symmetric `.result`/"
            "`.return_value` accessor convention."
        )

    def test_return_value_proxies_to_job_return_value(self):
        job = _FakeJob(payload={"ok": True})
        task = AutoTask(job)
        assert task.return_value == {"ok": True}
        assert job.return_value_calls == 1, (
            "AutoTask.return_value did not call job.return_value() — the "
            "implementation may have regressed to job.result (deprecated) "
            "or job._result (private)."
        )
        assert job.result_reads == 0, (
            "AutoTask.return_value reached for the deprecated job.result "
            "property — the rq DeprecationWarning will re-surface."
        )

    def test_repeated_access_calls_job_each_time(self):
        """Pin that return_value is not memoised on AutoTask. The
        underlying rq Job stores the value (or fetches lazily from
        Redis), so AutoTask delegating each call avoids stale reads
        when the job hasn't finished yet on the first read."""
        job = _FakeJob(payload="first")
        task = AutoTask(job)
        _ = task.return_value
        job._payload = "second"
        assert task.return_value == "second"
        assert job.return_value_calls == 2


# ---------------------------------------------------------------------------
# AutoTask.result — now delegates to job.return_value() (silences deprecation)
# ---------------------------------------------------------------------------


class TestAutoTaskResultDelegatesToReturnValue:
    """Pre-PR-#7 the property was ``return self.job.result``, which
    triggered ``DeprecationWarning: Job.result is deprecated. Use
    Job.return_value() instead.`` on every read. PR #7 changed it to
    ``return self.job.return_value()`` — backwards-compatible for
    callers but no longer noisy."""

    def test_result_proxies_via_job_return_value(self):
        job = _FakeJob(payload=42)
        task = AutoTask(job)
        assert task.result == 42
        assert job.return_value_calls == 1, (
            "AutoTask.result no longer calls job.return_value() — likely "
            "regressed to job.result, re-introducing the rq deprecation "
            "warning that PR #7 silenced."
        )
        assert job.result_reads == 0, (
            "AutoTask.result reached job.result directly — that's the "
            "pre-PR-#7 path. Every consumer call will now emit a "
            "DeprecationWarning."
        )

    def test_result_and_return_value_yield_equal_payloads(self):
        """Backwards-compat invariant: existing callers reading
        ``task.result`` see the same payload they always have. PR #7's
        only behaviour change for them is the absent warning."""
        job = _FakeJob(payload=[1, 2, 3])
        task = AutoTask(job)
        assert task.result == task.return_value == [1, 2, 3]

    def test_no_deprecation_warning_emitted_from_either_accessor(self):
        """Belt-and-suspenders: catch warnings while reading both and
        assert nothing about rq's Job.result deprecation surfaces.
        The fake job doesn't emit warnings itself, so this primarily
        protects against future regressions where the AutoTask
        implementation re-introduces a `self.job.result` access."""
        job = _FakeJob(payload="x")
        task = AutoTask(job)
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            _ = task.result
            _ = task.return_value
        deprecation_warnings = [
            w for w in recorded
            if issubclass(w.category, DeprecationWarning)
            and "result" in str(w.message).lower()
        ]
        assert deprecation_warnings == [], (
            "AutoTask emitted a DeprecationWarning mentioning 'result' "
            "— the implementation likely reached for job.result. PR #7 "
            "was supposed to silence that path."
        )


# ---------------------------------------------------------------------------
# Worker service in tests/docker-compose.yml
# ---------------------------------------------------------------------------


class TestDockerComposeWorkerService:
    """Without a worker process, ``test_int_tasks.py`` integration
    tests hang on QUEUED jobs that nothing drains. PR #7 added a
    declarative worker service so ``make inittests`` brings it up
    alongside the storage services."""

    @classmethod
    def setup_class(cls):
        cls.compose_path = REPO / "tests" / "docker-compose.yml"
        cls.parsed = yaml.safe_load(cls.compose_path.read_text(encoding="utf-8"))
        cls.services = (cls.parsed or {}).get("services") or {}

    def test_worker_service_present(self):
        assert "worker" in self.services, (
            "tests/docker-compose.yml no longer defines a 'worker' "
            "service — taskrunner integration tests will hang again "
            "(QUEUED jobs with nothing draining). This is exactly the "
            "regression issue #5 documented; PR #7 was the fix."
        )

    def test_worker_runs_rq_worker_command(self):
        worker = self.services["worker"]
        command = worker.get("command", "")
        # command is a list of shell pieces; rq worker shows up in the
        # final shell-c invocation. Stringify defensively.
        command_text = " ".join(command) if isinstance(command, list) else str(command)
        assert "rq worker" in command_text, (
            "tests/docker-compose.yml worker no longer runs 'rq worker' "
            "— the service exists but isn't actually consuming the queue."
        )
        assert "redis://cachedb" in command_text, (
            "worker no longer points at the cachedb service URL — the "
            "worker would either fail to connect or land on a different "
            "redis instance than the tests publish to."
        )

    def test_worker_depends_on_cachedb_health(self):
        """Without `depends_on: cachedb.service_healthy`, compose can
        race the worker against an unready Redis — the worker would
        exit immediately on first connect failure, leaving an
        ostensibly-up compose stack with no worker process. Pin the
        dependency edge so the failure mode is loud."""
        worker = self.services["worker"]
        depends = worker.get("depends_on") or {}
        # depends_on can be a list or dict; only the dict form encodes
        # `condition: service_healthy`.
        assert isinstance(depends, dict), (
            "tests/docker-compose.yml worker.depends_on regressed from "
            "the long-form dict to a list — the cachedb health "
            "condition is no longer enforced, races on cold-start."
        )
        cachedb_dep = depends.get("cachedb") or {}
        assert cachedb_dep.get("condition") == "service_healthy", (
            "worker.depends_on.cachedb no longer requires "
            "service_healthy — compose may start the worker before "
            "Redis accepts connections."
        )

    def test_worker_has_healthcheck(self):
        """`make inittests` polls for worker readiness via the same
        SCARD rq:workers signal the worker's own healthcheck uses.
        If the healthcheck disappears, `docker compose ps` shows the
        worker as up immediately, and the makefile's wait-loop relies
        on Redis-side state instead — the two-layer check is the
        invariant worth pinning."""
        worker = self.services["worker"]
        healthcheck = worker.get("healthcheck") or {}
        assert healthcheck, (
            "tests/docker-compose.yml worker no longer declares a "
            "healthcheck — compose will report 'up' the moment the "
            "container starts, before rq registers with Redis."
        )


# ---------------------------------------------------------------------------
# makefile inittests wait-loop
# ---------------------------------------------------------------------------


class TestMakefileInittestsWaitsForWorker:
    """``make inittests`` brings the compose stack up and previously
    fell straight through to `pip install`, leaving a window where
    test runs could fire against an unready stack. PR #7 added a
    Redis-polling wait-loop that blocks until the worker is registered."""

    @classmethod
    def setup_class(cls):
        cls.makefile = (REPO / "makefile").read_text(encoding="utf-8")

    def test_inittests_polls_redis_for_worker_registration(self):
        # Look for the SCARD signal — that's how the makefile knows
        # an rq worker has registered without parsing docker logs.
        assert re.search(
            r"SCARD\s+rq:workers", self.makefile
        ), (
            "makefile inittests no longer polls `SCARD rq:workers` to "
            "verify worker registration — runs may fire against an "
            "unready stack and produce flaky QUEUED-state assertions "
            "indistinguishable from issue #5's original symptom."
        )

    def test_inittests_has_bounded_retry_with_failure_exit(self):
        """The wait-loop must time out and exit non-zero — otherwise
        a worker that never registers wedges the test run forever.
        Pin the bounded-retry shape rather than the exact timeout."""
        # The wait-loop is the for-loop in inittests; check it has
        # an `exit 1` somewhere after the loop, signalling failure
        # on timeout rather than silently falling through.
        # Match across continued shell lines.
        assert re.search(
            r"for\s+i.*?seq.*?sleep\s+\d+.*?exit\s+1",
            self.makefile,
            re.DOTALL,
        ), (
            "makefile inittests wait-loop no longer exits non-zero "
            "on timeout — a wedged worker would block forever instead "
            "of failing the target with a diagnostic."
        )


# ---------------------------------------------------------------------------
# requirements_dev.txt — pyyaml declared
# ---------------------------------------------------------------------------


class TestRequirementsDevDeclaresPyYAML:
    """The previous iter's test file
    ``tests/unit/test_unit_dev_agent_command_iter_2026_05_26.py``
    imports ``yaml`` (PyYAML). pyyaml was previously satisfied
    transitively through ``myst-parser`` in dev environments, but CI
    skips docs extras and was silently red. PR #7 declared pyyaml
    explicitly. If this regresses, CI goes red again the next time
    a runner image gets refreshed and the transitive resolution
    changes."""

    def test_pyyaml_listed(self):
        text = (REPO / "requirements_dev.txt").read_text(encoding="utf-8")
        assert re.search(r"^\s*pyyaml\b", text, re.MULTILINE | re.IGNORECASE), (
            "requirements_dev.txt no longer lists pyyaml explicitly — "
            "CI will go red on imports of yaml from tests/unit/ when "
            "the runner image stops pulling pyyaml transitively."
        )


# ---------------------------------------------------------------------------
# Smoke imports — what PR #7 didn't break
# ---------------------------------------------------------------------------


class TestAutoTaskSurfaceUnchanged:
    """Beyond the two property changes, PR #7 should not have moved
    any other AutoTask surface. Pin the rest of the property set as a
    cheap regression guard — a future refactor that consolidates
    properties (e.g. dropping `is_failed`/`is_finished` in favour of
    a single `status` check) would surface here."""

    def test_expected_property_set_present(self):
        expected = {
            "id", "args", "kwargs", "status", "func_name", "timeout",
            "enqueued_at", "started_at", "ended_at", "retries_left",
            "is_failed", "is_finished", "origin", "exc_info",
            "return_value", "result",
        }
        actual = {
            name
            for name, value in vars(AutoTask).items()
            if isinstance(value, property)
        }
        missing = expected - actual
        assert not missing, (
            f"AutoTask is missing expected properties: {sorted(missing)}. "
            "PR #7 was supposed to add return_value without removing the "
            "rest of the surface."
        )

    def test_delete_and_meta_still_callable(self):
        """The two non-property accessors aren't part of PR #7's
        scope, but they're the surface most consumers reach for after
        return_value, so pin their existence here so we notice if a
        future refactor accidentally removes them."""
        assert callable(AutoTask.delete)
        assert callable(AutoTask.meta)
