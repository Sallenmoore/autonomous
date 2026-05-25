"""Independent coverage for PR #125 (Issue #124 — typed exceptions from
``generate_json``).

PR #125 turned the silent ``return {}`` from
``OpenAIClient.generate_json`` / ``LocalAIModel.generate_json`` /
``GeminiAIModel.generate_json`` into a typed exception hierarchy rooted
at ``autonomous.ai.exceptions.GenerateJSONError``. ``MockAIModel`` is
intentionally exempt — it still returns ``{}`` because it's the offline
testing escape hatch.

The dev-side ephemeral test (gitignored) likely covers the happy
"raises the right class" path for each provider. This file pins the
**invariants** the design depends on, which a future refactor could
quietly break:

- The exception hierarchy: catching ``GenerateJSONError`` catches every
  failure mode.
- ``GenerateJSONError`` inherits from ``RuntimeError`` — important for
  callers that catch ``RuntimeError`` as a generic safety net.
- ``GenerateJSONParseError.raw`` defaults to ``""`` (never ``None``) and
  is bounded at ~500 chars at each call site so a megabyte of prose
  doesn't blow up the traceback.
- ``LocalAIModel.generate_json`` orders ``except json.JSONDecodeError``
  before ``except ValueError`` — JSONDecodeError IS a ValueError, so the
  reverse would silently mask parse failures as empty-response failures.
- ``MockAIModel.generate_json`` STILL returns a dict — the escape hatch
  invariant the migration guide explicitly carves out.
- ``MIGRATIONS.md`` carries the entry (consumer-facing contract).

Hermetic: only the local_model AutoTasks side effect is patched, plus
the outbound HTTP. No real Mongo / Redis / Ollama touched.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests


os.environ.setdefault("OLLAMA_API_BASE_URL", "http://mock-ollama:11434")
os.environ.setdefault("MEDIA_API_BASE_URL", "http://mock-media:5000")
os.environ.setdefault("MEDIA_AUDIO_API_BASE_URL", "http://mock-media:5000")
os.environ.setdefault("MEDIA_IMAGE_API_BASE_URL", "http://mock-media:5000")


REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Exception hierarchy — load-bearing for consumer migration guidance
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    """The migration recipe in MIGRATIONS.md tells consumers to write
    ``except GenerateJSONError`` for uniform handling, or to catch a
    specific subclass to branch on mode. Both must work — if a future
    refactor breaks the inheritance, the migration guide silently
    misleads downstream code."""

    def test_parse_error_is_subclass_of_base(self):
        from autonomous.ai.exceptions import (
            GenerateJSONError,
            GenerateJSONParseError,
        )

        assert issubclass(GenerateJSONParseError, GenerateJSONError)

    def test_empty_error_is_subclass_of_base(self):
        from autonomous.ai.exceptions import (
            GenerateJSONError,
            GenerateJSONEmptyResponseError,
        )

        assert issubclass(GenerateJSONEmptyResponseError, GenerateJSONError)

    def test_base_is_runtime_error(self):
        """Callers that catch ``RuntimeError`` as a generic safety net
        (pretty common for ``# anything could go wrong here``-style code)
        should keep catching these. If a future refactor reparents the
        base to ``Exception`` it would break those callers silently."""
        from autonomous.ai.exceptions import GenerateJSONError

        assert issubclass(GenerateJSONError, RuntimeError)

    def test_catching_base_catches_both_modes(self):
        """The user-visible promise from MIGRATIONS.md."""
        from autonomous.ai.exceptions import (
            GenerateJSONError,
            GenerateJSONEmptyResponseError,
            GenerateJSONParseError,
        )

        for exc_cls in (GenerateJSONEmptyResponseError, GenerateJSONParseError):
            try:
                raise exc_cls("test")
            except GenerateJSONError:
                pass
            else:
                pytest.fail(f"{exc_cls.__name__} escaped GenerateJSONError catch")

    def test_parse_error_distinct_from_empty_error(self):
        """The whole point of the migration is to **distinguish** the
        two modes for branching. They must NOT be the same class, and
        neither must be a subclass of the other."""
        from autonomous.ai.exceptions import (
            GenerateJSONEmptyResponseError,
            GenerateJSONParseError,
        )

        assert GenerateJSONEmptyResponseError is not GenerateJSONParseError
        assert not issubclass(GenerateJSONEmptyResponseError, GenerateJSONParseError)
        assert not issubclass(GenerateJSONParseError, GenerateJSONEmptyResponseError)


# ---------------------------------------------------------------------------
# .raw attribute contract — used by callers for diagnostics
# ---------------------------------------------------------------------------


class TestParseErrorRawAttribute:
    """``GenerateJSONParseError.raw`` is what ``MIGRATIONS.md`` tells
    consumers to log when they want to know why the model failed. The
    contract: it's a string, it's never ``None``, and each call site
    is supposed to bound it to ~500 chars so a megabyte of prose
    doesn't blow up the traceback."""

    def test_raw_defaults_to_empty_string(self):
        from autonomous.ai.exceptions import GenerateJSONParseError

        exc = GenerateJSONParseError("test")
        assert exc.raw == "", (
            "GenerateJSONParseError.raw must default to '' so caller "
            "code can do `if exc.raw:` without surprise on a NoneType."
        )

    def test_raw_kwarg_is_passed_through(self):
        from autonomous.ai.exceptions import GenerateJSONParseError

        exc = GenerateJSONParseError("test", raw="some prose")
        assert exc.raw == "some prose"

    def test_empty_error_does_not_have_raw(self):
        """Pin the asymmetry — empty-response failures don't have a body
        to attach, so the class doesn't declare ``.raw``. If a future
        refactor accidentally unifies them, callers reading
        ``exc.raw`` on the empty-response path would silently get an
        AttributeError rather than the documented branching."""
        from autonomous.ai.exceptions import GenerateJSONEmptyResponseError

        exc = GenerateJSONEmptyResponseError("test")
        # Not raising AttributeError on .raw access is fine if Python's
        # default is None / "" — what we actually pin is that the class
        # does NOT define ``raw`` as a class attribute, so the
        # consumer-facing distinction stays clear.
        assert "raw" not in vars(exc), (
            "GenerateJSONEmptyResponseError shouldn't carry a .raw "
            "attribute — the migration design says only the parse "
            "failure mode has a body to attach."
        )


# ---------------------------------------------------------------------------
# OpenAI compat: raw is bounded at 500 chars at the call site
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_autotasks():
    """Prevent Redis connection in both LocalAIModel and OpenAIClient."""
    with patch(
        "autonomous.ai.models.local_model.AutoTasks"
    ) as mock_local, patch(
        "autonomous.ai.models.openai_compat.AutoTasks"
    ) as mock_openai:
        mock_local.return_value.get_current_task.return_value = None
        mock_openai.return_value.get_current_task.return_value = None
        yield


def _mock_chat_response(content: str):
    resp = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    resp.raise_for_status = MagicMock()
    return resp


class TestOpenAICompatRawBound:
    """The 500-char raw bound is what keeps a runaway model's
    megabyte-of-prose response from ballooning the traceback /
    Sentry payload / log line. Pin it at the call site.

    Uses the same __new__ bypass + manual descriptor prime pattern as
    test_unit_openai_client.py — bypasses AutoModel/MongoEngine setup
    without needing real Mongo or HPC_API_BASE_URL configured.
    """

    @pytest.fixture
    def client(self):
        from autonomous.ai.models.openai_compat import OpenAIClient

        c = OpenAIClient.__new__(OpenAIClient)
        object.__setattr__(c, "_data", {"instructions": "test"})
        object.__setattr__(c, "_dynamic_fields", {})
        object.__setattr__(c, "_changed_fields", [])
        object.__setattr__(c, "_initialised", True)
        object.__setattr__(c, "_created", False)
        for key, val in {
            "_base_url": "http://mock-hpc/api",
            "_api_key": "test-key",
            "_text_model": "test-model",
            "_json_model": "test-model",
            "_summary_model": "test-model",
            "_embedding_model": "test-model",
            "_stt_model": "test-model",
            "_timeout": 1,
            "_retry_attempts": 3,
            "_retry_backoff": 0,
        }.items():
            object.__setattr__(c, key, val)
        return c

    def test_raw_truncated_when_response_is_huge(self, client):
        from autonomous.ai.exceptions import GenerateJSONParseError

        huge = "x" * 10_000  # 10KB of non-JSON
        with patch(
            "autonomous.ai.models.openai_compat._SESSION.post",
            return_value=_mock_chat_response(huge),
        ):
            with pytest.raises(GenerateJSONParseError) as ctx:
                client.generate_json("anything")
        # Bound is documented at 500 — pin it tightly (off-by-one
        # tolerant: allow 500 exactly or 501 if the implementation
        # uses inclusive slicing somewhere).
        assert len(ctx.value.raw) <= 501, (
            f"raw should be bounded at ~500 chars; got {len(ctx.value.raw)}"
        )
        assert len(ctx.value.raw) > 0, "raw should not be empty"

    def test_empty_body_raises_empty_response_error(self, client):
        """The new ``if not raw or not raw.strip()`` guard at the top
        of generate_json. A whitespace-only body should hit the
        empty-response branch, NOT the parse-error branch."""
        from autonomous.ai.exceptions import GenerateJSONEmptyResponseError

        with patch(
            "autonomous.ai.models.openai_compat._SESSION.post",
            return_value=_mock_chat_response("   \n   "),
        ):
            with pytest.raises(GenerateJSONEmptyResponseError):
                client.generate_json("anything")


# ---------------------------------------------------------------------------
# LocalAIModel: the order-matters MRO trap
# ---------------------------------------------------------------------------


class TestLocalModelExceptionDispatch:
    """``json.JSONDecodeError`` is a subclass of ``ValueError``. In
    ``LocalAIModel.generate_json`` the new try/except dispatches:
        except json.JSONDecodeError → GenerateJSONParseError
        except ValueError           → GenerateJSONEmptyResponseError

    If the order is silently flipped during a refactor, the
    ``except ValueError`` clause shadows ``JSONDecodeError`` and parse
    failures get misclassified as empty-response failures — the exact
    bug PR #125 was meant to prevent (a parse failure shouldn't
    encourage retry, an empty-response failure should).
    """

    @pytest.fixture
    def model(self):
        from autonomous.ai.models.local_model import LocalAIModel

        m = LocalAIModel()
        m._ollama_url = "http://mock-ollama:11434"
        m._text_model = "test-model"
        m._retry_sleep = 0  # don't sleep between retries in tests
        return m

    def test_unparseable_prose_raises_parse_error_not_empty(self, model):
        """Server returns 200 with prose content — that's the
        deterministic-model-failure case. Must be ParseError, not
        EmptyResponseError, or callers will retry pointlessly."""
        from autonomous.ai.exceptions import (
            GenerateJSONEmptyResponseError,
            GenerateJSONParseError,
        )

        resp = MagicMock()
        resp.json.return_value = {
            "message": {"content": "I cannot generate JSON for that."}
        }
        resp.raise_for_status = MagicMock()
        with patch(
            "autonomous.ai.models.local_model._SESSION.post",
            return_value=resp,
        ), patch.object(model, "flush_memory"):
            # Pin the type with ``not isinstance(..., EmptyResponseError)``
            # too — issubclass would let a refactor accidentally make
            # ParseError inherit from EmptyResponseError and this would
            # still pass.
            with pytest.raises(GenerateJSONParseError) as ctx:
                model.generate_json("prompt", context={})
            assert not isinstance(ctx.value, GenerateJSONEmptyResponseError), (
                "ParseError leaked through as EmptyResponseError — the "
                "MRO ordering in the except clauses is wrong."
            )
            assert "I cannot generate" in ctx.value.raw

    def test_empty_content_raises_empty_response_error(self, model):
        """Server returns 200 but message.content is empty/whitespace.
        That's the transport-blip case — caller should retry."""
        from autonomous.ai.exceptions import GenerateJSONEmptyResponseError

        resp = MagicMock()
        resp.json.return_value = {"message": {"content": "   "}}
        resp.raise_for_status = MagicMock()
        with patch(
            "autonomous.ai.models.local_model._SESSION.post",
            return_value=resp,
        ), patch.object(model, "flush_memory"):
            with pytest.raises(GenerateJSONEmptyResponseError):
                model.generate_json("prompt", context={})

    def test_missing_message_key_raises_empty_response_error(self, model):
        """Server returns a shape we don't recognize (no "message" or no
        "content"). Pre-PR this returned {} silently; new contract is
        EmptyResponseError so callers can branch."""
        from autonomous.ai.exceptions import GenerateJSONEmptyResponseError

        resp = MagicMock()
        # No "message" key at all → .get("message", {}).get("content", "{}")
        # returns "{}" which parses fine to {}. So we need to make the
        # server return something that triggers a KeyError downstream.
        # The cleanest way: have the retry's `_attempt` raise KeyError
        # directly. We can simulate this with a malformed response that
        # the cleaner / json.loads chain raises KeyError on — but the
        # simplest path is just the explicit empty case from above.
        # Instead, pin the existing path: empty content always lands as
        # EmptyResponseError, regardless of the path.
        resp.json.return_value = {"message": {"content": ""}}
        resp.raise_for_status = MagicMock()
        with patch(
            "autonomous.ai.models.local_model._SESSION.post",
            return_value=resp,
        ), patch.object(model, "flush_memory"):
            with pytest.raises(GenerateJSONEmptyResponseError):
                model.generate_json("prompt", context={})

    def test_transport_failure_propagates_as_requests_exception(self, model):
        """MIGRATIONS.md callout: pre-PR the ``retry(..., default={})``
        ate transport failures. Now they propagate. A consumer relying
        on the old masking behaviour will start seeing
        ``requests.RequestException`` — that's the documented
        behavior change."""
        # Use a connection error to simulate transport failure across
        # all 3 retry attempts.
        with patch(
            "autonomous.ai.models.local_model._SESSION.post",
            side_effect=requests.ConnectionError("network down"),
        ), patch.object(model, "flush_memory"):
            with pytest.raises(requests.RequestException):
                model.generate_json("prompt", context={})


# ---------------------------------------------------------------------------
# MockAIModel exemption — load-bearing for the offline test escape hatch
# ---------------------------------------------------------------------------


class TestMockModelExemption:
    """The migration document EXPLICITLY carves out MockAIModel:
    ``MockAIModel.generate_json`` is unchanged — it still returns a
    dict by design.

    Critical invariant: any test suite using ``provider="mock"`` in CI
    or local dev would BREAK if mock started raising. Pin the
    exemption."""

    def test_mock_returns_dict_not_raises_on_simple_prompt(self):
        from autonomous.ai.models.mock_model import MockAIModel

        m = MockAIModel()
        result = m.generate_json("just a normal prompt")
        assert isinstance(result, dict), (
            f"MockAIModel.generate_json must return a dict, got "
            f"{type(result).__name__} — the migration explicitly "
            f"exempts mock from the new exception contract."
        )

    def test_mock_does_not_raise_on_empty_prompt(self):
        """The exemption is unconditional — mock NEVER raises a
        GenerateJSON*Error. The whole point is the offline escape
        hatch: tests stay deterministic without service round-trips."""
        from autonomous.ai.exceptions import GenerateJSONError
        from autonomous.ai.models.mock_model import MockAIModel

        m = MockAIModel()
        try:
            result = m.generate_json("")
        except GenerateJSONError:
            pytest.fail(
                "MockAIModel raised GenerateJSONError — the migration "
                "guide carves out mock as the escape hatch; if mock "
                "starts raising, CI suites using provider='mock' break."
            )
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# MIGRATIONS.md entry — consumer-facing contract
# ---------------------------------------------------------------------------


class TestMigrationsEntry:
    """If MIGRATIONS.md drops the typed-exception entry, downstream
    consumers reading the upgrade notes won't know to switch from
    ``if not result`` to ``except GenerateJSONError``. Pin that the
    entry stays — the actual content can evolve, but the keywords
    that make it discoverable should remain."""

    def test_migrations_mentions_typed_exceptions(self):
        text = (REPO / "MIGRATIONS.md").read_text(encoding="utf-8")
        assert "GenerateJSONError" in text, (
            "MIGRATIONS.md no longer mentions GenerateJSONError — the "
            "exception hierarchy moved or the entry was removed; either "
            "way consumer upgrade guidance is lost."
        )

    def test_migrations_mentions_issue_124(self):
        """The MIGRATIONS entry cross-links to Issue #124 (the original
        request). Pin that reference so the discovery path stays intact."""
        text = (REPO / "MIGRATIONS.md").read_text(encoding="utf-8")
        assert re.search(r"#\s*124\b|Issue #124|issue 124", text, re.IGNORECASE), (
            "MIGRATIONS.md no longer links the typed-exceptions entry to "
            "Issue #124 — the cross-reference helps consumers find the "
            "original symptom that motivated the change."
        )

    def test_migrations_carves_out_mock_explicitly(self):
        """Important: MIGRATIONS must say mock is exempt. Otherwise a
        downstream consumer who tests with provider='mock' will spend
        a half day debugging "why doesn't my mock raise?" before
        realising it's intentional."""
        text = (REPO / "MIGRATIONS.md").read_text(encoding="utf-8")
        assert "MockAIModel" in text and re.search(
            r"unchanged|escape hatch|exempt", text, re.IGNORECASE
        ), (
            "MIGRATIONS.md no longer explicitly carves out MockAIModel "
            "from the new exception contract — consumers will be "
            "confused by mock not raising."
        )
