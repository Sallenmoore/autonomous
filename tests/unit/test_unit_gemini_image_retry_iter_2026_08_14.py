"""Independent test-agent coverage for PR #206 / issue #203.

The Gemini image path gained a bounded retry around the "empty
Success" response, gated on ``finish_reason``:

- ``finish_reason=STOP`` with no image bytes → ``GenerateImage
  TransientEmptyError`` → retried up to ``_IMAGE_MAX_ATTEMPTS``.
- anything else (a safety block drops ``.content`` entirely, and the
  candidate list can be empty) → ``GenerateImageEmptyResponseError``
  → fails fast on the first call.

Written from the PR diff alone (dev's ``tests/_dev_local/`` is
gitignored and absent from the diff). What this file pins, and why
each pin is load-bearing rather than a restatement of the diff:

- **The gate is on the finish_reason, not on emptiness.** Both shapes
  produce "Success with no bytes"; only one is retryable. A refactor
  that catches the base class in the ``retry(catch=...)`` tuple would
  silently spend three billed ``generate_content`` calls on every
  safety block. The SAFETY tests assert the client was called
  **exactly once**, which is the only observable that distinguishes
  the two.
- **The exception hierarchy is a back-compat contract**, not
  cosmetics: the adapter used to raise a bare ``ValueError`` here and
  consumers (StoryTeller's ``generate_with_retry``) catch that. If a
  future cleanup re-parents these onto ``RuntimeError`` — matching the
  ``GenerateJSONError`` family — every one of those consumers stops
  catching and the failure escapes as an unhandled exception.
- **``_get_image_config`` must stay outside the retry loop.** It is
  the 4K-clamp breadcrumb emitter; running it per attempt triples the
  operator-facing log line for a single logical call.
- **``.content is None`` must surface as the typed error.** Pre-PR it
  escaped as ``AttributeError`` from ``None.parts`` — a type neither
  the caller's ``except ValueError`` nor the adapter's own handler
  caught.

Hermetic: hollow stub bound to the real ``generate_image``, no
AutoModel, no network, no genai client. Stub pattern follows
``test_unit_gemini_failure_paths_iter_2026_06_18.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from autonomous.ai.exceptions import (
    GenerateImageEmptyResponseError,
    GenerateImageTransientEmptyError,
)
from autonomous.ai.models.gemini import GeminiAIModel


IMAGE_BYTES = b"\x89PNG-stub-bytes"


# ---------------------------------------------------------------------------
# Response shapes the genai SDK hands back
# ---------------------------------------------------------------------------


class _FinishReason:
    """Stand-in for the genai ``FinishReason`` enum member — the only
    attribute the adapter reads off it is ``.name``."""

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"FinishReason.{self.name}"


class _Part:
    def __init__(self, data=None):
        self.inline_data = MagicMock(data=data) if data is not None else None


class _Candidate:
    def __init__(self, content, finish_reason):
        self.content = content
        self.finish_reason = finish_reason


class _Response:
    def __init__(self, candidates):
        self.candidates = candidates

    def __repr__(self):
        return "<stub gemini response>"


def _image_response():
    """Success: one part carrying inline image bytes."""
    content = MagicMock(parts=[_Part(), _Part(IMAGE_BYTES)])
    return _Response([_Candidate(content, _FinishReason("STOP"))])


def _empty_stop_response(finish_reason="STOP"):
    """The #203 shape: HTTP Success, ``finish_reason=STOP``, a single
    empty text part and no inline bytes."""
    content = MagicMock(parts=[_Part()])
    return _Response([_Candidate(content, _FinishReason(finish_reason))])


def _blocked_response(finish_reason="SAFETY"):
    """Safety-blocked candidate: the SDK drops ``.content`` entirely."""
    return _Response([_Candidate(None, _FinishReason(finish_reason))])


# ---------------------------------------------------------------------------
# Hollow model bound to the real generate_image
# ---------------------------------------------------------------------------


class _StubGemini:
    """Only the attributes ``generate_image`` actually reads.

    ``_IMAGE_RETRY_SLEEP`` is zeroed so the suite doesn't spend 3s of
    real backoff; the shipped values are pinned separately in
    ``TestRetryWiring`` so zeroing here cannot hide a regression in
    them.
    """

    _image_model = "gemini-stub-image"
    SAFETY_SETTINGS = GeminiAIModel.SAFETY_SETTINGS
    _IMAGE_MAX_ATTEMPTS = GeminiAIModel._IMAGE_MAX_ATTEMPTS
    _IMAGE_RETRY_SLEEP = 0

    generate_image = GeminiAIModel.generate_image

    def __init__(self, responses):
        self.client = MagicMock()
        self.client.models.generate_content.side_effect = responses
        self.image_config_calls = []

    def _get_image_config(self, aspect_ratio_input):
        self.image_config_calls.append(aspect_ratio_input)
        return "1:1", "2K"

    @property
    def call_count(self):
        return self.client.models.generate_content.call_count


def _make(responses):
    return _StubGemini(responses)


# ---------------------------------------------------------------------------
# 1. Exception hierarchy — the back-compat contract
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    def test_transient_is_a_subclass_of_the_base(self):
        # Catching the base MUST catch both forms; the docstring sells
        # exactly this ("Catch this to catch both forms").
        assert issubclass(
            GenerateImageTransientEmptyError, GenerateImageEmptyResponseError
        )

    @pytest.mark.parametrize(
        "exc_cls",
        [GenerateImageEmptyResponseError, GenerateImageTransientEmptyError],
    )
    def test_both_are_value_errors(self, exc_cls):
        # The adapter previously raised a bare ValueError here and
        # consumers already catch that to drive their own degrade path.
        # Re-parenting onto RuntimeError (matching the GenerateJSONError
        # family) would silently break every one of them.
        assert issubclass(exc_cls, ValueError)
        try:
            raise exc_cls("boom")
        except ValueError as e:
            assert str(e) == "boom"
        else:  # pragma: no cover - defensive
            pytest.fail(f"{exc_cls.__name__} escaped `except ValueError`")

    @pytest.mark.parametrize(
        "exc_cls",
        [GenerateImageEmptyResponseError, GenerateImageTransientEmptyError],
    )
    def test_neither_is_a_runtime_error(self, exc_cls):
        # Guards the inverse of the above: a consumer that catches
        # RuntimeError for the JSON family must NOT start swallowing
        # image failures too.
        assert not issubclass(exc_cls, RuntimeError)


# ---------------------------------------------------------------------------
# 2. STOP → retried
# ---------------------------------------------------------------------------


class TestTransientStopIsRetried:
    def test_empty_stop_then_success_returns_the_image(self):
        # The headline #203 fix: the observed blip clears on the next
        # identical call, so two empty STOPs followed by a good
        # response must produce an image, not an exception.
        stub = _make([_empty_stop_response(), _empty_stop_response(), _image_response()])

        assert stub.generate_image("a castle") == IMAGE_BYTES
        assert stub.call_count == 3

    def test_exhausted_budget_raises_the_transient_subclass(self):
        # On exhaustion the caller must be able to tell "provider gave
        # up after N attempts" from "you passed a bad argument" — that
        # is the whole point of the typed error.
        stub = _make([_empty_stop_response() for _ in range(3)])

        with pytest.raises(GenerateImageTransientEmptyError):
            stub.generate_image("a castle")
        assert stub.call_count == GeminiAIModel._IMAGE_MAX_ATTEMPTS

    def test_attempt_count_is_exactly_the_class_constant(self):
        # Pin attempts to the constant rather than the literal 3: a
        # bump to the constant should not need this test edited, but an
        # off-by-one in the loop (or a stray extra call) still fails.
        stub = _make(
            [_empty_stop_response() for _ in range(GeminiAIModel._IMAGE_MAX_ATTEMPTS + 2)]
        )

        with pytest.raises(GenerateImageEmptyResponseError):
            stub.generate_image("a castle")
        assert stub.call_count == GeminiAIModel._IMAGE_MAX_ATTEMPTS

    def test_plain_string_finish_reason_still_retried(self):
        # The adapter unwraps the enum via ``.name`` but is documented
        # to let a plain string fall through unchanged — a genai
        # version that stops boxing the value must not silently turn
        # every retryable response into a fail-fast one.
        content = MagicMock(parts=[_Part()])
        stub = _make(
            [
                _Response([_Candidate(content, "STOP")]),
                _image_response(),
            ]
        )

        assert stub.generate_image("a castle") == IMAGE_BYTES
        assert stub.call_count == 2

    def test_parts_none_is_treated_as_empty_not_a_crash(self):
        # ``for part in candidate.content.parts or []`` — a None parts
        # list must degrade to the typed empty error, not TypeError.
        content = MagicMock(parts=None)
        stub = _make(
            [
                _Response([_Candidate(content, _FinishReason("STOP"))]),
                _image_response(),
            ]
        )

        assert stub.generate_image("a castle") == IMAGE_BYTES
        assert stub.call_count == 2

    def test_retry_logs_a_breadcrumb_per_retried_attempt(self, monkeypatch):
        # Without the on_retry log, a provider degradation shows up as
        # latency with no operator-visible cause.
        logged = []
        monkeypatch.setattr(
            "autonomous.ai.models.gemini.log",
            lambda msg, *a, **kw: logged.append(str(msg)),
        )
        stub = _make([_empty_stop_response(), _image_response()])

        stub.generate_image("a castle")

        assert any("empty response" in m and "retrying" in m for m in logged), (
            f"expected a retry breadcrumb; got {logged!r}"
        )


# ---------------------------------------------------------------------------
# 3. Non-STOP → fails fast
# ---------------------------------------------------------------------------


class TestDeterministicEmptyFailsFast:
    @pytest.mark.parametrize("reason", ["SAFETY", "PROHIBITED_CONTENT"])
    def test_safety_block_raises_base_class_on_the_first_call(self, reason):
        # ONE client call is the load-bearing assertion: retrying a
        # deterministic block bills three image generations for a
        # result that cannot change. If a refactor widens the retry
        # catch to the base class, the exception type stays the same
        # and only this count moves.
        stub = _make([_blocked_response(reason) for _ in range(3)])

        with pytest.raises(GenerateImageEmptyResponseError) as excinfo:
            stub.generate_image("something the filter dislikes")

        assert not isinstance(excinfo.value, GenerateImageTransientEmptyError)
        assert stub.call_count == 1

    def test_content_none_is_typed_not_attribute_error(self):
        # Pre-PR this escaped as AttributeError from ``None.parts``,
        # bypassing both the consumer's ``except ValueError`` and the
        # adapter's own handler.
        stub = _make([_blocked_response("SAFETY")])

        with pytest.raises(ValueError):
            stub.generate_image("prompt")

    def test_no_candidates_at_all_fails_fast(self):
        # ``response.candidates == []`` leaves candidate=None, so
        # ``getattr(candidate, "finish_reason", None)`` is None → not
        # STOP → no retry.
        stub = _make([_Response([]) for _ in range(3)])

        with pytest.raises(GenerateImageEmptyResponseError) as excinfo:
            stub.generate_image("prompt")

        assert not isinstance(excinfo.value, GenerateImageTransientEmptyError)
        assert stub.call_count == 1

    def test_unknown_finish_reason_fails_fast(self):
        # Anything the adapter doesn't recognize gets the conservative
        # treatment (no billed retries), not the permissive one.
        stub = _make([_empty_stop_response("MAX_TOKENS") for _ in range(3)])

        with pytest.raises(GenerateImageEmptyResponseError) as excinfo:
            stub.generate_image("prompt")

        assert not isinstance(excinfo.value, GenerateImageTransientEmptyError)
        assert stub.call_count == 1

    def test_finish_reason_is_named_in_the_message(self):
        # The operator triaging a failed image has to know which shape
        # they hit; the reason is the only thing that distinguishes a
        # provider blip from a content block.
        stub = _make([_blocked_response("SAFETY")])

        with pytest.raises(GenerateImageEmptyResponseError) as excinfo:
            stub.generate_image("prompt")

        assert "SAFETY" in str(excinfo.value)

    @pytest.mark.parametrize("exc", [OSError("socket died"), RuntimeError("boom")])
    def test_non_empty_failures_are_not_retried(self, exc):
        # The retry catch is narrow by design: a transport error or a
        # permanent 4xx should surface immediately rather than burning
        # the budget. Second element would be consumed only if a retry
        # fired.
        stub = _make([exc, _image_response()])

        with pytest.raises(type(exc)):
            stub.generate_image("prompt")
        assert stub.call_count == 1


# ---------------------------------------------------------------------------
# 4. Happy path + loop-invariant work
# ---------------------------------------------------------------------------


class TestHappyPathAndLoopInvariants:
    def test_first_call_success_costs_one_call(self):
        # The retry must not change the cost of the common case.
        stub = _make([_image_response()])

        assert stub.generate_image("a castle") == IMAGE_BYTES
        assert stub.call_count == 1

    def test_first_inline_data_part_wins(self):
        # Multi-part responses: the loop breaks on the first part
        # carrying bytes, so a trailing text part cannot blank it.
        content = MagicMock(parts=[_Part(), _Part(IMAGE_BYTES), _Part(b"second")])
        stub = _make([_Response([_Candidate(content, _FinishReason("STOP"))])])

        assert stub.generate_image("a castle") == IMAGE_BYTES

    def test_image_config_resolved_once_across_retries(self):
        # It lives outside the retry closure precisely so the 4K-clamp
        # breadcrumb is emitted once per logical call, not once per
        # attempt.
        stub = _make([_empty_stop_response(), _empty_stop_response(), _image_response()])

        stub.generate_image("a castle", aspect_ratio="4K")

        assert stub.image_config_calls == ["4K"], (
            "aspect-ratio resolution MUST stay outside the retry loop; "
            f"got {stub.image_config_calls!r}"
        )

    def test_exhaustion_logs_the_unable_to_create_breadcrumb(self, monkeypatch):
        # The outer ``except (APIError, ValueError, OSError)`` still has
        # to see the exhausted error — it only does because the typed
        # error subclasses ValueError. A re-parent would silently drop
        # this log line as well as consumer catches.
        logged = []
        monkeypatch.setattr(
            "autonomous.ai.models.gemini.log",
            lambda msg, *a, **kw: logged.append(str(msg)),
        )
        stub = _make([_empty_stop_response() for _ in range(3)])

        with pytest.raises(GenerateImageTransientEmptyError):
            stub.generate_image("a castle")

        assert any("Unable to create image" in m for m in logged), (
            f"expected the outer failure breadcrumb; got {logged!r}"
        )


# ---------------------------------------------------------------------------
# 5. Retry wiring — the arguments the adapter hands the shared helper
# ---------------------------------------------------------------------------


class TestRetryWiring:
    def test_shipped_constants(self):
        # Pinned because _StubGemini zeroes the sleep: without this, a
        # change to the shipped backoff would be invisible to the file.
        assert GeminiAIModel._IMAGE_MAX_ATTEMPTS == 3
        assert GeminiAIModel._IMAGE_RETRY_SLEEP == 1.0

    def test_retry_is_given_only_the_transient_class(self, monkeypatch):
        # The catch tuple is the gate. Assert it directly so a widening
        # to the base class fails here with an obvious message, not
        # just as a billing surprise in the SAFETY tests.
        captured = {}
        real_retry = __import__(
            "autonomous.ai.retry", fromlist=["retry"]
        ).retry

        def _spy(func, **kwargs):
            captured.update(kwargs)
            return real_retry(func, **kwargs)

        monkeypatch.setattr("autonomous.ai.models.gemini.retry", _spy)
        stub = _make([_image_response()])

        stub.generate_image("a castle")

        assert captured["catch"] == (GenerateImageTransientEmptyError,), (
            "only the transient subclass may be retried; widening this "
            f"tuple bills 3 calls per safety block. Got {captured['catch']!r}"
        )
        assert captured["max_attempts"] == GeminiAIModel._IMAGE_MAX_ATTEMPTS
        assert captured["backoff_factor"] == 2.0
        assert captured["sleep_seconds"] == stub._IMAGE_RETRY_SLEEP
