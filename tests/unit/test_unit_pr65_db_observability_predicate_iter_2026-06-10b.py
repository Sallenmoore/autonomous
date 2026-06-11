"""Independent unit coverage for PR #65 — three bundled changes.

PR #65 (dev branch ``iter/2026-06-10b-batch``, refs #63 + #51 slice 2 +
#50 slice 2) ships:

* **#63 fix** — ``autonomous.db.__init__`` eagerly imports the
  ``dereference`` submodule alongside ``connection``, ``document``,
  etc. The lazy ``_import_class("DeReference")`` in
  ``autonomous.db.common.py`` raced on cold workers and intermittently
  raised ``ImportError`` on the first ``ReferenceAttr`` deref.
* **#51 slice 2** — ``autonomous.db.db_sync._emit_hpc_unreachable`` now
  bumps a process-wide ``Counter("hpc_unreachable_total",
  label_names=("signature",))`` on **every** call, including
  throttle-suppressed ones, so dashboards see the true rate even
  when the printed-line stream is silenced.
* **#50 slice 2** — ``openai_compat._is_transport_failure`` delegates
  to ``autonomous.http.is_transport_failure`` with
  ``_TRANSPORT_FAILURE_CODES`` passed as the ``extra_codes`` set.
  Behavior is identical; the predicate now lives in one place.

These tests are written from a fresh read of the PR diff
(test-agent's independent perspective) — they do NOT consult the
dev agent's gitignored ``tests/_dev_local`` ephemerals. They pin
the contracts the PR explicitly claims:

* dereference submodule is bound under ``autonomous.db`` at package
  import time (cold-worker race repro via subprocess).
* Counter bumps on every emit (verbatim + throttle-suppressed paths).
* Different signatures bump independent label series.
* Counter failure inside ``_emit_hpc_unreachable`` is swallowed —
  never propagates to the error-reporting caller.
* ``_is_transport_failure`` delegates with the right extras set
  (verified via monkeypatch) and its observable semantics match
  the pre-#50-slice-2 fixed-set + range check byte-for-byte.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from unittest.mock import MagicMock

import pytest

from autonomous.db import db_sync
from autonomous.db.db_sync import _emit_hpc_unreachable
from autonomous.observability import REGISTRY


# ---------------------------------------------------------------------------
# Part 1 — #63: dereference eagerly bound at package import
# ---------------------------------------------------------------------------


class TestDereferenceEagerImport:
    """The ``dereference`` submodule must be reachable as an attribute
    of ``autonomous.db`` immediately after ``import autonomous.db``.

    Pre-fix, ``dereference`` was missing from the eager-import tuple;
    ``common.py:_import_class("DeReference")`` runs
    ``from autonomous.db import dereference`` lazily, which raced on
    cold workers and intermittently raised ``ImportError``.
    """

    def test_dereference_is_attribute_after_db_import(self):
        """``autonomous.db.dereference`` is a non-None module object."""
        import autonomous.db as _db

        assert hasattr(_db, "dereference"), (
            "autonomous.db.dereference attribute missing — eager-import "
            "regression on #63"
        )
        # It's the actual module, not a placeholder
        from types import ModuleType
        assert isinstance(_db.dereference, ModuleType)
        assert _db.dereference.__name__ == "autonomous.db.dereference"

    def test_from_autonomous_db_import_dereference_succeeds(self):
        """The exact lazy path used by ``common.py:_import_class`` works.

        ``autonomous.db.common._import_class("DeReference")`` executes
        ``from autonomous.db import dereference`` at first call. If the
        eager-import tuple omits ``dereference``, that statement races
        with module finalization on cold workers.
        """
        from autonomous.db import dereference

        assert dereference is not None
        # The DeReference class lives in there — common.py is reaching
        # for it specifically.
        assert hasattr(dereference, "DeReference")

    def test_dereference_in_init_eager_import_tuple(self):
        """The fix is structural — assert the import statement actually
        names ``dereference`` inside the eager-import tuple, not just
        anywhere in the file. Matches the indented tuple-line form so
        a stale comment mentioning ``dereference`` (after the import
        line is deleted) doesn't false-pass.
        """
        import autonomous.db
        src = importlib.util.find_spec("autonomous.db").origin
        with open(src, encoding="utf-8") as f:
            content = f.read()
        # The tuple-line form: 4 spaces of indent, the bare name, a
        # comma. Looser than AST-parsing but tight enough that comments
        # don't trip it.
        assert "    dereference," in content, (
            "dereference not named in autonomous/db/__init__.py "
            "eager-import tuple — regression on #63"
        )

    def test_lazy_path_import_class_dereference_resolves(self):
        """The race condition lived on ``common.py:_import_class("DeReference")``,
        which executes ``from autonomous.db import dereference`` at first
        call. Exercise that exact lazy path — independent of whether
        ``autonomous.db`` happens to have already eager-imported the
        submodule — and assert the class comes back. A true race repro
        would need ``multiprocessing.Process`` × N under fork; that's
        flaky and not worth the cycles, but this at least exercises
        the lazy resolver the bug lived on.
        """
        from autonomous.db.common import _import_class

        cls = _import_class("DeReference")
        assert cls is not None
        assert cls.__name__ == "DeReference"

    def test_cold_worker_fresh_interpreter_imports_dereference(self):
        """Repro of the actual cold-worker scenario: spawn a brand-new
        Python interpreter, import ``autonomous.db``, and look up the
        ``dereference`` attribute. Pre-fix this could ImportError on
        the lazy path; with the eager import, it's deterministic.

        PYTHONPATH injection mirrors the pattern from
        ``test_unit_config_settings_iter_2026-06-07.py`` —
        setuptools 64+ direct-URL editable mode (GitHub Actions CI)
        installs an import hook in the running process, but a fresh
        subprocess starts without it, so ``autonomous`` is invisible
        unless we explicitly point at ``src/``.
        """
        import os
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent.parent / "src"
        env = dict(os.environ)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src}:{existing}" if existing else str(src)

        script = (
            "import autonomous.db as d; "
            "from autonomous.db import dereference; "
            "assert dereference is d.dereference; "
            "assert hasattr(d.dereference, 'DeReference'); "
            "print('OK')"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"cold-worker import failed:\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.stdout.strip() == "OK"


# ---------------------------------------------------------------------------
# Part 2 — #51 slice 2: hpc_unreachable_total Counter
# ---------------------------------------------------------------------------


@pytest.fixture
def _hpc_state(monkeypatch):
    """Reset the throttle dicts AND the Counter between tests so each
    test sees a clean module-level state.

    The counter is registered process-wide on REGISTRY, so without a
    reset, observations from other test files would leak in and the
    arithmetic in these tests would be off.
    """
    db_sync._HPC_UNREACHABLE_LAST_LOGGED.clear()
    db_sync._HPC_UNREACHABLE_SUPPRESSED.clear()
    counter = REGISTRY.get("hpc_unreachable_total")
    assert counter is not None, (
        "hpc_unreachable_total counter not registered — #51 slice 2 "
        "regression"
    )
    counter.reset()
    yield counter
    db_sync._HPC_UNREACHABLE_LAST_LOGGED.clear()
    db_sync._HPC_UNREACHABLE_SUPPRESSED.clear()
    counter.reset()


class TestHpcUnreachableCounter:
    """The Counter must be bumped on **every** call, regardless of
    throttle decision. The Redis hour-bucket counter
    (``record_embedding_sync_event``) is the existing
    never-throttled metric; the new in-process Counter matches that
    contract.
    """

    def test_counter_is_registered_with_signature_label(self, _hpc_state):
        """Constructor assertions — registered on default REGISTRY
        with the documented label names tuple.
        """
        counter = _hpc_state
        assert counter.name == "hpc_unreachable_total"
        assert counter.label_names == ("signature",)

    def test_throttle_off_counter_bumps_per_call(self, _hpc_state, monkeypatch, capsys):
        """With throttle disabled (default), every call prints AND
        bumps the counter. Pre-#51-slice-2 there was no counter at
        all; the contract here is "one print → one counter inc".
        """
        monkeypatch.delenv("HPC_UNREACHABLE_THROTTLE_SECONDS", raising=False)
        counter = _hpc_state

        for i in range(5):
            _emit_hpc_unreachable("sig-A", f"[HPC-UNREACHABLE] msg {i}")

        # Each call printed a line.
        out = capsys.readouterr().out
        assert out.count("[HPC-UNREACHABLE]") == 5
        # And each bumped the counter under the sig-A label.
        snapshot = counter.collect()
        assert snapshot == {("sig-A",): 5.0}

    def test_throttle_on_counter_bumps_even_when_print_suppressed(
        self, _hpc_state, monkeypatch, capsys
    ):
        """**Load-bearing contract** — when throttling suppresses the
        printed line, the counter MUST still be bumped. This is the
        whole point of the slice: dashboards see the true rate even
        when the print stream is silenced.

        With a 60s window, only the first call prints; calls 2-5
        within that window have their print suppressed but the
        counter must still tick up to 5.
        """
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "60")
        counter = _hpc_state

        for i in range(5):
            _emit_hpc_unreachable("sig-throttled", f"[HPC-UNREACHABLE] msg {i}")

        out = capsys.readouterr().out
        # Only the first call printed — throttle silenced the other 4.
        prints = [line for line in out.splitlines() if line.startswith("[HPC-UNREACHABLE]")]
        assert len(prints) == 1, (
            f"expected 1 printed line (throttle suppresses), got {len(prints)}: {prints!r}"
        )
        # But the counter sees ALL FIVE.
        snapshot = counter.collect()
        assert snapshot == {("sig-throttled",): 5.0}

    def test_distinct_signatures_create_independent_series(
        self, _hpc_state, monkeypatch
    ):
        """The ``signature`` label is what keys the time series in a
        Prometheus-style scrape. Different signatures must produce
        independent series — bumping one must not affect another.
        """
        monkeypatch.delenv("HPC_UNREACHABLE_THROTTLE_SECONDS", raising=False)
        counter = _hpc_state

        _emit_hpc_unreachable("openai:HPCUnreachableError", "msg-1")
        _emit_hpc_unreachable("local:http:500", "msg-2")
        _emit_hpc_unreachable("openai:HPCUnreachableError", "msg-3")

        snapshot = counter.collect()
        assert snapshot == {
            ("openai:HPCUnreachableError",): 2.0,
            ("local:http:500",): 1.0,
        }

    def test_counter_inc_called_with_signature_kwarg(self, _hpc_state, monkeypatch):
        """Production-shape sanity: ``_emit_hpc_unreachable`` must call
        ``inc(signature=signature)`` — NOT ``inc(signature)`` positional
        (which would land as ``value=signature`` and either silently
        skew the count or raise on the finite-number check) and NOT a
        wrong kwarg name like ``sig=`` (which the strict-label check in
        ``metrics.py`` would raise on, then the bare-except would
        swallow forever).

        Record every call and assert kwargs == {"signature": ...} and
        no positional value was passed.
        """
        monkeypatch.delenv("HPC_UNREACHABLE_THROTTLE_SECONDS", raising=False)
        counter = _hpc_state
        calls: list[tuple[tuple, dict]] = []

        original_inc = counter.inc

        def _spy(*args, **kwargs):
            calls.append((args, dict(kwargs)))
            return original_inc(*args, **kwargs)

        monkeypatch.setattr(counter, "inc", _spy)
        _emit_hpc_unreachable("sig-shape", "[HPC-UNREACHABLE] m")

        assert len(calls) == 1
        args, kwargs = calls[0]
        assert args == (), (
            f"Counter.inc must be called kwarg-only; got positional {args!r}"
        )
        assert kwargs == {"signature": "sig-shape"}

    def test_counter_failure_does_not_propagate(self, _hpc_state, monkeypatch, capsys):
        """The Counter inc is wrapped in ``try/except`` — a metrics-
        layer failure inside an error-reporting function must NOT
        replace the in-flight HPC error.

        Patch the global counter's ``inc`` to raise; the print MUST
        still happen.
        """
        monkeypatch.delenv("HPC_UNREACHABLE_THROTTLE_SECONDS", raising=False)
        counter = _hpc_state

        def _boom(*args, **kwargs):
            raise RuntimeError("metrics-layer down")

        monkeypatch.setattr(counter, "inc", _boom)

        # Must not raise.
        _emit_hpc_unreachable("sig-x", "[HPC-UNREACHABLE] still-printed")

        out = capsys.readouterr().out
        assert "[HPC-UNREACHABLE] still-printed" in out

    def test_counter_failure_preserves_throttle_state(
        self, _hpc_state, monkeypatch, capsys
    ):
        """A counter-bump exception must not short-circuit the throttle
        bookkeeping below it — otherwise ``_HPC_UNREACHABLE_LAST_LOGGED``
        wouldn't get written, every subsequent call would re-print, and
        the throttle would silently break across the whole process.

        With throttle on (3600s) and counter.inc raising, two calls
        must produce exactly ONE printed line (the second is correctly
        suppressed) AND ``_HPC_UNREACHABLE_LAST_LOGGED["sig-throttle"]``
        must be set after the first call.
        """
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "3600")
        counter = _hpc_state

        def _boom(*args, **kwargs):
            raise RuntimeError("metrics-layer down")

        monkeypatch.setattr(counter, "inc", _boom)

        _emit_hpc_unreachable("sig-throttle", "[HPC-UNREACHABLE] first")
        assert "sig-throttle" in db_sync._HPC_UNREACHABLE_LAST_LOGGED, (
            "throttle state was not updated after first emit — "
            "counter-bump failure corrupted downstream bookkeeping"
        )
        _emit_hpc_unreachable("sig-throttle", "[HPC-UNREACHABLE] second")

        prints = [
            line for line in capsys.readouterr().out.splitlines()
            if line.startswith("[HPC-UNREACHABLE]")
        ]
        assert len(prints) == 1, (
            f"expected exactly 1 printed line under throttle, got {len(prints)}: {prints!r}"
        )

    def test_counter_bumped_before_throttle_decision(
        self, _hpc_state, monkeypatch
    ):
        """Order-of-operations sanity: if the throttle short-circuits
        the function (window > 0 and inside the window), the counter
        bump must already have happened on the way in. Verified by
        making the bump observable BEFORE we ever consult the throttle
        — i.e., even a single throttled call increments by 1.
        """
        monkeypatch.setenv("HPC_UNREACHABLE_THROTTLE_SECONDS", "3600")
        counter = _hpc_state

        # Prime the throttle bucket so the next call goes down the
        # suppression branch.
        _emit_hpc_unreachable("sig-prime", "first")
        # Now we're inside the 3600s window — the next call IS suppressed.
        _emit_hpc_unreachable("sig-prime", "suppressed")

        snapshot = counter.collect()
        assert snapshot[("sig-prime",)] == 2.0


# ---------------------------------------------------------------------------
# Part 3 — #50 slice 2: predicate delegation in openai_compat
# ---------------------------------------------------------------------------


class TestIsTransportFailureDelegation:
    """``openai_compat._is_transport_failure`` is now a wrapper around
    ``autonomous.http.is_transport_failure`` with
    ``_TRANSPORT_FAILURE_CODES`` passed as ``extra_codes``. The
    observable contract — input → bool — must be identical to the
    pre-delegation impl.
    """

    def test_500_returns_true_via_5xx_range(self):
        """500 was the bug from #39 — the original fixed-set check
        missed it. The 5xx-range branch (in the central predicate)
        catches it.
        """
        from autonomous.ai.models.openai_compat import _is_transport_failure

        assert _is_transport_failure(500) is True
        assert _is_transport_failure(502) is True
        assert _is_transport_failure(503) is True
        assert _is_transport_failure(599) is True

    def test_401_returns_true_via_extras_set(self):
        """``_TRANSPORT_FAILURE_CODES`` is ``frozenset({401})`` — the
        deployment-specific "VPN drop" code. Must pass through to the
        central predicate's ``extras`` hit branch.
        """
        from autonomous.ai.models.openai_compat import _is_transport_failure

        assert _is_transport_failure(401) is True

    def test_2xx_3xx_4xx_below_500_return_false(self):
        """Anything not in extras and < 500 is "not transport". The
        old code did exactly this via the fixed-set + range check.
        """
        from autonomous.ai.models.openai_compat import _is_transport_failure

        # Sample across the < 500 space (skipping 401 which IS in extras).
        for status in (200, 201, 204, 301, 302, 400, 403, 404, 429, 499):
            assert _is_transport_failure(status) is False, (
                f"status {status} should not be transport-class"
            )

    def test_non_orderable_inputs_return_false_defensively(self):
        """A ``MagicMock`` or ``None`` shouldn't crash the predicate —
        the central impl has a ``try/except TypeError`` matching the
        original openai_compat shape. This is the test-fixture
        compatibility branch.
        """
        from autonomous.ai.models.openai_compat import _is_transport_failure

        assert _is_transport_failure(MagicMock()) is False
        assert _is_transport_failure(None) is False
        # A string is not comparable with int via >= on Python 3.
        assert _is_transport_failure("oops") is False

    def test_delegates_to_autonomous_http_predicate(self, monkeypatch):
        """Structural: the wrapper actually calls
        ``autonomous.http.is_transport_failure``. Catches a future
        regression where someone re-inlines the predicate without
        realizing the consolidation was load-bearing for future
        transport-class refinements.

        Patch the bound reference inside ``openai_compat`` (the
        ``from ... import is_transport_failure as _http_is_transport_failure``
        binding) so the test stays decoupled from the central
        implementation's own behavior.
        """
        from autonomous.ai.models import openai_compat

        calls: list[tuple] = []

        def _spy(status, *, extra_codes=()):
            calls.append((status, frozenset(extra_codes)))
            return True  # arbitrary — we're testing dispatch, not return

        monkeypatch.setattr(
            openai_compat, "_http_is_transport_failure", _spy
        )

        result = openai_compat._is_transport_failure(503)
        assert result is True
        assert len(calls) == 1
        status, extras = calls[0]
        assert status == 503
        # The extras set MUST be the module's _TRANSPORT_FAILURE_CODES,
        # not an empty/default set — the deployment-specific 401
        # equivalence depends on this passthrough.
        assert extras == openai_compat._TRANSPORT_FAILURE_CODES
        assert 401 in extras

    def test_parity_table_old_vs_new_semantics(self):
        """Direct parity check: for a battery of inputs, the new
        delegating impl returns exactly what the pre-delegation impl
        (inlined here for comparison) would have returned. The two
        impls have to agree input-for-input.
        """
        from autonomous.ai.models.openai_compat import (
            _is_transport_failure,
            _TRANSPORT_FAILURE_CODES,
        )

        # Re-implement the OLD behavior verbatim from the diff's
        # `-` lines:
        #     if status in _TRANSPORT_FAILURE_CODES: return True
        #     try: return status >= 500
        #     except TypeError: return False
        def _old(status):
            if status in _TRANSPORT_FAILURE_CODES:
                return True
            try:
                return status >= 500
            except TypeError:
                return False

        for status in [
            200, 301, 400, 401, 403, 404, 429, 499,
            500, 501, 502, 503, 521, 525, 599, 600,
            None, "x", MagicMock(),
        ]:
            assert _is_transport_failure(status) == _old(status), (
                f"parity broke at status={status!r}"
            )
