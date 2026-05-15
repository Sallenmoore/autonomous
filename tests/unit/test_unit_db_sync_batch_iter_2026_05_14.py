"""Tests for the iter/2026-05-14 db_sync symmetry batch (PR #69).

Independent test-agent coverage for the two-issue batch:

- **#65** — ``_get_vector_local`` now catches bare ``Exception``,
  matching ``_get_vector_openai``. Pre-fix narrow tuple
  ``(RequestException, ValueError, KeyError)`` let non-tuple exceptions
  propagate uncaught (could kill the RQ worker) and made the
  symmetric-observability docstring claim false.
- **#66** — ``_get_vector_openai``'s ``[HPC-UNREACHABLE]`` print lines
  now contain the ``"openai"`` substring (parallel to the local-side
  ``"local"`` substring added in #60). Dashboards can split provider
  failure counts via simple grep.

Lockstep updates already merged from dev:
- ``test_uncaught_exception_type_propagates_pin_intent`` was the
  test agent's prior INTENT PIN for the asymmetric narrow-tuple
  catch. Renamed to ``test_non_tuple_exception_is_caught_and_recorded``
  and inverted by dev in PR #69. The prior test's comment explicitly
  authorized the flip ("If dev later decides both providers should
  catch every Exception, flip the assertion."); this iter file adds
  the *complementary* coverage that the dev's lockstep flip can't
  reach from one perspective.

This file pins:

1. The **`Exception` vs `BaseException` boundary** for #65 — the most
   critical contract this batch carries. ``except Exception`` swallows
   programmer/infra failures but lets ``KeyboardInterrupt`` and
   ``SystemExit`` propagate. If a drive-by ever widened the catch to
   ``BaseException``, RQ workers would become unkillable via SIGINT
   and ``sys.exit()`` calls would become no-ops. Multiple failure
   modes, none of which raise an Exception — they raise BaseException.
2. The **openai-side marker family contract** for #66 — both openai
   exception branches (``HPCUnreachableError`` and the generic
   ``except Exception`` fallback) must emit ``[HPC-UNREACHABLE]``
   marker lines containing ``"openai"``. The PR body explicitly
   flagged the symmetric-grep gap on the committed side and suggested
   exactly this test.
3. The **diff's actual format change for #66** — the old phrase
   ``"embedding generation failed"`` must no longer appear in stdout
   on the openai failure path. Pin the deletion so a future revert
   would fail this test (consumers may have grep workflows that
   broke when the phrase was removed; this test makes the removal
   load-bearing instead of accidental).
"""

from unittest.mock import patch

import pytest

from autonomous.db import db_sync


# ---------------------------------------------------------------------------
# #65 — Exception vs BaseException boundary (the critical contract)
# ---------------------------------------------------------------------------


class TestVectorLocalBaseExceptionBoundary:
    """Pin the Exception/BaseException dividing line. PR #69 broadens
    ``_get_vector_local``'s catch to bare ``Exception``, NOT bare
    ``BaseException``. That distinction is load-bearing:

    - ``Exception`` covers `RuntimeError`, `TypeError`, `OSError`,
      `requests.RequestException`, and the entire user-error +
      infra-error surface. These should be swallowed under the
      observability umbrella so the worker degrades rather than
      crashes.
    - ``BaseException`` ALSO covers `KeyboardInterrupt`, `SystemExit`,
      and `GeneratorExit`. These are signal-handling and control-flow
      primitives that MUST propagate — catching them turns SIGINT into
      a soft no-op and makes the worker unkillable.

    A future "improvement" to widen to ``BaseException`` (e.g. "catch
    everything for resilience") would silently break operator
    workflows. Pin the boundary behaviorally."""

    def test_keyboardinterrupt_propagates_not_swallowed(self):
        # Ctrl-C / SIGINT MUST kill the worker. If the catch ever
        # widens to BaseException, this test fails — forcing a
        # conversation before workers become un-stoppable.
        with patch.object(
            db_sync._HTTP_SESSION,
            "post",
            side_effect=KeyboardInterrupt(),
        ), patch.object(db_sync, "record_embedding_sync_event") as mock_record:
            with pytest.raises(KeyboardInterrupt):
                db_sync._get_vector_local("text")
        # And: KeyboardInterrupt is NOT a documented HPC failure; the
        # counter must not bump for it. If it did, dashboards would
        # see phantom failures on every operator-initiated shutdown.
        mock_record.assert_not_called()

    def test_systemexit_propagates_not_swallowed(self):
        # `sys.exit()` raises SystemExit. Used in clean-shutdown paths
        # and test-runner exit codes. Same contract as
        # KeyboardInterrupt — must reach the worker's process boundary
        # unmodified.
        with patch.object(
            db_sync._HTTP_SESSION,
            "post",
            side_effect=SystemExit(2),
        ), patch.object(db_sync, "record_embedding_sync_event") as mock_record:
            with pytest.raises(SystemExit):
                db_sync._get_vector_local("text")
        mock_record.assert_not_called()

    def test_baseexception_propagates_not_swallowed(self):
        # Belt-and-suspenders: a raw `BaseException` (not one of its
        # named subclasses) must also propagate. Catches a refactor
        # like `except (Exception, BaseException)` — which would be
        # silly but defensible against a tired-Monday commit.
        with patch.object(
            db_sync._HTTP_SESSION,
            "post",
            side_effect=BaseException("not Exception-derived"),
        ), patch.object(db_sync, "record_embedding_sync_event") as mock_record:
            with pytest.raises(BaseException):
                db_sync._get_vector_local("text")
        mock_record.assert_not_called()

    def test_custom_exception_subclass_is_caught(self):
        # Positive pin: any user-defined `Exception` subclass IS
        # caught — proves the broadening was real, not just "catches
        # the stdlib hierarchy." A future re-narrowing to a named
        # tuple of stdlib exceptions would fail this test.
        class MyDomainError(Exception):
            pass

        with patch.object(
            db_sync._HTTP_SESSION,
            "post",
            side_effect=MyDomainError("from a third-party adapter"),
        ), patch.object(db_sync, "record_embedding_sync_event") as mock_record:
            result = db_sync._get_vector_local("text")
        assert result is None, (
            "post-#65 contract: any Exception subclass returns None, "
            "not propagates"
        )
        mock_record.assert_called_once_with("hpc_failure")


# ---------------------------------------------------------------------------
# #66 — openai-side marker family contains "openai" substring
# ---------------------------------------------------------------------------


class TestOpenAIMarkerNamesProvider:
    """Pin: both ``_get_vector_openai`` exception branches' marker
    lines contain the substring ``"openai"``, so a dashboard's grep
    can split local-vs-openai failure counts.

    Pre-#66 both branches printed ``"[HPC-UNREACHABLE] embedding
    generation failed..."`` — distinguishable from local only by what
    they DIDN'T say. Post-#66 both branches print ``"[HPC-UNREACHABLE]
    openai embedding failed..."`` — symmetric with the local side's
    ``"[HPC-UNREACHABLE] local embedding failed..."``.

    The PR body explicitly suggested this committed coverage:
    *"a new test asserting "openai" in marker_line would close the
    symmetric-grep gap on the committed side."*"""

    @pytest.fixture(autouse=True)
    def _silence_autotasks(self):
        # Mirror the existing pattern in
        # test_unit_record_embedding_sync_event.py::TestHPCCallSiteWiring
        # — openai_compat imports AutoTasks at module level; neutralize
        # it so the lazy import inside _get_vector_openai doesn't
        # reach Redis.
        with patch(
            "autonomous.ai.models.openai_compat.AutoTasks"
        ) as mock_tasks:
            mock_tasks.return_value.get_current_task.return_value = None
            yield mock_tasks

    def test_hpc_unreachable_branch_marker_contains_openai(self, capsys):
        # The HPCUnreachableError branch is the primary openai-failure
        # path. Pin that the marker line names the provider so the
        # symmetric-grep contract holds.
        from autonomous.ai.models.openai_compat import (
            HPCUnreachableError,
            OpenAIClient,
        )
        with patch.object(
            OpenAIClient,
            "get_embedding",
            side_effect=HPCUnreachableError("connection refused"),
        ), patch.object(db_sync, "record_embedding_sync_event"):
            db_sync._get_vector_openai("some text")
        out = capsys.readouterr().out
        assert "[HPC-UNREACHABLE]" in out, (
            "marker prefix is the cross-provider scraper regex; "
            "do NOT pass even if openai-substring is absent — failing "
            "the prefix is a separate (worse) regression"
        )
        # Tight phrase rather than loose `"openai" in out` — see
        # test_generic_exception_branch_marker_contains_openai for
        # the rationale (avoids matching incidental "openai" in an
        # exception class name).
        assert "openai embedding" in out.lower(), (
            "marker line must name the provider in the diff phrase "
            "(`openai embedding failed`) so dashboards can split "
            "local-vs-openai failure counts via grep (#66)"
        )

    def test_generic_exception_branch_marker_contains_openai(self, capsys):
        # The generic-Exception fallback path also emits a marker
        # line. Pin that THIS path's marker also names the provider —
        # an asymmetry between the two openai branches would defeat
        # the symmetric-grep contract for the unexpected-error case
        # (which is exactly when operators most need attribution).
        #
        # Side-effect message intentionally contains NO "openai"
        # substring — if it did, the marker-substring assertion
        # would pass on the exception message rather than on the
        # marker-line format, turning the test into a tautology
        # against the source diff. The exception's class name is
        # also "ValueError" (not "OpenAI...") so `type(e).__name__`
        # interpolation can't satisfy the assertion either.
        from autonomous.ai.models.openai_compat import OpenAIClient
        with patch.object(
            OpenAIClient,
            "get_embedding",
            side_effect=ValueError("malformed payload"),
        ), patch.object(db_sync, "record_embedding_sync_event"):
            db_sync._get_vector_openai("some text")
        out = capsys.readouterr().out
        assert "[HPC-UNREACHABLE]" in out
        # Tightened from `"openai" in out.lower()` to require the
        # exact diff phrase — avoids matching incidental "openai"
        # in an exception class name like OpenAIError, which would
        # let a partial revert (marker → "embedding generation
        # failed (unexpected OpenAIError):") pass spuriously.
        assert "openai embedding" in out.lower(), (
            "unexpected-Exception branch must also name the provider "
            "in the marker phrase (`openai embedding failed`); an "
            "asymmetry between the two openai branches defeats the "
            "symmetric-grep contract for the path operators most "
            "need attribution on"
        )
        # Closes the partial-revert gap pr-test-analyzer flagged:
        # without this, restoring only the generic-branch print
        # while leaving the HPCUnreachableError branch fixed would
        # not fail any test. The deletion pin makes the wire-format
        # change load-bearing on BOTH branches.
        assert "embedding generation failed" not in out, (
            "the pre-#66 marker phrase has been replaced; if a "
            "partial revert restores it on this branch only, "
            "consumer grep workflows that adapted to the new phrase "
            "will silently break on the unexpected-error path"
        )

    def test_old_marker_phrase_no_longer_appears(self, capsys):
        # Wire-format pin for the diff's actual deletion. Pre-#66:
        # "[HPC-UNREACHABLE] embedding generation failed..." (no
        # provider name). Post-#66: "[HPC-UNREACHABLE] openai
        # embedding failed..." A future revert that re-introduces the
        # old phrase would fail this test — making the removal
        # load-bearing instead of accidental.
        from autonomous.ai.models.openai_compat import (
            HPCUnreachableError,
            OpenAIClient,
        )
        with patch.object(
            OpenAIClient,
            "get_embedding",
            side_effect=HPCUnreachableError("connection refused"),
        ), patch.object(db_sync, "record_embedding_sync_event"):
            db_sync._get_vector_openai("some text")
        out = capsys.readouterr().out
        assert "embedding generation failed" not in out, (
            "the pre-#66 marker phrase has been replaced with "
            "'openai embedding failed'; if a revert re-introduces "
            "the old phrase, consumer grep workflows that adapted "
            "to the new phrase will silently break"
        )
