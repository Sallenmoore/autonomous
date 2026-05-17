"""Tests for the iter/2026-05-16-pr88-followup batch (PR #94).

Independent test-agent coverage for the three-issue tightening:

- **#89** — Extends ``openai_compat._post`` carve-out tuple from 4 → 7
  config-error types (adds ``URLRequired``, ``InvalidHeader``,
  ``InvalidProxyURL``). The lockstep extension of the parametrize list
  in ``test_unit_followup_iter_2026_05_15_pr83.py`` covers the
  per-type propagation contract; this file pins ORTHOGONAL angles
  so a future regression that drops ALL of them (or reverts to the
  old 4-type tuple) is caught even if someone also touches the
  parametrize list.
- **#90** — Changes ``gemini._add_files`` guard from
  ``set(keys) == {"name", "file"}`` to subset check
  ``"name" in fl and "file" in fl``. The 2-key case (the original
  guard) still triggers; the new pin is the N-key case for N ≥ 3
  that PR #88's exact-equality form missed.
- **#93** — Adds ``ruvector.db`` to ``.gitignore``. A structural
  pin verifies the entry is present AND functional via
  ``git check-ignore``.

Two-perspective coverage. Dev's ephemeral tests in ``tests/_dev_local/``
likely covered the per-type carve-out and the subset check; this
file's contribution is forward-pinning the *intent* of each change
so accidental tightening / loosening is caught.
"""

import io
import pathlib
import subprocess
from unittest.mock import patch

import pytest
import requests


# ===========================================================================
# #89 — openai_compat carve-out extended (orthogonal angles to parametrize)
# ===========================================================================


class TestOpenAICarveOutSurfaceExtended:
    """Pin the *cardinality* and *intent* of the extended carve-out.

    The lockstep parametrize update in PR #83's test file pins each
    individual type. This class pins SHAPE properties of the carve-out
    that would survive someone editing the parametrize list itself.
    """

    @pytest.fixture(autouse=True)
    def _silence_autotasks(self):
        with patch(
            "autonomous.ai.models.openai_compat.AutoTasks"
        ) as mock_tasks:
            mock_tasks.return_value.get_current_task.return_value = None
            yield mock_tasks

    def _make_client(self):
        from autonomous.ai.models import openai_compat
        client = openai_compat.OpenAIClient.__new__(
            openai_compat.OpenAIClient
        )
        client._base_url = "http://stub"
        client._timeout = 1.0
        # Single attempt + zero backoff keeps any retry-spin regression
        # from costing real wall time. Carve-out correctness is proved
        # by `sleep` call count, not duration.
        client._retry_attempts = 1
        client._retry_backoff = 0
        return client

    def test_carve_out_source_contains_all_seven_types(self):
        # Source-text pin: the except tuple must enumerate at least
        # the 7 types this PR ratifies. A regression that drops one
        # silently (e.g. a merge resolving to the pre-#89 tuple)
        # would slip through the parametrize-list check if someone
        # also edited that list back to 4. This pin is the second
        # line of defense — names checked against the source file.
        src = pathlib.Path(
            "src/autonomous/ai/models/openai_compat.py"
        ).read_text()
        required = (
            "MissingSchema",
            "InvalidURL",
            "InvalidSchema",
            "InvalidJSONError",
            "URLRequired",
            "InvalidHeader",
            "InvalidProxyURL",
        )
        missing = [n for n in required if n not in src]
        assert not missing, (
            f"openai_compat.py is missing carve-out types: {missing}. "
            f"Carve-out must enumerate all 7 config-error types per "
            f"#84 + #89, even if InvalidProxyURL is transitively "
            f"caught by InvalidURL today."
        )

    def test_invalid_header_propagates_raw_without_retry(self, monkeypatch):
        # Picked one of the NEW types (InvalidHeader) as a smoke for
        # the actual runtime path — the source-text pin above proves
        # presence, this proves binding. Together they catch both
        # "name was removed" and "name is listed but except clause
        # was re-ordered to land in the broader catch".
        from autonomous.ai.models import openai_compat
        client = self._make_client()
        sleep_calls = []
        monkeypatch.setattr(
            "autonomous.ai.retry.time.sleep",
            lambda s: sleep_calls.append(s),
        )
        with patch.object(
            openai_compat._SESSION,
            "post",
            side_effect=requests.exceptions.InvalidHeader("bad header"),
        ):
            with pytest.raises(requests.exceptions.InvalidHeader):
                client._post("path", {"k": "v"})
        assert sleep_calls == [], (
            f"InvalidHeader should bypass retry entirely; got "
            f"{len(sleep_calls)} sleeps"
        )

    def test_carve_out_does_not_catch_connectionerror(self, monkeypatch):
        # Regression guard for the OTHER direction: someone broadens
        # the carve-out tuple to catch ConnectionError (or
        # RequestException itself), which would defeat the entire
        # purpose of the HPCUnreachableError translation layer (#78).
        # ConnectionError must still flow into the broader catch and
        # be translated to HPCUnreachableError.
        from autonomous.ai.models import openai_compat
        client = self._make_client()
        sleep_calls = []
        monkeypatch.setattr(
            "autonomous.ai.retry.time.sleep",
            lambda s: sleep_calls.append(s),
        )
        with patch.object(
            openai_compat._SESSION,
            "post",
            side_effect=requests.exceptions.ConnectionError("net down"),
        ):
            with pytest.raises(openai_compat.HPCUnreachableError) as exc:
                client._post("path", {"k": "v"})
        # Translation happened (not raw ConnectionError).
        assert isinstance(
            exc.value.__cause__, requests.exceptions.ConnectionError
        ), (
            f"ConnectionError should be wrapped in HPCUnreachableError "
            f"via `raise ... from exc`; got cause "
            f"{type(exc.value.__cause__).__name__}"
        )


# ===========================================================================
# #90 — gemini _add_files subset guard
# ===========================================================================


class TestGeminiAddFilesSubsetGuard:
    """Pin the subset-check semantics (the substance of #90).

    Pre-#90 the guard used ``set(keys) == {"name", "file"}`` — an
    exact-equality check that let any N-key dict (N ≥ 3) bypass and
    silently corrupt via the legitimate-{filename: fileobj}-path
    interpretation. Post-#90 the guard uses ``"name" in fl and
    "file" in fl`` — fires for ANY dict containing both keys.
    """

    def _stub(self):
        # `_add_files` is called as an unbound method with the stub
        # standing in for `self`. The reach goes beyond just the
        # guard: even when the guard does NOT fire, the function
        # iterates `self.MAX_FILES`, calls `self.client.files.list()`,
        # and `self.save()` on every non-guard path. The stub must
        # provide that surface fully — otherwise a "flows-through"
        # test would AttributeError BEFORE the guard runs and pass
        # via the test's `except AttributeError: pass` swallow,
        # making the test tautological (passes regardless of guard
        # correctness). Caught by /review-pr on PR #94.
        #
        # `MAX_FILES = 0` short-circuits the upload loop via
        # `normalized[: 0]` — the loop body never runs, so the
        # heavy `client.files.upload` / `client.get_file` /
        # `genai.errors.APIError` surface isn't reached.
        from autonomous.ai.models.gemini import GeminiAIModel

        class _ClientFilesStub:
            @staticmethod
            def list():
                return []  # iterated for `[f.name for f in ...]`

        class _ClientStub:
            files = _ClientFilesStub()

        class _Stub:
            MAX_FILES = 0
            client = _ClientStub()

            def __init__(self):
                self.files = []
                self.file_refs = []

            def save(self):
                pass

        return GeminiAIModel, _Stub()

    def test_three_key_dict_with_name_and_file_raises(self):
        # The substance of #90: a 3-key dict containing BOTH "name"
        # and "file" plus extra metadata is the same misuse pattern
        # PR #85 was meant to catch, just one key wider. The
        # exact-equality form bypassed this; the subset form fires.
        GeminiAIModel, stub = self._stub()
        f = io.BytesIO(b"x")
        misused = {"name": "alice", "file": f, "extra": "metadata"}
        with pytest.raises(TypeError) as exc:
            GeminiAIModel._add_files(stub, misused)
        # Anchor the issue reference in the message — operators
        # debugging "why did this raise?" should land on #90.
        assert "#90" in str(exc.value) or "#85, #90" in str(exc.value), (
            f"TypeError message should reference #90 (or #85, #90); "
            f"got: {exc.value!r}"
        )

    def test_five_key_dict_with_name_and_file_raises(self):
        # Same intent at higher cardinality — proves the guard is
        # truly subset-checked, not "exactly 3 keys".
        GeminiAIModel, stub = self._stub()
        f = io.BytesIO(b"x")
        misused = {
            "name": "alice",
            "file": f,
            "metadata": {},
            "size": 100,
            "mime": "image/webp",
        }
        with pytest.raises(TypeError):
            GeminiAIModel._add_files(stub, misused)

    def test_two_key_dict_with_name_and_file_still_raises(self):
        # Regression pin against the pre-#85 behavior. The original
        # 2-key case must STILL trigger after the subset broadening.
        # Otherwise someone could "fix" #90 by accidentally
        # reverting to a guard that misses the original case.
        GeminiAIModel, stub = self._stub()
        f = io.BytesIO(b"x")
        misused = {"name": "alice", "file": f}
        with pytest.raises(TypeError):
            GeminiAIModel._add_files(stub, misused)

    def test_dict_with_only_name_key_flows_through(self):
        # A {filename: fileobj} dict where ONE filename happens to
        # be the literal string "name" but NOT also "file" is a
        # legitimate shape — guard must NOT fire. Proves the AND
        # (not OR) semantics of the new check.
        #
        # `MAX_FILES = 0` on the stub short-circuits the upload
        # loop so this call completes cleanly through the
        # guard-untrigger path and returns []. A regression that
        # ORed the keys (`"name" in fl or "file" in fl`) would
        # raise TypeError here.
        GeminiAIModel, stub = self._stub()
        f = io.BytesIO(b"x")
        legitimate = {"name": f, "other.webp": io.BytesIO(b"y")}
        result = GeminiAIModel._add_files(stub, legitimate)
        assert result == [], (
            f"With MAX_FILES=0 the upload loop short-circuits and "
            f"should return []. Guard absence proven by clean "
            f"return. Got: {result!r}"
        )

    def test_dict_with_only_file_key_flows_through(self):
        # Symmetric to the previous test: filename "file" alone must
        # not trip the guard. Together the two prove `and` semantics.
        GeminiAIModel, stub = self._stub()
        f = io.BytesIO(b"x")
        legitimate = {"file": f, "alice.webp": io.BytesIO(b"y")}
        result = GeminiAIModel._add_files(stub, legitimate)
        assert result == [], (
            f"Symmetric to the 'only-name' case: clean return "
            f"proves guard did not fire. Got: {result!r}"
        )


# ===========================================================================
# #93 — .gitignore for ruvector.db
# ===========================================================================


class TestRuvectorDbGitignored:
    """Pin both the .gitignore entry and its functional effect."""

    def test_gitignore_lists_ruvector_db(self):
        # Static pin: file is named in .gitignore. A regression that
        # accidentally drops the line during conflict resolution
        # would be caught here even without git available.
        content = pathlib.Path(".gitignore").read_text()
        # Match a stand-alone line (not commented out, not part of
        # a path component). Be tolerant of trailing whitespace
        # and either with or without a trailing newline.
        lines = [ln.strip() for ln in content.splitlines()]
        assert "ruvector.db" in lines, (
            f".gitignore must contain a stand-alone `ruvector.db` "
            f"entry per #93; not found in stripped line set."
        )

    def test_git_actually_ignores_ruvector_db(self):
        # Functional pin: `git check-ignore` agrees. Catches the
        # case where the entry is present but neutralized (e.g.
        # someone accidentally adds `!ruvector.db` later in the
        # file, which would un-ignore it).
        try:
            result = subprocess.run(
                ["git", "check-ignore", "-v", "ruvector.db"],
                capture_output=True,
                text=True,
                cwd=pathlib.Path(__file__).resolve().parents[2],
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pytest.skip("git not available or hung")
        # `git check-ignore` exits 0 when the path IS ignored, 1
        # when not ignored. Stdout names the matching rule.
        assert result.returncode == 0, (
            f"git check-ignore should report ruvector.db as ignored; "
            f"rc={result.returncode}, stdout={result.stdout!r}, "
            f"stderr={result.stderr!r}"
        )
        assert "ruvector.db" in result.stdout, (
            f"check-ignore output should reference the ruvector.db "
            f"rule; got: {result.stdout!r}"
        )
