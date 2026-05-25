"""Tests for the iter/2026-05-15-pr76-followup batch (PR #83).

Independent test-agent coverage for the five-issue follow-up:

- **#74** — Gemini ``_add_files`` accepts BOTH list-of-dicts and
  dict-of-fileobjs shapes via input normalization. Pre-fix every
  call raised ``AttributeError`` (list path) or wrong-shape tuples
  (dict path) — production traceback blocking storyteller's image
  attachment flow.
- **#77** — ``retry(jitter=NaN)`` now raises at validation time
  rather than slipping through to ``time.sleep(NaN)`` mid-loop.
- **#78** — ``openai_compat._post`` catches the documented
  ``requests.RequestException`` base, so urllib3 pool exceptions
  (``RetryError``, ``ChunkedEncodingError``) translate to
  ``HPCUnreachableError`` and surface under the ``[HPC-UNREACHABLE]``
  scrape sentinel.
- **#79** — Already pinned by the lockstep flip of this iter file's
  predecessor (``test_persist_false_emits_reinstantiation_log_with_orphan_note``
  in ``test_unit_perf_iter_2026_05_15.py``). No additional coverage
  needed in this file.
- **#80** — ``tests/perf/conftest.py`` now uses
  ``pytest_collection_modifyitems`` to apply the ``perf`` marker.
  Pin the user-visible contract: ``pytest -m perf`` actually
  selects the perf suite (was zero pre-fix).

Independent perspective focus:
- **#74**: dev's ephemeral tests likely cover both shapes; this file
  adds the negative-space pins (empty inputs, the MAX_FILES truncation
  contract, and the shape-coercion invariant that BOTH callers see
  the same dict structure inside the loop body).
- **#78**: dev probably tests the broader catch via one Exception
  subclass; this file pins the SPECIFIC subclasses called out in
  the issue (``RetryError``, ``ChunkedEncodingError``) so a future
  re-narrowing to e.g. ``(ConnectionError, Timeout, RetryError)``
  would still miss ``ChunkedEncodingError`` and the regression would
  be caught.
- **#80**: dev's ephemeral test likely runs ``pytest -m perf``; this
  file pins it via the registered-and-applied invariant from inside
  the test suite without subprocessing.
"""

import math
import pathlib
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
import requests


# Repo root derived from this file's location, NOT a hardcoded path,
# so the subprocess-pytest test below works in any checkout (including
# CI's $GITHUB_WORKSPACE which lives under /home/runner/work/, not
# /opt/projects/).
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


# ===========================================================================
# #74 — Gemini _add_files dict/list normalization
# ===========================================================================


class TestGeminiAddFilesShapeNormalization:
    """Pin: ``_add_files`` accepts BOTH input shapes and produces a
    list-of-dicts internal representation before the loop runs.
    Pre-#74, ``list(file_list.items())`` AttributeError'd on the list
    path and produced ``(key, value)`` tuples on the dict path that
    couldn't be subscripted as ``f["name"]``."""

    def _make_gemini_stub(self):
        # `GeminiAIModel.client` is a property without a setter, so
        # we can't attribute-assign on an instance. Use a hand-built
        # stub class that has the same surface ``_add_files`` reaches,
        # then invoke ``_add_files`` as an unbound method with the
        # stub as self. Same pattern as dev's _StubAgent in
        # test_unit_baseagent_get_client_persist.py.
        class _Stub:
            MAX_FILES = 10

            def save(self):
                # _add_files calls self.save() at the end.
                pass

        stub = _Stub()
        stub.client = MagicMock()
        stub.client.files.delete = MagicMock()
        # Upload returns a handle whose `state.name` is NOT "PROCESSING"
        # so the post-upload while-loop exits immediately.
        upload_handle = MagicMock()
        upload_handle.state.name = "READY"
        stub.client.files.upload = MagicMock(return_value=upload_handle)
        # files.list() returns an empty iterable so the file_refs
        # comprehension produces [] (and self.file_refs is settable
        # on a plain class instance).
        stub.client.files.list = MagicMock(return_value=[])
        return stub

    def _call(self, stub, file_list, mime_type="application/json"):
        # Invoke as unbound-method-with-stub-self to bypass the
        # `client` property.
        from autonomous.ai.models import gemini
        return gemini.GeminiAIModel._add_files(
            stub, file_list, mime_type=mime_type
        )

    def test_list_of_dicts_shape_is_accepted(self):
        stub = self._make_gemini_stub()
        file_list = [
            {"name": "a.json", "file": MagicMock()},
            {"name": "b.json", "file": MagicMock()},
        ]
        # Must not raise. The pre-fix code attempted
        # `list(file_list.items())` which raises AttributeError on
        # a list — this test fails on the source if that returns.
        self._call(stub, file_list)
        # Both files made it through to upload (proves the loop
        # body actually iterated, not just constructed an empty
        # result).
        assert stub.client.files.upload.call_count == 2

    def test_dict_of_fileobjs_shape_is_accepted(self):
        # The OTHER documented caller shape (per #74's analysis):
        # `generate_image` and storyteller's ImageAgent pass a
        # `{filename: fileobj}` dict.
        stub = self._make_gemini_stub()
        file_list = {
            "a.json": MagicMock(),
            "b.json": MagicMock(),
        }
        # Must not raise. Pre-fix the loop body received
        # `(filename, fileobj)` tuples and crashed at `f["name"]`.
        self._call(stub, file_list)
        assert stub.client.files.upload.call_count == 2

    def test_max_files_truncation_holds_on_both_shapes(self):
        # The `[:self.MAX_FILES]` slice is the loop's safety belt.
        # Pin it survives the normalization step on BOTH shapes —
        # a regression that normalized AFTER truncation, or used
        # the wrong upper bound on the truncation slice, would
        # silently upload more files than intended (cost + quota).
        stub = self._make_gemini_stub()
        stub.MAX_FILES = 2
        many = {
            f"f{i}.json": MagicMock() for i in range(5)
        }
        self._call(stub, many)
        assert stub.client.files.upload.call_count == 2, (
            f"MAX_FILES truncation should cap uploads at 2; got "
            f"{stub.client.files.upload.call_count}"
        )
        # And on the list shape too.
        stub.client.files.upload.reset_mock()
        many_list = [
            {"name": f"g{i}.json", "file": MagicMock()} for i in range(5)
        ]
        self._call(stub, many_list)
        assert stub.client.files.upload.call_count == 2

    def test_empty_inputs_do_not_crash(self):
        # Negative-space pin: empty dict and empty list are both
        # valid inputs that should produce zero uploads (a noop
        # call). A regression that didn't handle the empty case
        # uniformly across shapes would surface here.
        stub = self._make_gemini_stub()
        self._call(stub, [])
        self._call(stub, {})
        assert stub.client.files.upload.call_count == 0

    def test_mime_type_kwarg_propagates_to_upload(self):
        # Gap pin: ``_add_files`` accepts a ``mime_type`` kwarg that
        # MUST land in the eventual ``files.upload(config={...})``
        # call. The actual production caller (``generate_image``,
        # ``upscale_image`` per src/autonomous/ai/models/gemini.py)
        # passes ``mime_type="image/webp"`` — a regression where the
        # normalization step dropped or hardcoded the mime_type
        # would silently break image uploads for those paths.
        # Default and explicit cases tested.
        stub = self._make_gemini_stub()
        file_list = [{"name": "a.webp", "file": MagicMock()}]
        self._call(stub, file_list, mime_type="image/webp")
        # Inspect the upload call's config kwarg.
        upload_kwargs = stub.client.files.upload.call_args.kwargs
        assert upload_kwargs.get("config", {}).get("mime_type") == (
            "image/webp"
        ), (
            f"mime_type kwarg must propagate to upload's "
            f"config={{...}}; got call_args.kwargs={upload_kwargs!r}"
        )


# ===========================================================================
# #77 (additional) — retry(jitter=NaN) is rejected
# ===========================================================================


class TestRetryJitterNaNRejected:
    """Pin: ``retry(jitter=float('nan'))`` raises ``ValueError`` at
    validation time. My iter/2026-05-15 file pinned the BOUNDARY
    (jitter just below 1.0 stays positive) but not NaN. #77 closed
    the gap with ``math.isfinite``; pin the user-visible contract."""

    def test_nan_jitter_raises_validation_error(self):
        # NaN is the ONLY input the new `math.isfinite` check rejects
        # that the old `< 0 or >= 1` check accepted. Pin the new
        # error wording specifically — "finite" is the differentiator.
        from autonomous.ai.retry import retry
        with pytest.raises(ValueError, match=r"finite.*\[0, 1\)"):
            retry(
                lambda: None,
                max_attempts=1,
                sleep_seconds=1.0,
                jitter=float("nan"),
            )

    def test_positive_infinity_jitter_raises_validation_error(self):
        # +Infinity already failed the `>= 1` check pre-#77 (the old
        # behavior). Pin the rejection only — not the specific
        # message wording, so a reasonable future re-phrasing (e.g.
        # "jitter must be a number less than 1") doesn't break this
        # test for non-behavioral reasons.
        from autonomous.ai.retry import retry
        with pytest.raises(ValueError, match=r"jitter"):
            retry(
                lambda: None,
                max_attempts=1,
                sleep_seconds=1.0,
                jitter=math.inf,
            )

    def test_negative_infinity_jitter_raises_validation_error(self):
        # -Infinity failed `< 0` pre-#77 too. Same "rejection-only,
        # not message-text" stance as +Inf.
        from autonomous.ai.retry import retry
        with pytest.raises(ValueError, match=r"jitter"):
            retry(
                lambda: None,
                max_attempts=1,
                sleep_seconds=1.0,
                jitter=-math.inf,
            )


# ===========================================================================
# #78 — openai_compat._post catches the full RequestException family
# ===========================================================================


class TestOpenAIPostCatchesPoolExceptions:
    """Pin: ``openai_compat._post`` translates ALL
    ``requests.RequestException`` subclasses to ``HPCUnreachableError``,
    including the urllib3-pool-specific types that the pre-#78 narrow
    catch missed. A future re-narrowing (e.g. back to a named tuple)
    that omits any of these would fail this test."""

    @pytest.fixture(autouse=True)
    def _silence_autotasks(self):
        with patch(
            "autonomous.ai.models.openai_compat.AutoTasks"
        ) as mock_tasks:
            mock_tasks.return_value.get_current_task.return_value = None
            yield mock_tasks

    def _make_client(self):
        # OpenAIClient.__new__ inherits class-level _retry_attempts=3
        # and _retry_backoff=10 from openai_compat. Without overriding,
        # each test would burn ~20s of real time.sleep on the inner
        # retry loop (2 sleeps × ~10s each). Set attempts=1 and
        # backoff=0 so the test fails fast on the first translated
        # raise — the retry behavior is not what we're pinning.
        from autonomous.ai.models import openai_compat
        client = openai_compat.OpenAIClient.__new__(
            openai_compat.OpenAIClient
        )
        client._base_url = "http://stub"
        client._timeout = 1.0
        client._retry_attempts = 1
        client._retry_backoff = 0
        return client

    def test_retry_error_translates_to_hpc_unreachable(self):
        # urllib3 pool exhaustion. Pre-#78 this propagated raw and
        # bypassed the [HPC-UNREACHABLE] scrape sentinel.
        from autonomous.ai.models import openai_compat
        client = self._make_client()
        with patch.object(
            openai_compat._SESSION,
            "post",
            side_effect=requests.exceptions.RetryError("pool exhausted"),
        ):
            with pytest.raises(openai_compat.HPCUnreachableError) as excinfo:
                client._post("test/path", {"k": "v"})
        # The translated error should include the type name so the
        # log-scraper can disambiguate transport classes.
        assert "RetryError" in str(excinfo.value), (
            "translated error must include type(exc).__name__ so "
            "operators can disambiguate transport failure classes"
        )

    def test_chunked_encoding_error_translates_to_hpc_unreachable(self):
        # Interrupted streamed body on a pooled connection. Pre-#78
        # this also escaped the translation.
        from autonomous.ai.models import openai_compat
        client = self._make_client()
        with patch.object(
            openai_compat._SESSION,
            "post",
            side_effect=requests.exceptions.ChunkedEncodingError(
                "stream interrupted"
            ),
        ):
            with pytest.raises(openai_compat.HPCUnreachableError) as excinfo:
                client._post("test/path", {"k": "v"})
        assert "ChunkedEncodingError" in str(excinfo.value)

    def test_legacy_connection_error_still_translates(self):
        # Belt-and-suspenders: the pre-#78 cases (ConnectionError,
        # Timeout) still translate. A regression that swapped to
        # a too-narrow catch (e.g. only urllib3 ones) would now
        # fail.
        from autonomous.ai.models import openai_compat
        client = self._make_client()
        with patch.object(
            openai_compat._SESSION,
            "post",
            side_effect=requests.ConnectionError("refused"),
        ):
            with pytest.raises(openai_compat.HPCUnreachableError):
                client._post("test/path", {"k": "v"})


# ===========================================================================
# #80 — pytest -m perf actually selects the perf suite
# ===========================================================================


class TestPytestPerfMarkerActuallyApplies:
    """Pin: post-#80, ``pytest -m perf`` selects perf tests (was 0
    pre-fix). The marker is applied via the
    ``pytest_collection_modifyitems`` hook in
    ``tests/perf/conftest.py``. A regression that removed the hook
    OR moved it to a wrong directory OR changed the path predicate
    would break the documented explicit-invocation interface."""

    def test_pytest_dash_m_perf_selects_at_least_one_test(self):
        # Subprocess pytest with `-m perf --collect-only` and parse
        # the count. The previous in-process invocation isn't safe
        # (would pollute the current collection); subprocess
        # isolates.
        #
        # `cwd` is derived from this file's location so the test
        # works in any checkout (including CI's $GITHUB_WORKSPACE
        # under /home/runner/work/, not the dev tree's /opt/projects/).
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest",
                "tests/perf",
                "-m", "perf",
                "--collect-only",
                "-q",
                "-p", "no:cacheprovider",
                "-o", "addopts=",
            ],
            capture_output=True,
            text=True,
            cwd=str(_REPO_ROOT),
        )
        # If `-m perf` collects nothing, the output says
        # "no tests collected (X deselected)" — that's the regression.
        out = result.stdout
        assert "no tests collected" not in out, (
            f"`pytest -m perf` must select the perf suite (was 0 "
            f"pre-#80); got output:\n{out}\nstderr:\n{result.stderr}"
        )
        # And at least one test was collected.
        import re
        m = re.search(r"(\d+) tests? collected", out)
        assert m and int(m.group(1)) >= 1, (
            f"`pytest -m perf` should collect at least one test; "
            f"output:\n{out}"
        )

    # The symmetric `pytest -m 'not perf'` test was dropped per
    # pr-test-analyzer feedback: it costs ~30s of subprocess pytest
    # bootstrap to prove the converse of the positive pin above,
    # which is already implied (if `-m perf` selects N>0 and the
    # marker discipline applies, then `-m 'not perf'` excludes the
    # same N). Keep the positive pin — it's the user-visible
    # contract.
