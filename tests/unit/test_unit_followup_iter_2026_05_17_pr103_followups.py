"""Tests for the iter/2026-05-17-pr103-followups batch (PR #107).

Independent test-agent coverage for the 2-issue style cleanup that
addresses /review-pr findings on PR #103:

- **#104** — Source comment hygiene: trim multi-line narrative
  comments and remove PR/issue back-references (``See #85, #90``,
  ``See #85, #90, #100``, etc.) per CLAUDE.md "default to writing
  no comments / don't reference the current task, fix, or callers".
- **#105** — ``AutoUser.get_guest()`` log() ``_print`` symmetry:
  the bootstrap log() now uses ``_print=False`` too (was default
  True, asymmetric with the memoize log already at False).

Dev's PR #107 includes lockstep edits across two prior-iter test
files (re-anchoring discriminators that depended on the dropped
issue tags). Those lockstep tests pin the new English-phrase
substrings as discriminators — adequate for the precedence test
they were attached to.

This file pins ORTHOGONAL surfaces:

- **#104 behavioral pin**: live error messages from misuse
  triggers no longer contain ``#\\d+`` issue references. The
  lockstep tests pin POSITIVE substrings (what the message DOES
  contain); this pins the NEGATIVE direction (what the message
  must NOT contain). A regression that adds "See #107" or a
  bug-tracker auto-tagger would slip past dev's positive pin
  but be caught here.
- **#105 bootstrap-_print pin**: my prior cycle's
  ``TestGetGuestLogSideEffects.test_bootstrap_path_logs_bootstrap_and_memoize``
  pinned ``_print=False`` on the memoize call. The same test
  did NOT pin ``_print`` on the bootstrap call. Now that #105
  has unified both to ``_print=False``, this file adds the
  matching pin so a future re-asymmetry would fail.
"""

import io
import re

import pytest


# ===========================================================================
# #104 — error messages are now issue-ref-free (negative direction)
# ===========================================================================


class TestGeminiErrorMessagesIssueRefFree:
    """Pin that ``gemini._add_files`` error messages no longer
    contain ``#\\d+`` style issue references.

    The lockstep test ``test_three_key_dict_with_name_and_file_raises``
    pins the POSITIVE substring (``"with both 'name' and 'file' keys"``).
    This class pins the NEGATIVE direction: issue refs must NOT
    appear in the message body. A regression that adds an issue
    ref ("See #107", "Per issue #200", etc.) for any reason —
    accidental copy-paste, well-meaning attribution, automated
    bug-link tooling — would be caught here.

    Source-text pins on issue-ref absence are brittle because they
    can match unrelated content (comments, docstrings). Pin on the
    LIVE error message — what the operator actually sees in a
    traceback. This anchors the contract on observable behavior,
    not on source layout.
    """

    def _stub(self):
        # Same MAX_FILES=0 short-circuit stub used by the prior iter
        # file. Mirrored here rather than imported to keep tests
        # self-contained (each iter file is independently revertable).
        from autonomous.ai.models.gemini import GeminiAIModel

        class _ClientFilesStub:
            @staticmethod
            def list():
                return []

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

    _ISSUE_REF_RE = re.compile(r"#\d+")

    def test_both_keys_error_message_contains_no_issue_refs(self):
        GeminiAIModel, stub = self._stub()
        misuse = {"name": "alice.webp", "file": io.BytesIO(b"x")}

        with pytest.raises(TypeError) as exc:
            GeminiAIModel._add_files(stub, misuse)

        msg = str(exc.value)
        matches = self._ISSUE_REF_RE.findall(msg)
        assert matches == [], (
            f"both-keys error message must not contain '#\\d+' "
            f"issue refs per #104 hygiene rule. CLAUDE.md: "
            f"\"Don't reference the current task, fix, or callers.\" "
            f"Got refs: {matches!r} in message: {msg!r}"
        )

    def test_value_shape_error_message_contains_no_issue_refs(self):
        GeminiAIModel, stub = self._stub()
        misuse = {"some.webp": "should-be-file-obj"}  # str value

        with pytest.raises(TypeError) as exc:
            GeminiAIModel._add_files(stub, misuse)

        msg = str(exc.value)
        matches = self._ISSUE_REF_RE.findall(msg)
        assert matches == [], (
            f"value-shape error message must not contain '#\\d+' "
            f"issue refs per #104 hygiene rule. Got refs: "
            f"{matches!r} in message: {msg!r}"
        )

    # NOTE: A third path — the list-entry-shape error
    # ("_add_files list entries must be {'name', 'file'} dicts;
    # got ... See #85.") — was NOT swept by PR #107 and still
    # carries a "#85" issue ref. The omission is filed as a
    # follow-up issue for the next dev cycle so the hygiene rule
    # gets applied uniformly across the file. Not pinned here
    # because the gap wasn't fixed by this iter; pinning would
    # break the gate on green source.


# ===========================================================================
# #105 — bootstrap log _print=False (symmetry with memoize)
# ===========================================================================


class TestGetGuestBootstrapLogPrintFalse:
    """Pin that the BOOTSTRAP log() call in ``get_guest`` uses
    ``_print=False`` (option A from issue #105 — uniform with the
    memoize log line).

    My prior-cycle ``TestGetGuestLogSideEffects.test_bootstrap_path_logs_bootstrap_and_memoize``
    pinned ``_print=False`` on the memoize call only. The bootstrap
    call's ``_print`` kwarg was unasserted; #105 fixed the asymmetry
    by passing ``_print=False`` explicitly there too. A future edit
    that drops the kwarg (relying on default = stdout echo) would
    re-introduce the asymmetry — pin against it.

    The cost is real: bootstrap is once-per-process per AutoUser
    subclass under normal flow, but every fresh subclass at import
    time and every test that resets the cache triggers it. Stdout
    echo would clutter both production logs and CI test output.
    """

    def test_bootstrap_log_uses_print_false(self, monkeypatch):
        log_calls = []

        def _capture_log(msg, *args, **kwargs):
            log_calls.append((msg, kwargs))

        monkeypatch.setattr("autonomous.auth.user.log", _capture_log)

        # Stub a cls whose find() returns None to force the bootstrap
        # path. Same shape as my prior-cycle test, focused only on the
        # bootstrap-call _print kwarg.
        class _Stub:
            _cached_guest = None

            @classmethod
            def find(cls, **kw):
                return None

            def __init__(self, **kw):
                self.pk = "bootstrap_pk"

            def save(self):
                pass

        from autonomous.auth.user import AutoUser

        AutoUser.get_guest.__func__(_Stub)

        bootstrap_calls = [
            c for c in log_calls if "Bootstrapped" in str(c[0])
        ]
        assert len(bootstrap_calls) == 1, (
            f"bootstrap path must log exactly once. "
            f"Got: {bootstrap_calls!r}"
        )

        _, kwargs = bootstrap_calls[0]
        assert kwargs.get("_print") is False, (
            f"#105: bootstrap log must use _print=False for symmetry "
            f"with the memoize log line. Default _print=True would "
            f"echo to stdout on every fresh-subclass first-access. "
            f"Got kwargs: {kwargs!r}"
        )
