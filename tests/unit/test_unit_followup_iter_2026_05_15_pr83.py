"""Tests for the iter/2026-05-15-pr83-followup batch (PR #88).

Independent test-agent coverage for the two-issue tightening:

- **#84** — ``openai_compat._post`` now re-raises config-error
  subclasses (``MissingSchema``, ``InvalidURL``, ``InvalidSchema``,
  ``InvalidJSONError``) BEFORE the broader ``requests.RequestException``
  catch. Pre-#88 these were translated to ``HPCUnreachableError`` and
  triggered retry-spin against unfixable errors.
- **#85** — ``gemini._add_files`` now raises ``TypeError`` upfront
  for invalid shapes (bytes/str/naked-single-dict) instead of
  silently corrupting or producing late TypeError mid-loop.

Independent perspective: dev's ephemeral tests likely cover the
two new branches. This file pins:

1. **#84 propagation, not just `assert_not_called`** — verify the
   actual exception type bubbles up unchanged (so a Sentry alert
   sees `MissingSchema` not `HPCUnreachableError`).
2. **#84 broader catch UNCHANGED** for the cases it should still
   handle — a regression to "catch everything" (no carve-out) or
   "catch only the 4 config types" (no fallback) would break the
   PR #78 transport-failure contract.
3. **#85 each invalid shape raises with a useful message** — the
   error message must include the offending type/value so
   operators can identify the caller. The "#85" reference in the
   message is a forensic anchor.
4. **#85 valid shapes still work** — regression guard that the
   shape guard didn't accidentally narrow the accepted set.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests


# ===========================================================================
# #84 — openai_compat._post propagates config-error subclasses
# ===========================================================================


class TestOpenAIPostPropagatesConfigErrors:
    """Pin: the 4 config-error subclasses listed in #84 propagate
    RAW (no HPCUnreachableError translation, no retry). Verify the
    exception type AND that the retry path was NOT exercised.

    The PR's carve-out lists FOUR config-error types; pin ALL of
    them so a regression that drops any one slips through detection.
    """

    @pytest.fixture(autouse=True)
    def _silence_autotasks(self):
        with patch(
            "autonomous.ai.models.openai_compat.AutoTasks"
        ) as mock_tasks:
            mock_tasks.return_value.get_current_task.return_value = None
            yield mock_tasks

    def _make_client(self):
        # Set retry counters high enough that a missed carve-out
        # WOULD cause multiple sleep calls (the symptom #84
        # described). _retry_backoff=0 keeps the test fast either
        # way; the proof is `time.sleep.call_count == 0`.
        from autonomous.ai.models import openai_compat
        client = openai_compat.OpenAIClient.__new__(
            openai_compat.OpenAIClient
        )
        client._base_url = "http://stub"
        client._timeout = 1.0
        client._retry_attempts = 5  # high enough to detect retry
        client._retry_backoff = 0
        return client

    @pytest.mark.parametrize(
        "exc_class",
        [
            requests.exceptions.MissingSchema,
            requests.exceptions.InvalidURL,
            requests.exceptions.InvalidSchema,
            requests.exceptions.InvalidJSONError,
            # Added in lockstep with #89 — the original 4-type carve-
            # out was incomplete; URLRequired and InvalidHeader are
            # also pure config errors that retry will not help.
            # InvalidProxyURL is an InvalidURL subclass already caught
            # transitively but listed for MRO-drift defense.
            requests.exceptions.URLRequired,
            requests.exceptions.InvalidHeader,
            requests.exceptions.InvalidProxyURL,
            # Added in lockstep with #99 — SSLError + ProxyError are
            # corporate-proxy / cert-bundle misconfigs that retry will
            # not help and HPCUnreachable translation actively
            # misdirects on-call. ContentDecodingError is deliberately
            # NOT added — it can legitimately be transient.
            requests.exceptions.SSLError,
            requests.exceptions.ProxyError,
        ],
    )
    def test_config_error_propagates_raw(self, exc_class, monkeypatch):
        # The substance of #84: config errors must NOT be translated
        # to HPCUnreachableError. Verify the exact original type
        # bubbles up (`pytest.raises(exc_class)` catches subclasses
        # too, but the type assertion below pins exact class).
        from autonomous.ai.models import openai_compat
        client = self._make_client()
        sleep_calls = []
        monkeypatch.setattr(
            "autonomous.ai.retry.time.sleep",
            lambda s: sleep_calls.append(s),
        )
        with patch.object(
            openai_compat._SESSION, "post", side_effect=exc_class("boom"),
        ):
            with pytest.raises(exc_class) as excinfo:
                client._post("test/path", {"k": "v"})
        # Exact class match — `pytest.raises(MissingSchema)` would
        # also match `HPCUnreachableError(MissingSchema)` in some
        # nesting patterns; pin exact identity.
        assert type(excinfo.value) is exc_class, (
            f"Config-error must propagate as the original "
            f"{exc_class.__name__}, not be translated. Got: "
            f"{type(excinfo.value).__name__}"
        )
        # Crucially: NO retry sleeps fired. Pre-#84 the wrapper
        # would have burned _retry_attempts-1 = 4 sleeps against
        # this unfixable error.
        assert sleep_calls == [], (
            f"Config errors must not be retried (defeats the carve-"
            f"out's whole point). Got sleeps: {sleep_calls}"
        )


class TestOpenAIPostBroaderCatchStillHandlesPoolErrors:
    """Pin: the carve-out for config errors did NOT accidentally
    break the PR #78 contract that ``RetryError`` and
    ``ChunkedEncodingError`` still translate to
    ``HPCUnreachableError``. A regression where the carve-out also
    matched those (e.g. via too-broad isinstance) would silently
    re-introduce #78's original bug."""

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
        client._retry_attempts = 1
        client._retry_backoff = 0
        return client

    @pytest.mark.parametrize(
        "exc_class",
        [
            requests.exceptions.RetryError,
            requests.exceptions.ChunkedEncodingError,
            requests.ConnectionError,
            requests.Timeout,
        ],
    )
    def test_transport_failure_still_translates(self, exc_class):
        # PR #78 contract preserved — these all become
        # HPCUnreachableError.
        from autonomous.ai.models import openai_compat
        client = self._make_client()
        with patch.object(
            openai_compat._SESSION, "post", side_effect=exc_class("boom"),
        ):
            with pytest.raises(openai_compat.HPCUnreachableError):
                client._post("test/path", {"k": "v"})

    def test_carve_out_covers_multipart_post_path_too(self, monkeypatch):
        # `_post` has TWO `_SESSION.post` call sites — json (the
        # else branch) and multipart (the `if files is not None`
        # branch). Both live inside ONE try block today, so the
        # carve-out + broader catch apply equally to both. Pin this
        # by exercising the multipart path — a future restructure
        # that splits the try blocks (giving each post its own
        # except) and forgets to copy the carve-out to one of them
        # would silently regress.
        from autonomous.ai.models import openai_compat
        client = self._make_client()
        sleep_calls = []
        monkeypatch.setattr(
            "autonomous.ai.retry.time.sleep",
            lambda s: sleep_calls.append(s),
        )
        # Drive the multipart path by passing files=. MissingSchema
        # propagation should hold on this path the same as on json.
        with patch.object(
            openai_compat._SESSION,
            "post",
            side_effect=requests.exceptions.MissingSchema("bad url"),
        ):
            with pytest.raises(
                requests.exceptions.MissingSchema
            ) as excinfo:
                client._post(
                    "upload/path", files={"f": ("x", b"data")}
                )
        assert type(excinfo.value) is requests.exceptions.MissingSchema
        # And: no retry sleeps on the multipart path either.
        assert sleep_calls == [], (
            f"multipart-path config error must not be retried; "
            f"got: {sleep_calls}"
        )


# ===========================================================================
# #85 — gemini._add_files shape guard
# ===========================================================================


class TestGeminiAddFilesShapeGuard:
    """Pin: the 3 invalid shapes ``_add_files`` previously accepted
    silently (or with late TypeError) now raise upfront with a
    diagnostic message. Pin error type AND that the message
    references the bad input — operators investigating Sentry
    traces need the offending value to identify the caller."""

    def _make_gemini_stub(self):
        # Re-uses the stub pattern from the iter/2026-05-15-pr76
        # file — call _add_files as an unbound method with a
        # hand-built self to bypass the `client` property.
        class _Stub:
            MAX_FILES = 10

            def save(self):
                pass

        stub = _Stub()
        stub.client = MagicMock()
        upload_handle = MagicMock()
        upload_handle.state.name = "READY"
        stub.client.files.upload = MagicMock(return_value=upload_handle)
        stub.client.files.delete = MagicMock()
        stub.client.files.list = MagicMock(return_value=[])
        return stub

    def _call(self, stub, file_list, **kwargs):
        from autonomous.ai.models import gemini
        return gemini.GeminiAIModel._add_files(stub, file_list, **kwargs)

    def test_bytes_input_raises_typeerror(self):
        # bytes is iterable — `list(b"abc")` produces `[97, 98, 99]`,
        # and the pre-#85 loop would have TypeError'd on `f["name"]`
        # mid-iteration. Now: explicit upfront rejection. Pin the
        # type only (not the exact prose), so a benign rewording
        # of the message ("expects a sequence of dicts") doesn't
        # break the test.
        stub = self._make_gemini_stub()
        with pytest.raises(TypeError) as excinfo:
            self._call(stub, b"some bytes payload")
        # The type name is the load-bearing semantic content for
        # operator triage — pin that.
        assert "bytes" in str(excinfo.value).lower()

    def test_str_input_raises_typeerror(self):
        # str is iterable (chars), same risk as bytes.
        stub = self._make_gemini_stub()
        with pytest.raises(TypeError) as excinfo:
            self._call(stub, "filename.json")
        assert "str" in str(excinfo.value).lower()

    def test_naked_single_file_dict_raises_typeerror(self):
        # The subtle silent-corruption case from #85: a dict that
        # LOOKS like a valid list entry, passed in unwrapped. The
        # `isinstance(..., dict)` branch fires and iterates the
        # outer dict's items, producing wrong-shape "entries".
        # Pin upfront rejection. Pin the load-bearing semantic
        # ('name' and 'file' both mentioned) rather than the exact
        # message format.
        stub = self._make_gemini_stub()
        with pytest.raises(TypeError) as excinfo:
            self._call(stub, {"name": "x.json", "file": MagicMock()})
        msg = str(excinfo.value)
        assert "'name'" in msg and "'file'" in msg, (
            f"single-file-dict error message must mention BOTH "
            f"'name' and 'file' keys so operators can recognize "
            f"the offending shape; got: {msg}"
        )

    def test_list_with_non_dict_entry_raises_typeerror(self):
        # Each list entry must be a `{name, file}` dict. A regression
        # where someone passed `["filename1", "filename2"]` (list of
        # strings) would silently corrupt pre-fix; now: TypeError.
        stub = self._make_gemini_stub()
        bad = [{"name": "a.json", "file": MagicMock()}, "not-a-dict"]
        with pytest.raises(TypeError) as excinfo:
            self._call(stub, bad)
        # Semantic pin: message names both required keys somewhere.
        msg = str(excinfo.value)
        assert "'name'" in msg and "'file'" in msg

    def test_int_or_none_raises_typeerror(self):
        # Negative-space pin: non-iterable types are also rejected
        # explicitly (rather than crashing on `list(...)`).
        stub = self._make_gemini_stub()
        with pytest.raises(TypeError):
            self._call(stub, 42)
        with pytest.raises(TypeError):
            self._call(stub, None)


class TestGeminiAddFilesValidShapesStillWork:
    """Regression guard: the shape guard didn't accidentally
    narrow the accepted set. Both documented shapes still work
    (list-of-dicts, dict-of-fileobjs) AND tuple-of-dicts (the
    `isinstance(..., (list, tuple))` branch — a likely benign
    caller variant)."""

    def _make_gemini_stub(self):
        class _Stub:
            MAX_FILES = 10

            def save(self):
                pass

        stub = _Stub()
        stub.client = MagicMock()
        upload_handle = MagicMock()
        upload_handle.state.name = "READY"
        stub.client.files.upload = MagicMock(return_value=upload_handle)
        stub.client.files.delete = MagicMock()
        stub.client.files.list = MagicMock(return_value=[])
        return stub

    def _call(self, stub, file_list, **kwargs):
        from autonomous.ai.models import gemini
        return gemini.GeminiAIModel._add_files(stub, file_list, **kwargs)

    def test_tuple_of_dicts_shape_works(self):
        # PR #88's `isinstance(file_list, (list, tuple))` accepts
        # tuples too. Pin this so a future re-narrowing to `list`-
        # only would surface as a regression rather than slip past.
        stub = self._make_gemini_stub()
        files = (
            {"name": "a.json", "file": MagicMock()},
            {"name": "b.json", "file": MagicMock()},
        )
        self._call(stub, files)
        assert stub.client.files.upload.call_count == 2

    def test_dict_of_multiple_fileobjs_still_works(self):
        # The single-file `{name, file}` dict is rejected by #85,
        # but a multi-key `{filename: fileobj, filename2: fileobj2}`
        # dict is still valid and is the documented shape from
        # generate_image and storyteller's ImageAgent.
        stub = self._make_gemini_stub()
        # Two entries — distinct from the single-file rejection
        # because keys aren't exactly {"name", "file"}.
        files = {
            "a.json": MagicMock(),
            "b.json": MagicMock(),
        }
        self._call(stub, files)
        assert stub.client.files.upload.call_count == 2
