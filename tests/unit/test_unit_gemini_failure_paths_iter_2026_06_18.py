"""Gemini failure-path parity with ``openai_compat`` (closes #147).

The 2026-06-18 multi-agent audit (test-gap finder + its independent
sub-agent read) confirmed that ``gemini.py`` has five branches with no
unit coverage while their ``openai_compat`` analogs have a thorough
parametrized sweep. The asymmetry meant a refactor that "simplified"
any of those branches would silently leak raw stdlib exceptions past
the typed translation layer or alter the documented partial-summary
contract.

Five branches pinned:

1. ``generate_json`` ToolCall extraction outer except at gemini.py:441
   (``AttributeError`` / ``IndexError`` / ``KeyError`` / ``TypeError``)
   — translates SDK schema-drift failures to ``GenerateJSONParseError``.
2. ``response.text`` inner except at gemini.py:425-434
   (``AttributeError`` / ``TypeError``) — logs the SDK-drift breadcrumb
   so the wrong-tool-with-no-text case is distinguishable from
   wrong-tool-with-prose.
3. ``response.candidates[0].content is None`` intermediate guard at
   gemini.py:408 — the "safety filter dropped the candidate's
   ``.content`` entirely" path; existing tests always set
   ``candidates = []`` and never reach the intermediate ``None``.
4. ``_add_files`` orphan-cleanup outer except widened to bare
   ``Exception`` in #84 — only ``ValueError`` (via the
   ``UnknownApiResponseError`` stand-in) is exercised today; this
   pins that an arbitrary ``RuntimeError`` mid-poll still triggers
   cleanup.
5. ``summarize_text`` mid-loop ``break`` on ``(AttributeError,
   IndexError, genai.errors.APIError)`` at gemini.py:493 — partial
   summary contract: when the N-th chunk's response is malformed,
   the function must return the concatenation of the first N-1
   chunks' summaries, not raise and not silently continue.

All tests are hermetic — no network, no AutoModel, no real SDK.
"""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock

import pytest

from autonomous.ai.exceptions import (
    GenerateJSONEmptyResponseError,
    GenerateJSONParseError,
)


# ---------------------------------------------------------------------------
# Stub harness shared by the generate_json branches (1, 2, 3).
# ---------------------------------------------------------------------------


def _make_gemini_for_generate_json(response):
    """Build a hollow gemini instance bound to the real ``generate_json``
    and to a ``client`` whose ``models.generate_content`` returns
    ``response``. Mirrors ``_make_gemini_recorder`` in
    ``test_unit_gemini_translation_iter_2026_06_14.py`` but with the
    response shaped to drive failure branches rather than the happy
    path.
    """
    from autonomous.ai.models.gemini import GeminiAIModel

    class _Stub:
        instructions = "test"
        pk = "test-pk"
        _json_model = "gemini-test"
        file_refs: list = []

        def save(self):
            pass

        def _add_function(self, function):
            return {"name": function["name"]}

        def _add_context(self, context):
            return []

        generate_json = GeminiAIModel.generate_json

    stub = _Stub()
    stub.client = MagicMock()
    stub.client.models.generate_content.return_value = response
    return stub


def _make_response_with_part(part):
    """Wrap a single ``part`` stub in the full ``candidates[0].content.parts``
    nesting that ``generate_json`` walks."""
    response = MagicMock()
    content = MagicMock()
    content.parts = [part]
    candidate = MagicMock()
    candidate.content = content
    response.candidates = [candidate]
    return response


# ---------------------------------------------------------------------------
# 1) ToolCall extraction outer except (gemini.py:441)
# ---------------------------------------------------------------------------


class _RaisingFunctionCallPart:
    """Plain class whose ``function_call`` property raises the configured
    exception on access. Used instead of ``MagicMock(spec=...)`` +
    ``PropertyMock`` because MagicMock's ``__getattr__`` traps
    ``AttributeError`` and returns a fresh mock instead of letting the
    exception propagate — same quirk that ate the ``response.text`` SDK
    drift test and the ``summarize_text`` AttributeError parametrize
    case on the first run of this file."""

    def __init__(self, exc):
        self._exc = exc

    @property
    def function_call(self):
        raise self._exc


class TestToolCallExtractionCatchTuple:
    """Pin: every member of the ``except (AttributeError, IndexError,
    KeyError, TypeError)`` tuple at gemini.py:441 wraps to
    ``GenerateJSONParseError``. The tuple exists to defend against SDK
    schema drift; if a refactor narrows it, raw stdlib exceptions would
    leak past the typed translation layer to consumers."""

    @pytest.mark.parametrize(
        "raised_cls", [AttributeError, IndexError, KeyError, TypeError]
    )
    def test_each_member_of_the_catch_tuple_translates_to_parse_error(
        self, raised_cls
    ):
        part = _RaisingFunctionCallPart(
            raised_cls("simulated SDK schema drift")
        )
        response = _make_response_with_part(part)
        stub = _make_gemini_for_generate_json(response)

        with pytest.raises(GenerateJSONParseError) as excinfo:
            stub.generate_json("hello", json_schema={"type": "object"})

        # The typed wrapper preserves the original on __cause__ so
        # observability that walks the chain still sees the true type.
        assert isinstance(excinfo.value.__cause__, raised_cls)


# ---------------------------------------------------------------------------
# 2) response.text inner except (gemini.py:425-434)
# ---------------------------------------------------------------------------


class _WrongToolPart:
    """Plain-class part with a non-matching tool_call. The wrong-tool
    branch reads ``tool_call.name``, which doesn't match the function
    being asked for."""

    class _ToolCall:
        name = "some-other-tool"

        def __bool__(self):
            return True

    function_call = _ToolCall()


class _WrongToolResponseFailingText:
    """Plain-class response whose ``.text`` property raises the
    configured exception — used to drive gemini.py:426's inner
    ``except (AttributeError, TypeError)``."""

    def __init__(self, text_exc):
        self._text_exc = text_exc
        # Mirror ``response.candidates[0].content.parts[0]`` structure.
        self.candidates = [self]   # candidate
        self.content = self        # content (re-use to keep stub flat)
        self.parts = [_WrongToolPart()]

    @property
    def text(self):
        raise self._text_exc


class TestResponseTextSDKDriftBranch:
    """Pin: a wrong-tool response whose ``response.text`` access raises
    (SDK schema drift / tool-only response with no text accessor)
    emits the documented log breadcrumb and still raises
    ``GenerateJSONParseError`` — same outer shape as the
    wrong-tool-with-prose case so callers can rely on a uniform
    exception type."""

    @pytest.mark.parametrize("text_exc_cls", [AttributeError, TypeError])
    def test_response_text_failure_is_logged_and_caller_still_sees_parse_error(
        self, text_exc_cls, capsys
    ):
        response = _WrongToolResponseFailingText(
            text_exc_cls("SDK has no text accessor")
        )
        stub = _make_gemini_for_generate_json(response)

        with pytest.raises(GenerateJSONParseError) as excinfo:
            stub.generate_json("hello", json_schema={"type": "object"})

        # The wrong-tool message tells the caller the model called the
        # wrong tool — not that ``response.text`` exploded.
        assert "did not call function" in str(excinfo.value)

        # The breadcrumb from the inner except at gemini.py:431 is the
        # only signal a degraded SDK left behind. Without it a refactor
        # that swapped the log line for a silent ``pass`` would make
        # the wrong-tool-with-no-text case indistinguishable from
        # wrong-tool-with-prose in operator logs.
        out = capsys.readouterr().out
        assert "Could not read Gemini response.text" in out


# ---------------------------------------------------------------------------
# 3) candidates[0].content is None intermediate guard (gemini.py:408)
# ---------------------------------------------------------------------------


class TestNoContentIntermediateGuard:
    """Pin: a response with ``candidates=[<one>]`` where
    ``candidates[0].content is None`` (Gemini safety filters dropped the
    candidate content entirely) raises ``GenerateJSONEmptyResponseError``
    via the intermediate guard at gemini.py:408. Existing tests stub
    ``candidates = []`` to drive the FIRST disjunct of the no-content
    expression — the intermediate ``None`` guard had no coverage."""

    def test_content_is_none_raises_empty_response_error(self):
        candidate = MagicMock()
        candidate.content = None
        response = MagicMock()
        response.candidates = [candidate]

        stub = _make_gemini_for_generate_json(response)

        with pytest.raises(GenerateJSONEmptyResponseError):
            stub.generate_json("hello", json_schema={"type": "object"})


# ---------------------------------------------------------------------------
# 4) _add_files orphan-cleanup widened to bare Exception (gemini.py:267)
# ---------------------------------------------------------------------------


def _make_files_stub(state_chain):
    """Minimal stub for ``GeminiAIModel._add_files`` — exposes
    ``self.client.files.upload`` and ``self.client.files.get`` /
    ``.delete`` / ``.list``. ``state_chain`` is the sequence of poll
    states returned by ``files.get``."""
    from autonomous.ai.models.gemini import GeminiAIModel

    class _Stub:
        MAX_FILES = 10

        def save(self):
            pass

    stub = _Stub()
    stub.client = MagicMock()

    upload_h = MagicMock()
    upload_h.name = "files/orphan-0"
    upload_h.state = MagicMock(name="PROCESSING_state")
    upload_h.state.name = state_chain[0]

    stub.client.files.upload = MagicMock(return_value=upload_h)
    stub.client.files.list = MagicMock(return_value=[])
    stub.client.files.delete = MagicMock()
    return stub, upload_h


class TestOrphanCleanupOnArbitraryException:
    """Pin: the orphan-cleanup outer except at gemini.py:267 is
    deliberately ``except Exception:`` (widened in #84) so any failure
    mode the SDK might throw still triggers best-effort cleanup before
    the original exception re-propagates. The existing orphan-cleanup
    suite covers ``GeminiFileUploadTimeoutError``, ``genai.errors.APIError``,
    and ``ValueError`` (via the ``UnknownApiResponseError`` stand-in,
    which subclasses ``ValueError``). This pins an arbitrary
    ``RuntimeError`` — neither of those — still drives cleanup."""

    def test_runtime_error_mid_poll_still_triggers_orphan_delete(
        self, monkeypatch
    ):
        stub, upload_h = _make_files_stub(state_chain=["PROCESSING"])

        # ``client.files.get`` raises a RuntimeError on the first poll —
        # not GeminiFileUploadTimeoutError, not APIError, not ValueError.
        stub.client.files.get = MagicMock(
            side_effect=RuntimeError("simulated arbitrary SDK failure")
        )

        # Make time deterministic so the test doesn't actually sleep.
        monkeypatch.setattr("time.sleep", lambda _: None)

        from autonomous.ai.models import gemini

        with pytest.raises(RuntimeError):
            gemini.GeminiAIModel._add_files(
                stub, [{"name": "file.json", "file": b"{}"}]
            )

        # Cleanup fired on the uploaded orphan, even though the
        # triggering exception was outside the documented timeout /
        # APIError / ValueError set.
        # Note: ``_add_files`` also calls ``files.delete`` at gemini.py:223
        # BEFORE upload (to clean up any previous upload of the same
        # display name), so total ``delete`` count is 2. The orphan
        # cleanup is the second call — assert on the call with the
        # upload handle's ``.name``, not on call count.
        stub.client.files.delete.assert_any_call(name="files/orphan-0")


# ---------------------------------------------------------------------------
# 5) summarize_text mid-loop break (gemini.py:493-495)
# ---------------------------------------------------------------------------


class TestSummarizeTextPartialOnMidLoopFailure:
    """Pin the partial-summary contract: when the N-th chunk's
    ``generate_content`` returns a response whose
    ``candidates[0].content.parts[0].text`` access raises one of
    ``(AttributeError, IndexError, genai.errors.APIError)``,
    ``summarize_text`` MUST break out of the loop and return the
    concatenation of the first N-1 chunks' summaries — not raise, not
    silently continue with empty content, not return ``""``."""

    def _make_summary_stub(self, responses):
        """Stub gemini with a multi-call ``generate_content`` that
        returns the items in ``responses`` in order."""
        from autonomous.ai.models.gemini import GeminiAIModel

        class _Stub:
            MAX_SUMMARY_TOKEN_LENGTH = 3  # split input into small chunks
            instructions = "summarize"
            _summary_model = "gemini-test"

            summarize_text = GeminiAIModel.summarize_text

        stub = _Stub()
        stub.client = MagicMock()
        stub.client.models.generate_content = MagicMock(side_effect=responses)
        return stub

    class _GoodPart:
        def __init__(self, text):
            self.text = text

    class _PartRaisingOnText:
        def __init__(self, exc):
            self._exc = exc

        @property
        def text(self):
            raise self._exc

    def _wrap_part(self, part):
        """Wrap ``part`` in the nested
        ``candidates[0].content.parts[0]`` shape — plain class, not
        MagicMock, so AttributeError doesn't get trapped by MagicMock's
        ``__getattr__``."""

        class _Resp:
            candidates = [type("Cand", (), {"content": type("C", (), {"parts": [part]})()})()]

        return _Resp()

    def _good_response(self, text):
        return self._wrap_part(self._GoodPart(text))

    def _malformed_response_raising_on_text(self, exc):
        return self._wrap_part(self._PartRaisingOnText(exc))

    @pytest.mark.parametrize(
        "exc",
        [AttributeError("no .text"), IndexError("empty parts on second response")],
    )
    def test_break_on_malformed_response_returns_first_chunks_only(self, exc):
        # Three chunks. First two succeed; third returns the malformed
        # shape that raises ``exc`` on text access. Must return the
        # concatenation of the first two summaries (with trailing
        # newlines per the source's ``full_summary += summary + "\n"``).
        responses = [
            self._good_response("first-chunk-summary"),
            self._good_response("second-chunk-summary"),
            self._malformed_response_raising_on_text(exc),
        ]
        stub = self._make_summary_stub(responses)

        # MAX_SUMMARY_TOKEN_LENGTH=3 → three chunks of three words each.
        text = "alpha bravo charlie delta echo foxtrot golf hotel india"

        result = stub.summarize_text(text)

        assert "first-chunk-summary" in result
        assert "second-chunk-summary" in result
        # Critical pin: the break fires, so the third chunk's content
        # (which would be empty / the chunk text itself echoed) is NOT
        # in the output. The partial-summary contract is the whole
        # point of break-vs-continue.
        assert result.count("\n") == 2  # exactly the two successful chunks


# ---------------------------------------------------------------------------
# 6) Negative-space sanity: happy path still reaches generate_content
# ---------------------------------------------------------------------------


class TestHappyPathStillReachable:
    """A future refactor that moves the no_content guard or the
    extraction try/except too eagerly would silently break every
    well-formed call. Pin the happy path so the new guards don't fire
    on legitimate responses."""

    def test_well_formed_tool_call_returns_args(self):
        tool_call = MagicMock()
        tool_call.name = "response"  # matches the default schema_name
        tool_call.args = {"answer": "42"}
        tool_call.__bool__ = lambda self: True

        part = MagicMock()
        part.function_call = tool_call

        response = _make_response_with_part(part)
        stub = _make_gemini_for_generate_json(response)

        result = stub.generate_json("hello", json_schema={"type": "object"})

        assert result == {"answer": "42"}
