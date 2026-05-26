"""Independent coverage for PR #18 (iter/2026-05-26d: AutoTask.exc_info
off deprecated Job.exc_info — closes #14).

PR #18 is the pattern-mate of PR #7's ``Job.result`` → ``Job.return_value()``
migration. ``AutoTask.exc_info`` previously read ``self.job.exc_info``
directly, which rq 2.x deprecates (and a future rq major will remove
entirely). PR #18 reroutes through ``self.job.latest_result()`` and
returns the ``exc_string`` attribute of the resulting Result object,
preserving the existing ``str | None`` return contract.

The dev perspective: "two-line swap from a deprecated attribute to its
modern accessor; return type unchanged; callers don't notice." The
test agent's independent perspective: "is the new path actually used,
does the None-safe guard correctly handle jobs with no result yet
(queued/started), and would a regression to the old path re-introduce
the DeprecationWarning the migration was meant to silence?"

Hermetic: a small mock-job fake with a configurable ``latest_result()``
return value stands in for ``rq.job.Job`` so the new exc_info accessor
can be exercised without a live Redis or worker. Uses the same
two-perspective shape as ``test_unit_autotask_return_value_iter_2026_05_26b.py``.
"""

from __future__ import annotations

import warnings

import pytest

from autonomous.taskrunner.autotasks import AutoTask


# ---------------------------------------------------------------------------
# Mock job fakes — explicit latest_result vs. legacy exc_info paths
# ---------------------------------------------------------------------------


class _FakeResult:
    """Minimal stand-in for ``rq.results.Result``. Only attribute we
    care about for the migration is ``exc_string`` (the formatted
    traceback for failed jobs)."""

    def __init__(self, exc_string: str | None):
        self.exc_string = exc_string


class _FakeJob:
    """Stands in for ``rq.job.Job``. Tracks call counts on the two
    paths the migration cares about:

    - ``latest_result()`` — the new, post-PR-#18 path.
    - ``exc_info`` (property) — the old, deprecated path. Reading it
      would emit ``DeprecationWarning`` on a real rq 2.x Job; here it
      just increments a counter we can assert against, so a regression
      to the old code path is caught loudly.
    """

    def __init__(self, latest: _FakeResult | None = None, exc_info: str | None = None):
        self._latest = latest
        self._exc_info_legacy = exc_info
        self.latest_result_calls = 0
        self.legacy_exc_info_reads = 0

    def latest_result(self):
        self.latest_result_calls += 1
        return self._latest

    @property
    def exc_info(self):
        # If a future regression points AutoTask.exc_info back at this
        # property, the read shows up in legacy_exc_info_reads and the
        # related assertion below fires.
        self.legacy_exc_info_reads += 1
        return self._exc_info_legacy


# ---------------------------------------------------------------------------
# AutoTask.exc_info — migrated to Job.latest_result().exc_string
# ---------------------------------------------------------------------------


class TestAutoTaskExcInfo:
    """PR #18's headline: ``exc_info`` now reads through
    ``Job.latest_result()`` instead of the deprecated attribute. The
    return contract (``str | None``) stays the same, so callers don't
    notice — but the deprecation warning silences."""

    def test_exc_info_returns_exc_string_when_latest_result_present(self):
        traceback = (
            'Traceback (most recent call last):\n  File "..."\n'
            "TypeError: unsupported operand type(s) for +: 'int' and 'str'"
        )
        job = _FakeJob(latest=_FakeResult(exc_string=traceback))
        task = AutoTask(job)
        assert task.exc_info == traceback, (
            "AutoTask.exc_info returned the wrong value when "
            "latest_result() yielded a Result with exc_string set. "
            "The migration path is broken — likely a typo on "
            "`.exc_string` (e.g. `.exc_info` or `.exception`)."
        )
        assert job.latest_result_calls == 1, (
            "AutoTask.exc_info did not call job.latest_result() — the "
            "implementation may have regressed to the pre-PR-#18 path "
            "(self.job.exc_info), which is deprecated in rq 2.x and "
            "will be removed in a future major."
        )

    def test_exc_info_returns_none_when_no_result_yet(self):
        """Jobs that are queued / started / haven't produced a Result
        yet make ``Job.latest_result()`` return ``None`` — PR #18's
        guard (``latest.exc_string if latest else None``) keeps the
        old contract (``None`` for in-flight jobs) intact. A regression
        that drops the None-check would raise AttributeError on every
        in-flight job."""
        job = _FakeJob(latest=None)
        task = AutoTask(job)
        # Must not raise.
        result = task.exc_info
        assert result is None, (
            f"AutoTask.exc_info returned {result!r} when "
            "latest_result() yielded None — expected None per the "
            "pre-PR-#18 contract."
        )

    def test_exc_info_returns_none_when_result_has_no_exc_string(self):
        """Finished-successfully jobs produce a Result whose
        ``exc_string`` is ``None``. The migration should pass that
        through unchanged."""
        job = _FakeJob(latest=_FakeResult(exc_string=None))
        task = AutoTask(job)
        assert task.exc_info is None

    def test_exc_info_does_not_read_legacy_attribute(self):
        """Regression guard: a future edit that reaches for the
        deprecated ``job.exc_info`` would silently re-introduce the
        rq deprecation warning. Pin the migration by asserting the
        legacy path stays untouched."""
        legacy_payload = "legacy-traceback-should-not-be-read"
        job = _FakeJob(
            latest=_FakeResult(exc_string="modern-exc-string"),
            exc_info=legacy_payload,
        )
        task = AutoTask(job)
        result = task.exc_info
        assert job.legacy_exc_info_reads == 0, (
            "AutoTask.exc_info reached for job.exc_info (the rq-"
            "deprecated path) — PR #18's whole purpose was to stop "
            "using it. The DeprecationWarning will re-surface."
        )
        assert result == "modern-exc-string", (
            f"AutoTask.exc_info returned {result!r} — looks like the "
            "implementation may be mixing the modern and legacy paths."
        )

    def test_no_deprecation_warning_emitted(self):
        """Belt-and-suspenders: read ``exc_info`` while catching
        warnings and assert nothing about rq's ``Job.exc_info``
        deprecation surfaces. The fake job doesn't emit warnings
        itself, so this primarily protects against future regressions
        where the AutoTask implementation reaches for the deprecated
        attribute."""
        job = _FakeJob(latest=_FakeResult(exc_string="x"))
        task = AutoTask(job)
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            _ = task.exc_info
        deprecation = [
            w for w in recorded
            if issubclass(w.category, DeprecationWarning)
            and "exc_info" in str(w.message).lower()
        ]
        assert deprecation == [], (
            "AutoTask.exc_info emitted a DeprecationWarning mentioning "
            "'exc_info' — the implementation reached for the deprecated "
            "rq attribute. PR #18 was supposed to silence that path."
        )

    def test_repeated_access_calls_latest_result_each_time(self):
        """latest_result() reads from Redis on each call (rq does
        not memoise on the Job object). AutoTask.exc_info must
        delegate each access so callers polling a still-running job
        eventually see the post-failure exc_string when the worker
        updates it."""
        job = _FakeJob(latest=_FakeResult(exc_string="initial"))
        task = AutoTask(job)
        _ = task.exc_info
        # Simulate a later Redis fetch returning an updated Result.
        job._latest = _FakeResult(exc_string="updated")
        assert task.exc_info == "updated"
        assert job.latest_result_calls == 2, (
            "AutoTask.exc_info memoised the first latest_result() "
            "call — a still-running job would surface stale exc_info "
            "indefinitely after the first read."
        )


# ---------------------------------------------------------------------------
# Sibling-property non-regression — return_value path from PR #7 still clean
# ---------------------------------------------------------------------------


class TestSiblingReturnValueUnchanged:
    """PR #18 touches only ``AutoTask.exc_info``. Pin that
    ``AutoTask.return_value`` and ``AutoTask.result`` still route
    through ``Job.return_value()`` from PR #7 — a careless refactor
    that consolidates the two migrations could accidentally route
    one through the wrong rq accessor."""

    def test_return_value_still_uses_return_value(self):
        """The PR #7 path: AutoTask.return_value reads
        job.return_value() (not job.result or job.latest_result).
        Pin to catch a careless refactor that swaps the two."""

        class _FakeJobWithReturnValue:
            def __init__(self):
                self.return_value_calls = 0
                self.latest_result_calls = 0

            def return_value(self):
                self.return_value_calls += 1
                return 42

            def latest_result(self):
                self.latest_result_calls += 1
                return _FakeResult(exc_string=None)

        job = _FakeJobWithReturnValue()
        task = AutoTask(job)
        assert task.return_value == 42
        assert job.return_value_calls == 1, (
            "AutoTask.return_value no longer routes through "
            "job.return_value() — possibly cross-wired with the "
            "exc_info migration in PR #18."
        )
        assert job.latest_result_calls == 0, (
            "AutoTask.return_value reached for latest_result() — "
            "wrong accessor; PR #7 set this to return_value() and "
            "PR #18 shouldn't have touched it."
        )
