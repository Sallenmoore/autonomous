"""Independent committed coverage for PR #81 / issue #75.

PR #81 adds best-effort orphan cleanup to ``GeminiAIModel._add_files``:
when the bounded poll loop raises ``GeminiFileUploadTimeoutError`` or
``genai.errors.APIError`` mid-poll, every file already appended to the
local ``uploaded_files`` accumulator is best-effort deleted via
``self.client.files.delete(name=...)`` BEFORE the original exception
re-raises. Pre-#75 these files leaked indefinitely on Gemini's storage
quota whenever a poll failed.

Independent perspective (no peek at dev's ``tests/_dev_local/``):
- Single-file timeout: cleanup deletes exactly the one orphan.
- Multi-file mid-batch: cleanup deletes ALL accumulated files, not
  just the one that timed out (the prior file_0 already polled to
  ACTIVE is just as orphaned from the caller's POV — the call as a
  whole failed, so the caller never gets the handle).
- ``genai.errors.APIError`` mid-poll triggers the same cleanup path
  (it's in the except tuple alongside the timeout).
- A single ``files.delete`` failure (APIError) is swallowed so it
  doesn't mask the original poll exception; remaining orphans still
  get a delete attempt.
- Happy path: NO deletes when the poll succeeds (over-eager cleanup
  would itself be a regression worth guarding).
- The poll target was switched from ``client.get_file`` (broken on
  google-genai >= 2.0) to ``client.files.get(name=...)``; pin that
  the source actually exercises the modern SDK shape.

Hermetic — ``time.monotonic`` / ``time.sleep`` are patched so the
suite stays sub-second.
"""

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Stub harness — same shape as test_unit_gemini_upload_poll_cap_iter_2026-06-11
# but constructed for orphan-cleanup scenarios (multi-file accumulators,
# APIError side-effects on delete, etc.). Built fresh from the PR diff —
# the gitignored dev `tests/_dev_local/` is not consulted.
# ---------------------------------------------------------------------------


class _APIError(Exception):
    """Stand-in for ``google.genai.errors.APIError``.

    The real SDK class lives at ``google.genai.errors.APIError``; we don't
    need to import it to drive the cleanup branch — the source's
    ``except (..., genai.errors.APIError)`` catches whatever is bound at
    ``gemini.genai.errors.APIError`` at call time. We patch the symbol
    on the gemini module so the source's `except` actually catches our
    stand-in.
    """


def _make_stub(per_file_poll_states):
    """Build a stub whose ``files.upload`` returns one handle per outer-loop
    iteration (one per file in the input list), and whose ``files.get``
    returns the polled states for the CURRENT file in sequence.

    ``per_file_poll_states`` is a list-of-lists: outer index = file index,
    inner list = poll states for that file's PROCESSING → ACTIVE walk.
    The first state in each inner list is the upload's initial state;
    subsequent states are consumed by ``files.get`` polls.
    """

    class _Stub:
        MAX_FILES = 10

        def save(self):
            pass

    stub = _Stub()
    stub.client = MagicMock()

    upload_handles = []
    poll_handles = []
    for file_idx, states in enumerate(per_file_poll_states):
        state_objs = []
        for s in states:
            so = MagicMock()
            so.name = s
            state_objs.append(so)
        upload_h = MagicMock()
        upload_h.name = f"files/upload-{file_idx}"
        upload_h.state = state_objs[0]
        upload_handles.append(upload_h)
        for s in state_objs[1:]:
            h = MagicMock()
            h.name = f"files/upload-{file_idx}"
            h.state = s
            poll_handles.append(h)

    stub.client.files.upload = MagicMock(side_effect=upload_handles)
    stub.client.files.list = MagicMock(return_value=[])
    stub.client.files.delete = MagicMock()
    stub.client.files.get = MagicMock(side_effect=poll_handles or [upload_handles[0]])
    return stub


def _files(n):
    return [{"name": f"file_{i}.json", "file": b"{}"} for i in range(n)]


def _call(stub, file_list):
    from autonomous.ai.models import gemini
    return gemini.GeminiAIModel._add_files(stub, file_list)


@pytest.fixture(autouse=True)
def _patch_api_error(monkeypatch):
    """Bind the source's ``genai.errors.APIError`` to our stand-in so the
    source's except clause catches the stand-in we raise."""
    from autonomous.ai.models import gemini
    monkeypatch.setattr(gemini.genai.errors, "APIError", _APIError, raising=False)
    yield


# ---------------------------------------------------------------------------
# 1) Single-file timeout → exactly one delete on the stuck orphan
# ---------------------------------------------------------------------------


def test_timeout_on_single_file_deletes_that_one_orphan(monkeypatch):
    from autonomous.ai.exceptions import GeminiFileUploadTimeoutError

    monkeypatch.setenv("GEMINI_UPLOAD_POLL_TIMEOUT", "1")
    stub = _make_stub([["PROCESSING", "PROCESSING", "PROCESSING"]])

    times = iter([0.0, 0.0, 2.0])
    with patch("autonomous.ai.models.gemini.time.monotonic", side_effect=lambda: next(times)), \
         patch("autonomous.ai.models.gemini.time.sleep"):
        with pytest.raises(GeminiFileUploadTimeoutError):
            _call(stub, _files(1))

    # The orphan-cleanup contract: every handle in the local accumulator
    # gets a `files.delete(name=...)` call before the exception re-raises.
    deletes = stub.client.files.delete.call_args_list
    # Each `files.delete` call may be preceded by the pre-upload delete
    # at line ~222 (per-file `try: delete; except APIError: pass`). The
    # only file we deleted pre-upload was "file_0.json"; the orphan-
    # cleanup delete uses "files/upload-0" (the upload handle name).
    orphan_calls = [c for c in deletes if c.kwargs.get("name", "").startswith("files/upload-")]
    assert len(orphan_calls) == 1, (
        f"single-file timeout should delete exactly the one orphan upload "
        f"handle; got {orphan_calls!r}"
    )
    assert orphan_calls[0].kwargs["name"] == "files/upload-0"


# ---------------------------------------------------------------------------
# 2) Multi-file mid-batch timeout → ALL accumulated orphans deleted
# ---------------------------------------------------------------------------


def test_timeout_on_second_file_deletes_both_orphans(monkeypatch):
    """File 0 polls ACTIVE successfully; file 1 stays PROCESSING and
    times out. The caller never gets either handle, so both are orphaned
    from the consumer's POV — both must be deleted."""
    from autonomous.ai.exceptions import GeminiFileUploadTimeoutError

    monkeypatch.setenv("GEMINI_UPLOAD_POLL_TIMEOUT", "1")
    stub = _make_stub([
        ["PROCESSING", "ACTIVE"],          # file 0: flips to ACTIVE on first poll
        ["PROCESSING", "PROCESSING"],      # file 1: stays stuck → timeout
    ])

    # Monotonic per file: each file's own deadline. File 0 reads
    # monotonic at start (0.0) for its deadline = 1.0, then once in the
    # while-loop guard at 0.0 (< 1.0 → continue, poll succeeds). File 1
    # reads monotonic at start (1.5) for its deadline = 2.5, then once
    # at 3.0 → triggers raise.
    times = iter([0.0, 0.0, 1.5, 3.0])
    with patch("autonomous.ai.models.gemini.time.monotonic", side_effect=lambda: next(times)), \
         patch("autonomous.ai.models.gemini.time.sleep"):
        with pytest.raises(GeminiFileUploadTimeoutError):
            _call(stub, _files(2))

    deletes = stub.client.files.delete.call_args_list
    orphan_calls = [c for c in deletes if c.kwargs.get("name", "").startswith("files/upload-")]
    deleted_names = sorted(c.kwargs["name"] for c in orphan_calls)
    assert deleted_names == ["files/upload-0", "files/upload-1"], (
        f"both accumulated orphans should be deleted, got {deleted_names!r}"
    )


# ---------------------------------------------------------------------------
# 3) APIError mid-poll triggers cleanup too
# ---------------------------------------------------------------------------


def test_api_error_mid_poll_triggers_orphan_cleanup(monkeypatch):
    """The source's except tuple is ``(GeminiFileUploadTimeoutError,
    genai.errors.APIError)``. An APIError raised by ``files.get`` during
    polling must trigger the SAME cleanup path — same orphan-leak
    failure mode."""
    monkeypatch.setenv("GEMINI_UPLOAD_POLL_TIMEOUT", "60")
    stub = _make_stub([["PROCESSING", "PROCESSING"]])

    # Replace `files.get` so the first poll raises APIError.
    stub.client.files.get = MagicMock(side_effect=_APIError("simulated gemini outage"))

    times = iter([0.0, 0.0])
    with patch("autonomous.ai.models.gemini.time.monotonic", side_effect=lambda: next(times)), \
         patch("autonomous.ai.models.gemini.time.sleep"):
        with pytest.raises(_APIError):
            _call(stub, _files(1))

    deletes = stub.client.files.delete.call_args_list
    orphan_calls = [c for c in deletes if c.kwargs.get("name", "").startswith("files/upload-")]
    assert len(orphan_calls) == 1
    assert orphan_calls[0].kwargs["name"] == "files/upload-0"


# ---------------------------------------------------------------------------
# 4) A single delete-APIError doesn't mask original exception and doesn't
#    skip remaining orphans
# ---------------------------------------------------------------------------


def test_delete_failure_is_suppressed_and_remaining_orphans_still_attempted(monkeypatch):
    """If the delete call for orphan #0 itself raises APIError (Gemini
    intermittently 5xx), the source must:
      (a) suppress it (do NOT raise APIError from the cleanup block);
      (b) still attempt the delete for orphan #1;
      (c) re-raise the ORIGINAL exception (the timeout), not APIError.

    The "swallow APIError on delete" branch is load-bearing for the
    contract — without it, a cleanup partial-failure becomes the
    observable exception and the operator can't tell what actually
    went wrong."""
    from autonomous.ai.exceptions import GeminiFileUploadTimeoutError

    monkeypatch.setenv("GEMINI_UPLOAD_POLL_TIMEOUT", "1")
    stub = _make_stub([
        ["PROCESSING", "ACTIVE"],
        ["PROCESSING", "PROCESSING"],
    ])

    # files.delete raises APIError ONLY for the first orphan; the
    # second orphan's delete succeeds. The pre-upload deletes (line ~222
    # of gemini.py) are filename-keyed, not handle-keyed; the orphan
    # cleanup uses the handle name. We trip on the first orphan-name
    # delete only.
    delete_calls = {"count": 0}

    def fake_delete(name=None):
        if name and name.startswith("files/upload-"):
            delete_calls["count"] += 1
            if delete_calls["count"] == 1:
                raise _APIError("simulated delete outage on orphan 0")
        return None

    stub.client.files.delete = MagicMock(side_effect=fake_delete)

    times = iter([0.0, 0.0, 1.5, 3.0])
    with patch("autonomous.ai.models.gemini.time.monotonic", side_effect=lambda: next(times)), \
         patch("autonomous.ai.models.gemini.time.sleep"):
        with pytest.raises(GeminiFileUploadTimeoutError):
            # ← Original timeout re-raised, NOT APIError-from-delete.
            _call(stub, _files(2))

    assert delete_calls["count"] == 2, (
        f"both orphans must get a delete attempt despite first failing; "
        f"got {delete_calls['count']}"
    )


# ---------------------------------------------------------------------------
# 5) Happy path: no over-eager cleanup
# ---------------------------------------------------------------------------


def test_happy_path_does_not_delete_anything(monkeypatch):
    """Regression guard — without this, an over-eager refactor that
    moved the cleanup outside the except clause would silently delete
    every file the caller wanted to use."""
    monkeypatch.setenv("GEMINI_UPLOAD_POLL_TIMEOUT", "60")
    stub = _make_stub([["PROCESSING", "ACTIVE"]])

    times = iter([0.0, 0.0])
    with patch("autonomous.ai.models.gemini.time.monotonic", side_effect=lambda: next(times)), \
         patch("autonomous.ai.models.gemini.time.sleep"):
        result = _call(stub, _files(1))

    assert len(result) == 1
    # The pre-upload delete (line ~222) is keyed off the input filename
    # ("file_0.json"), NOT the orphan handle name. No orphan-name delete
    # should fire.
    orphan_calls = [
        c for c in stub.client.files.delete.call_args_list
        if c.kwargs.get("name", "").startswith("files/upload-")
    ]
    assert orphan_calls == [], (
        f"happy path must not delete orphan handles; got {orphan_calls!r}"
    )


# ---------------------------------------------------------------------------
# 6) Source pins the modern SDK shape — uses ``files.get(name=...)``
# ---------------------------------------------------------------------------


def test_poll_uses_modern_files_get_path(monkeypatch):
    """``google-genai >= 2.0`` exposes the poll via ``client.files.get(
    name=...)`` — the legacy ``client.get_file(name)`` does not exist.
    Pin that the source actually invokes the modern attribute path,
    not the broken legacy one (which only "worked" because MagicMock
    silently accepts any attribute access)."""
    monkeypatch.setenv("GEMINI_UPLOAD_POLL_TIMEOUT", "60")
    stub = _make_stub([["PROCESSING", "ACTIVE"]])

    times = iter([0.0, 0.0])
    with patch("autonomous.ai.models.gemini.time.monotonic", side_effect=lambda: next(times)), \
         patch("autonomous.ai.models.gemini.time.sleep"):
        _call(stub, _files(1))

    # files.get fired exactly once (the single poll that returned ACTIVE)
    # and was called with name=... — the modern SDK kwarg.
    assert stub.client.files.get.call_count == 1
    call = stub.client.files.get.call_args
    assert "name" in call.kwargs, (
        f"poll must use the modern ``files.get(name=...)`` kwarg form, "
        f"not positional or the legacy ``client.get_file(name)`` path; "
        f"got {call!r}"
    )
    assert call.kwargs["name"] == "files/upload-0"
