"""Independent coverage for PR #68 (#50 slice A).

PR #68 bounds the previously-unbounded ``GeminiAIModel._add_files``
PROCESSING poll loop with a wall-clock cap. Pre-#68, a file genuinely
stuck in PROCESSING (network drop mid-upload, malformed content,
backend outage) would spin the RQ worker forever with a 0.5s sleep
between probes. Post-#68, the cap defaults to 300s, is overridable via
``GEMINI_UPLOAD_POLL_TIMEOUT``, and raises a typed
``GeminiFileUploadTimeoutError`` on exhaustion so storyteller (and
any other consumer) can distinguish upload-stuck from other Gemini
failure modes without parsing the message.

Independent perspective (the test agent does not see dev's
``tests/_dev_local/``): these tests pin the contract from the diff
alone — exception identity, env override semantics, message shape,
and the no-timeout happy path. Mocks ``time.monotonic``/``time.sleep``
so the suite stays sub-second and deterministic regardless of CI load.
"""

import io
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Stub helpers (pattern lifted from pr83/pr88 followup tests — the only way
# to exercise _add_files hermetically given the lazy `client` property and
# the AutoModel.save() call at the tail of the method).
# ---------------------------------------------------------------------------


def _make_stub(upload_states):
    """Build a Gemini stub whose `client.get_file` returns objects with the
    states in ``upload_states`` (one per call). ``client.files.upload`` returns
    an initial uploaded_file whose state is ``upload_states[0]``; subsequent
    polls via ``get_file`` consume ``upload_states[1:]``.
    """

    class _Stub:
        MAX_FILES = 10

        def save(self):
            pass

    stub = _Stub()
    stub.client = MagicMock()

    # Each state name lives on a separate mock so identity comparisons
    # (Gemini's `uploaded_file.state.name`) work as expected.
    state_objs = []
    for name in upload_states:
        state_obj = MagicMock()
        state_obj.name = name
        state_objs.append(state_obj)

    upload_handle = MagicMock()
    upload_handle.name = "files/test-upload-handle"
    upload_handle.state = state_objs[0]
    stub.client.files.upload = MagicMock(return_value=upload_handle)
    stub.client.files.delete = MagicMock()
    stub.client.files.list = MagicMock(return_value=[])

    # Each subsequent `get_file` call returns a handle with the next state.
    poll_handles = []
    for s in state_objs[1:]:
        h = MagicMock()
        h.name = "files/test-upload-handle"
        h.state = s
        poll_handles.append(h)
    stub.client.get_file = MagicMock(side_effect=poll_handles or [upload_handle])
    return stub


def _file_list():
    return [{"name": "stuck.json", "file": b"{}"}]


def _call(stub, **kwargs):
    from autonomous.ai.models import gemini
    return gemini.GeminiAIModel._add_files(stub, _file_list(), **kwargs)


# ---------------------------------------------------------------------------
# Exception class — its identity is part of the public contract for consumers
# that want to selectively catch upload-stuck without parsing a message.
# ---------------------------------------------------------------------------


def test_timeout_error_is_runtime_error_subclass():
    """Storyteller (and other consumers) can `except RuntimeError` as a
    coarse catch or `except GeminiFileUploadTimeoutError` as a precise
    catch. The class must inherit from RuntimeError to keep both paths
    open."""
    from autonomous.ai.exceptions import GeminiFileUploadTimeoutError

    assert issubclass(GeminiFileUploadTimeoutError, RuntimeError)


def test_timeout_error_is_importable_from_exceptions_module():
    """Regression: pin the import path. A move to ``ai.models.gemini``
    or ``ai.errors`` would silently break ``from autonomous.ai.exceptions
    import GeminiFileUploadTimeoutError`` for consumers."""
    import autonomous.ai.exceptions as exc_mod

    assert hasattr(exc_mod, "GeminiFileUploadTimeoutError")


# ---------------------------------------------------------------------------
# Bounded-poll behavior — exhausting the cap, default cap, env override,
# happy path (no timeout when state flips in time).
# ---------------------------------------------------------------------------


def test_raises_when_state_stays_processing_past_deadline(monkeypatch):
    """The load-bearing behavior: a file that never leaves PROCESSING must
    NOT spin forever. With a 1s cap, the second monotonic check (>= deadline)
    must raise."""
    from autonomous.ai.exceptions import GeminiFileUploadTimeoutError

    monkeypatch.setenv("GEMINI_UPLOAD_POLL_TIMEOUT", "1")
    # All states PROCESSING — file is genuinely stuck.
    stub = _make_stub(["PROCESSING", "PROCESSING", "PROCESSING", "PROCESSING"])

    # Monotonic sequence: deadline = 0 + 1 = 1.0; first check at t=0 (continue),
    # poll, then check at t=1.5 → triggers raise.
    times = iter([0.0, 0.0, 1.5])
    with patch("autonomous.ai.models.gemini.time.monotonic", side_effect=lambda: next(times)), \
         patch("autonomous.ai.models.gemini.time.sleep"):
        with pytest.raises(GeminiFileUploadTimeoutError):
            _call(stub)


def test_timeout_error_message_carries_file_handle_and_cap(monkeypatch):
    """Operators reading a worker traceback need both pieces to triage:
    *which* file got stuck, and *how long* we waited before giving up.
    Pin both fragments — message wording can change, the data cannot."""
    from autonomous.ai.exceptions import GeminiFileUploadTimeoutError

    monkeypatch.setenv("GEMINI_UPLOAD_POLL_TIMEOUT", "2.5")
    stub = _make_stub(["PROCESSING", "PROCESSING"])
    times = iter([0.0, 0.0, 10.0])
    with patch("autonomous.ai.models.gemini.time.monotonic", side_effect=lambda: next(times)), \
         patch("autonomous.ai.models.gemini.time.sleep"):
        with pytest.raises(GeminiFileUploadTimeoutError) as excinfo:
            _call(stub)

    msg = str(excinfo.value)
    assert "files/test-upload-handle" in msg, (
        f"timeout message must name the stuck file handle for operator triage: {msg!r}"
    )
    assert "2.5" in msg, (
        f"timeout message must surface the cap that was exhausted: {msg!r}"
    )


def test_happy_path_no_timeout_when_state_flips_before_deadline(monkeypatch):
    """Regression guard: PR #68 must not break the normal case. A file that
    transitions PROCESSING → ACTIVE within the cap must complete without
    raising."""
    monkeypatch.setenv("GEMINI_UPLOAD_POLL_TIMEOUT", "60")
    # First state PROCESSING (from upload), one poll returns ACTIVE.
    stub = _make_stub(["PROCESSING", "ACTIVE"])

    # Deadline = 0 + 60 = 60. Real loop only checks monotonic once
    # (state != PROCESSING after first poll), then exits.
    times = iter([0.0, 1.0])
    with patch("autonomous.ai.models.gemini.time.monotonic", side_effect=lambda: next(times)), \
         patch("autonomous.ai.models.gemini.time.sleep"):
        result = _call(stub)

    assert len(result) == 1
    assert result[0].state.name == "PROCESSING"  # the appended uploaded_file


def test_env_override_actually_changes_deadline(monkeypatch):
    """Pin the env override semantics. Without the override, the diff's
    300s default would let this test wait nearly forever; with the override
    a tiny cap triggers the raise. If a future refactor stops reading
    ``GEMINI_UPLOAD_POLL_TIMEOUT``, this test goes red."""
    from autonomous.ai.exceptions import GeminiFileUploadTimeoutError

    monkeypatch.setenv("GEMINI_UPLOAD_POLL_TIMEOUT", "0.01")
    stub = _make_stub(["PROCESSING", "PROCESSING"])

    # With cap=0.01s and monotonic clock that advances to 0.5s on the second
    # check, the raise must fire. (If the env var were ignored and the
    # default 300s applied, deadline would be 300 and t=0.5 < 300 ⇒ no raise.)
    times = iter([0.0, 0.5])
    with patch("autonomous.ai.models.gemini.time.monotonic", side_effect=lambda: next(times)), \
         patch("autonomous.ai.models.gemini.time.sleep"):
        with pytest.raises(GeminiFileUploadTimeoutError):
            _call(stub)


def test_default_cap_is_300_seconds_when_env_unset(monkeypatch):
    """Pin the default. A future regression that lowers the default to a
    handful of seconds would silently break long-running uploads on slow
    networks; raising it to thousands would silently re-introduce the
    pre-#50 hang. 300s is what the diff & exception docstring commit to."""
    from autonomous.ai.exceptions import GeminiFileUploadTimeoutError

    monkeypatch.delenv("GEMINI_UPLOAD_POLL_TIMEOUT", raising=False)
    stub = _make_stub(["PROCESSING", "PROCESSING"])

    # If default = 300, t=299.99 must NOT raise; t=300.0 must raise.
    # The check is `monotonic() >= deadline`, so 300.0 == deadline raises.
    times = iter([0.0, 299.99])
    with patch("autonomous.ai.models.gemini.time.monotonic", side_effect=lambda: next(times)), \
         patch("autonomous.ai.models.gemini.time.sleep"):
        # Should NOT raise — t=299.99 is below the default 300 deadline.
        # But the iterator will exhaust after the inner check, so we let it
        # exhaust and verify NO timeout was raised by inspecting the
        # exception type only.
        try:
            _call(stub)
        except GeminiFileUploadTimeoutError:
            pytest.fail("default cap should be >= 300s but raised at t=299.99")
        except StopIteration:
            # Iterator exhausted — that's fine, means we got past the cap
            # check at 299.99 without raising.
            pass

    # Second pass: at the boundary, default cap should raise.
    stub2 = _make_stub(["PROCESSING", "PROCESSING"])
    times = iter([0.0, 300.0])
    with patch("autonomous.ai.models.gemini.time.monotonic", side_effect=lambda: next(times)), \
         patch("autonomous.ai.models.gemini.time.sleep"):
        with pytest.raises(GeminiFileUploadTimeoutError):
            _call(stub2)
