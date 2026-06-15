"""Independent coverage for PR #128 — #124 strict-mode parse-failure
loose fallback in `openai_compat.generate_json` + #125 in-process
embedding backend in `db_sync`.

PR #128 ships **no committed tests** — dev's tests live in
`tests/_dev_local/` (gitignored). This file IS the landing test
coverage for both #124 and #125. Two scopes, both critical:

**#124 — strict-mode parse-failure 200 → loose retry.**

Pre-PR symptom: `OpenAIClient.generate_json` raised
`GenerateJSONParseError` when strict-mode produced HTTP 200 with a
non-JSON body. The HTTPError fallback path already handled the
"endpoint refused strict mode" case; this PR added the symmetric
"endpoint accepted but didn't honor strict" case.

Critical surfaces to cover:
- Caching the endpoint in `_UNSUPPORTED_STRICT_MODE` happens BEFORE
  the loose retry (so even if loose-retry also fails, subsequent
  calls skip the strict probe).
- Observability event emitted with `detection="parse_failure_200"`
  (distinct from `detection="first"` for the HTTPError path).
- Counter `structured_outputs_unavailable_total` incremented.
- Loose retry parseable → caller gets dict.
- Loose retry needs `clean_json_response` salvage → caller gets dict.
- Loose retry HTTPError → `GenerateJSONEmptyResponseError`.
- Loose retry both raw + cleaned unparseable → fall through to
  `GenerateJSONParseError` with STRICT-MODE raw (not loose).
- `use_strict=False` skips the fallback entirely.

**#125 — in-process embedding backend.**

Pre-PR symptom: embeddings only ran via `_get_vector_local` (HTTP to
media_ai) or `_get_vector_openai` (HTTP to OpenAI-compat). When both
went down, RAG indexing degraded across the whole consumer fleet.
This PR adds an in-process backend that runs `sentence-transformers`
in the worker.

Critical surfaces to cover:
- `_get_vector_in_process` success path: returns `list[float]`.
- Lazy singleton: `_get_in_process_embedder` loads the
  `SentenceTransformer` ONCE per process, regardless of call count.
- `_default_in_process_model` reads `LOCAL_EMBEDDING_MODEL` env;
  default is `sentence-transformers/all-MiniLM-L6-v2` (384-dim,
  matching StoryTeller's `search_index` pinned dim).
- ImportError handling: missing `sentence_transformers` or `torch`
  routes to `[HPC-UNREACHABLE]` with signature
  `in_process:ImportError:<module>` (distinguishing partial-install
  cases — sentence-transformers present but torch missing — from the
  forgot-the-extra case).
- Generic exception: signature `in_process:exc:<ExcType>`.
- `_VECTOR_PROVIDERS["in_process"]` wired.
- `record_embedding_sync_event("hpc_failure")` called on both
  failure paths (symmetric with `_get_vector_local` / `_get_vector_openai`).
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
import requests


# ---------------------------------------------------------------------------
# #124 — strict-mode parse-failure 200 → loose retry
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_autotasks():
    """Neutralize AutoTasks/Redis at import time — db_sync and
    openai_compat both touch RQ-adjacent paths."""
    with patch("autonomous.ai.models.openai_compat.AutoTasks") as mock_tasks:
        mock_tasks.return_value.get_current_task.return_value = None
        yield mock_tasks


@pytest.fixture
def fresh_strict_cache():
    """Reset `_UNSUPPORTED_STRICT_MODE` between tests so cached
    endpoints don't bleed across cases. Tests that add to the cache
    are restoring shared module state on tear-down."""
    from autonomous.ai.models.openai_compat import _UNSUPPORTED_STRICT_MODE

    before = set(_UNSUPPORTED_STRICT_MODE)
    _UNSUPPORTED_STRICT_MODE.clear()
    yield _UNSUPPORTED_STRICT_MODE
    _UNSUPPORTED_STRICT_MODE.clear()
    _UNSUPPORTED_STRICT_MODE.update(before)


def _make_openai_client():
    """Bypass AutoModel persistence to get a callable instance whose
    methods we can patch.

    Same pattern other openai_compat unit tests use. The instance's
    `_chat` is replaced per-test to return canned bodies.
    """
    from autonomous.ai.models.openai_compat import OpenAIClient

    client = OpenAIClient.__new__(OpenAIClient)
    # Minimum descriptor state for AutoModel.
    object.__setattr__(client, "_data", {})
    object.__setattr__(client, "_dynamic_fields", {})
    object.__setattr__(client, "_changed_fields", [])
    object.__setattr__(client, "_initialised", False)
    object.__setattr__(client, "_created", True)
    # Attributes generate_json reaches into.
    object.__setattr__(client, "_json_model", "test-model")
    object.__setattr__(client, "_base_url", "https://test.example/v1")
    object.__setattr__(client, "instructions", "Be helpful")
    return client


class TestStrictModeLooseFallbackSuccess:
    """The happy path: strict raw is malformed, loose retry returns
    parseable JSON. Caller gets a dict and never sees the strict-mode
    failure — only the observability event records it.
    """

    def test_returns_loose_retry_parsed_dict(self, fresh_strict_cache):
        client = _make_openai_client()
        # First call (strict): returns malformed JSON. Second (loose):
        # returns valid JSON.
        client._chat = MagicMock(side_effect=[
            "not real json {{{",
            '{"value": "ok"}',
        ])

        result = client.generate_json(
            "prompt",
            json_schema={"type": "object"},
            schema_name="thing",
        )
        assert result == {"value": "ok"}
        # Two `_chat` calls total (strict + loose retry).
        assert client._chat.call_count == 2

    def test_loose_retry_uses_loose_response_format(self, fresh_strict_cache):
        client = _make_openai_client()
        client._chat = MagicMock(side_effect=[
            "garbage",
            '{"x": 1}',
        ])

        client.generate_json(
            "prompt", json_schema={"type": "object"}, schema_name="t"
        )
        # Second call should have used loose response_format.
        second_call = client._chat.call_args_list[1]
        assert second_call.kwargs["response_format"] == {"type": "json_object"}

    def test_loose_retry_clean_json_response_salvage(self, fresh_strict_cache):
        # Loose retry returns markdown-fenced JSON. clean_json_response
        # strips the fence; second json.loads succeeds.
        client = _make_openai_client()
        client._chat = MagicMock(side_effect=[
            "strict garbage",
            "```json\n{\"x\": 1}\n```",
        ])

        result = client.generate_json(
            "prompt", json_schema={"type": "object"}
        )
        assert result == {"x": 1}


class TestStrictModeEndpointCachingBeforeRetry:
    """Caching must happen BEFORE the loose retry. Otherwise a loose-
    retry failure would skip the cache-add and the next call would
    re-probe strict — defeating the negative-cache purpose.
    """

    def test_endpoint_cached_when_loose_retry_succeeds(self, fresh_strict_cache):
        client = _make_openai_client()
        client._chat = MagicMock(side_effect=[
            "garbage",
            '{"ok": true}',
        ])

        client.generate_json("p", json_schema={"type": "object"})

        assert ("test-model", "https://test.example/v1") in fresh_strict_cache

    def test_endpoint_cached_even_when_loose_retry_also_fails(
        self, fresh_strict_cache
    ):
        client = _make_openai_client()
        # Strict garbage, loose ALSO garbage.
        client._chat = MagicMock(side_effect=[
            "strict garbage",
            "loose garbage too",
        ])

        with pytest.raises(Exception):
            client.generate_json("p", json_schema={"type": "object"})

        # Cache survives the loose-retry failure — subsequent calls
        # to this endpoint will skip strict.
        assert ("test-model", "https://test.example/v1") in fresh_strict_cache

    def test_endpoint_cached_when_loose_retry_raises_httperror(
        self, fresh_strict_cache
    ):
        from autonomous.ai.models.openai_compat import OpenAIClient  # noqa: F401

        client = _make_openai_client()
        http_err = requests.HTTPError("loose mode also blew up")
        client._chat = MagicMock(side_effect=[
            "strict garbage",
            http_err,
        ])

        with pytest.raises(Exception):
            client.generate_json("p", json_schema={"type": "object"})

        # Caching happened pre-retry — survives the HTTPError on loose.
        assert ("test-model", "https://test.example/v1") in fresh_strict_cache


class TestStrictModeObservabilityEvent:
    """The observability event/counter must fire with the
    `detection="parse_failure_200"` signature — distinct from
    `detection="first"` (HTTPError path) so dashboards can graph
    the two trigger modes separately.
    """

    def test_event_emitted_with_parse_failure_200_detection(
        self, fresh_strict_cache
    ):
        client = _make_openai_client()
        client._chat = MagicMock(side_effect=[
            "garbage",
            '{"ok": true}',
        ])

        with patch("autonomous.ai.models.openai_compat.event") as mock_event:
            client.generate_json("p", json_schema={"type": "object"})

        # The event() helper was called at least once with
        # detection="parse_failure_200".
        matching = [
            call for call in mock_event.call_args_list
            if call.kwargs.get("detection") == "parse_failure_200"
        ]
        assert len(matching) == 1, (
            f"expected exactly one parse_failure_200 event; "
            f"got {len(matching)} from {mock_event.call_args_list}"
        )

    def test_event_includes_strict_mode_body_excerpt(
        self, fresh_strict_cache
    ):
        client = _make_openai_client()
        strict_garbage = "x" * 500  # well over the 200-char excerpt limit
        client._chat = MagicMock(side_effect=[
            strict_garbage,
            '{"ok": true}',
        ])

        with patch("autonomous.ai.models.openai_compat.event") as mock_event:
            client.generate_json("p", json_schema={"type": "object"})

        parse_failure_call = [
            c for c in mock_event.call_args_list
            if c.kwargs.get("detection") == "parse_failure_200"
        ][0]
        excerpt = parse_failure_call.kwargs["body_excerpt"]
        # Body excerpt is the strict raw, truncated to 200 chars.
        assert excerpt == strict_garbage[:200]
        assert len(excerpt) == 200

    def test_event_marks_cached_for_process(self, fresh_strict_cache):
        client = _make_openai_client()
        client._chat = MagicMock(side_effect=["garbage", '{"ok": true}'])

        with patch("autonomous.ai.models.openai_compat.event") as mock_event:
            client.generate_json("p", json_schema={"type": "object"})

        parse_failure_call = [
            c for c in mock_event.call_args_list
            if c.kwargs.get("detection") == "parse_failure_200"
        ][0]
        assert parse_failure_call.kwargs["cached_for_process"] is True

    def test_counter_incremented(self, fresh_strict_cache):
        from autonomous.ai.models import openai_compat as oc

        client = _make_openai_client()
        client._chat = MagicMock(side_effect=["garbage", '{"ok": true}'])

        with patch.object(
            oc._STRUCTURED_OUTPUTS_UNAVAILABLE_COUNTER, "inc"
        ) as mock_inc:
            client.generate_json("p", json_schema={"type": "object"})

        mock_inc.assert_called_once_with(provider="openai_compat")


class TestStrictModeLooseRetryHTTPError:
    """The loose retry raising HTTPError or MalformedResponseError
    must surface as GenerateJSONEmptyResponseError with the
    distinguishing 'parse-failure fallback' phrase.
    """

    def test_httperror_on_loose_retry_yields_empty_response_error(
        self, fresh_strict_cache
    ):
        from autonomous.ai.exceptions import GenerateJSONEmptyResponseError

        client = _make_openai_client()
        client._chat = MagicMock(side_effect=[
            "strict garbage",
            requests.HTTPError("connection refused"),
        ])

        with pytest.raises(GenerateJSONEmptyResponseError) as exc_info:
            client.generate_json("p", json_schema={"type": "object"})

        # The "parse-failure" envelope distinguishes from the
        # HTTPError path's "fallback retry" envelope.
        assert "parse-failure" in str(exc_info.value).lower()

    def test_malformed_response_on_loose_retry_yields_empty_response_error(
        self, fresh_strict_cache
    ):
        from autonomous.ai.exceptions import (
            GenerateJSONEmptyResponseError,
            MalformedResponseError,
        )

        client = _make_openai_client()
        client._chat = MagicMock(side_effect=[
            "strict garbage",
            MalformedResponseError("no candidates"),
        ])

        with pytest.raises(GenerateJSONEmptyResponseError):
            client.generate_json("p", json_schema={"type": "object"})


class TestStrictModeBothUnparseableRaisesParseError:
    """When loose retry also returns malformed JSON, fall through to
    the original GenerateJSONParseError with the STRICT raw — the
    diagnostic preserves what the caller asked for.
    """

    def test_raises_generate_json_parse_error(self, fresh_strict_cache):
        from autonomous.ai.exceptions import GenerateJSONParseError

        client = _make_openai_client()
        client._chat = MagicMock(side_effect=[
            "strict-mode garbage",
            "loose-mode garbage too",
        ])

        with pytest.raises(GenerateJSONParseError):
            client.generate_json("p", json_schema={"type": "object"})

    def test_raw_attached_is_strict_mode_raw(self, fresh_strict_cache):
        from autonomous.ai.exceptions import GenerateJSONParseError

        client = _make_openai_client()
        strict_body = "STRICT-RAW-MARKER"
        loose_body = "LOOSE-RAW-MARKER"
        client._chat = MagicMock(side_effect=[strict_body, loose_body])

        with pytest.raises(GenerateJSONParseError) as exc_info:
            client.generate_json("p", json_schema={"type": "object"})

        # Critical: the user asked for strict; the diagnostic must
        # reflect THAT body so they can debug the schema mismatch.
        # Returning the loose body would mislead.
        assert exc_info.value.raw == strict_body
        assert loose_body not in str(exc_info.value.raw)

    def test_empty_loose_raw_falls_through_to_parse_error(
        self, fresh_strict_cache
    ):
        from autonomous.ai.exceptions import GenerateJSONParseError

        client = _make_openai_client()
        client._chat = MagicMock(side_effect=[
            "strict garbage",
            "",  # loose returned empty
        ])

        with pytest.raises(GenerateJSONParseError) as exc_info:
            client.generate_json("p", json_schema={"type": "object"})
        # Strict raw preserved on the exception even after loose
        # returned nothing.
        assert exc_info.value.raw == "strict garbage"

    def test_whitespace_only_loose_raw_falls_through(self, fresh_strict_cache):
        from autonomous.ai.exceptions import GenerateJSONParseError

        client = _make_openai_client()
        client._chat = MagicMock(side_effect=[
            "strict garbage",
            "   \n\t  ",
        ])

        with pytest.raises(GenerateJSONParseError):
            client.generate_json("p", json_schema={"type": "object"})


class TestNonStrictModeSkipsFallback:
    """Without strict mode (`json_schema=None` OR endpoint already
    cached as unsupported), the loose-retry fallback MUST NOT fire.
    """

    def test_no_schema_does_not_trigger_loose_retry(self, fresh_strict_cache):
        from autonomous.ai.exceptions import GenerateJSONParseError

        client = _make_openai_client()
        # Only one return — no second call expected since use_strict=False
        # already uses loose mode upfront.
        client._chat = MagicMock(return_value="garbage")

        with pytest.raises(GenerateJSONParseError):
            client.generate_json("prompt")  # json_schema=None

        # No second loose retry — exactly one `_chat` call.
        assert client._chat.call_count == 1

    def test_already_cached_endpoint_does_not_trigger_double_retry(
        self, fresh_strict_cache
    ):
        from autonomous.ai.exceptions import GenerateJSONParseError

        # Pre-populate the cache so use_strict=False from the start.
        fresh_strict_cache.add(("test-model", "https://test.example/v1"))
        client = _make_openai_client()
        client._chat = MagicMock(return_value="garbage")

        with pytest.raises(GenerateJSONParseError):
            client.generate_json("p", json_schema={"type": "object"})

        # Cached endpoint → loose used from the first call; no second retry.
        assert client._chat.call_count == 1


# ---------------------------------------------------------------------------
# #125 — in-process embedding backend
# ---------------------------------------------------------------------------


class TestInProcessProviderRegistered:
    """The new provider must be wired into `_VECTOR_PROVIDERS` so
    `EMBEDDING_AI_AGENT=in_process` routes through the dispatcher.
    """

    def test_provider_present_in_registry(self):
        from autonomous.db.db_sync import (
            _VECTOR_PROVIDERS,
            _get_vector_in_process,
        )

        assert _VECTOR_PROVIDERS["in_process"] is _get_vector_in_process

    def test_distinct_from_local_provider(self):
        # The naming note in MIGRATIONS.md is load-bearing: `local`
        # already routes to the legacy media_ai HTTP path. The new
        # backend MUST NOT have replaced it.
        from autonomous.db.db_sync import (
            _VECTOR_PROVIDERS,
            _get_vector_in_process,
            _get_vector_local,
        )

        assert _VECTOR_PROVIDERS["local"] is _get_vector_local
        assert _VECTOR_PROVIDERS["local"] is not _get_vector_in_process


class TestDefaultInProcessModel:
    """`_default_in_process_model` reads `LOCAL_EMBEDDING_MODEL` env
    or falls back to `sentence-transformers/all-MiniLM-L6-v2` (the
    384-dim default matching StoryTeller's `search_index`).
    """

    def test_default_when_env_not_set(self, monkeypatch):
        from autonomous.db.db_sync import _default_in_process_model

        monkeypatch.delenv("LOCAL_EMBEDDING_MODEL", raising=False)
        assert (
            _default_in_process_model()
            == "sentence-transformers/all-MiniLM-L6-v2"
        )

    def test_env_override_honored(self, monkeypatch):
        from autonomous.db.db_sync import _default_in_process_model

        monkeypatch.setenv(
            "LOCAL_EMBEDDING_MODEL",
            "sentence-transformers/all-mpnet-base-v2",
        )
        assert (
            _default_in_process_model()
            == "sentence-transformers/all-mpnet-base-v2"
        )


@pytest.fixture
def reset_embedder_singleton():
    """Reset `_IN_PROCESS_EMBEDDER` between tests so the lazy-load
    counter is observable per-test."""
    from autonomous.db import db_sync

    before = db_sync._IN_PROCESS_EMBEDDER
    db_sync._IN_PROCESS_EMBEDDER = None
    yield
    db_sync._IN_PROCESS_EMBEDDER = before


class TestLazyEmbedderSingleton:
    """`_get_in_process_embedder` must be a lazy per-process singleton —
    the SentenceTransformer load is what makes the path competitive
    with HTTP. Loading twice would defeat the speed argument.
    """

    def test_embedder_loaded_only_once_across_calls(
        self, reset_embedder_singleton
    ):
        from autonomous.db import db_sync

        fake_module = MagicMock()
        fake_model = MagicMock()
        fake_module.SentenceTransformer = MagicMock(return_value=fake_model)
        with patch.dict(sys.modules, {"sentence_transformers": fake_module}):
            a = db_sync._get_in_process_embedder()
            b = db_sync._get_in_process_embedder()

        assert a is b
        # Two `_get_in_process_embedder()` calls but only ONE
        # SentenceTransformer construction.
        fake_module.SentenceTransformer.assert_called_once()

    def test_embedder_uses_default_model_id(self, reset_embedder_singleton):
        from autonomous.db import db_sync

        fake_module = MagicMock()
        with patch.dict(sys.modules, {"sentence_transformers": fake_module}):
            db_sync._get_in_process_embedder()

        # SentenceTransformer was called with the default model id.
        fake_module.SentenceTransformer.assert_called_once_with(
            "sentence-transformers/all-MiniLM-L6-v2"
        )


class TestGetVectorInProcessSuccess:
    """Success path: embedder.encode → numpy array → `.tolist()` →
    `list[float]` returned.
    """

    def test_returns_embedding_list(self, reset_embedder_singleton):
        from autonomous.db import db_sync

        fake_array = MagicMock()
        fake_array.tolist.return_value = [0.1, 0.2, 0.3]
        fake_embedder = MagicMock()
        fake_embedder.encode.return_value = fake_array
        fake_module = MagicMock()
        fake_module.SentenceTransformer = MagicMock(return_value=fake_embedder)

        with patch.dict(sys.modules, {"sentence_transformers": fake_module}):
            result = db_sync._get_vector_in_process("hello")

        assert result == [0.1, 0.2, 0.3]
        fake_embedder.encode.assert_called_once_with("hello")

    def test_encode_called_with_input_text(self, reset_embedder_singleton):
        from autonomous.db import db_sync

        fake_array = MagicMock()
        fake_array.tolist.return_value = [0.0] * 384
        fake_embedder = MagicMock()
        fake_embedder.encode.return_value = fake_array
        fake_module = MagicMock()
        fake_module.SentenceTransformer = MagicMock(return_value=fake_embedder)

        with patch.dict(sys.modules, {"sentence_transformers": fake_module}):
            db_sync._get_vector_in_process("the quick brown fox")

        fake_embedder.encode.assert_called_once_with("the quick brown fox")


class TestGetVectorInProcessImportError:
    """ImportError handling: missing the `[embeddings]` extra (or its
    transitive `torch`) must degrade gracefully to `None` + the
    `[HPC-UNREACHABLE]` marker.

    The signature distinguishes which module went missing —
    `in_process:ImportError:torch` vs
    `in_process:ImportError:sentence_transformers` — so operators
    can tell forgot-the-extra apart from a partial install.
    """

    def _force_import_error(self, missing_module: str):
        """Return a context that makes `import sentence_transformers`
        raise ImportError naming `missing_module`."""
        # Build an ImportError whose `.name` attribute matches the
        # ModuleNotFoundError shape the production code reads.
        err = ImportError(f"No module named {missing_module!r}")
        err.name = missing_module
        fake_module = MagicMock()
        fake_module.SentenceTransformer = MagicMock(side_effect=err)
        return patch.dict(sys.modules, {"sentence_transformers": fake_module})

    def test_missing_sentence_transformers_returns_none(
        self, reset_embedder_singleton
    ):
        from autonomous.db import db_sync

        # No sentence_transformers in sys.modules — the import line
        # inside `_get_in_process_embedder` raises ModuleNotFoundError.
        # `monkeypatch` removes the module if present.
        if "sentence_transformers" in sys.modules:
            del sys.modules["sentence_transformers"]
        # Block the import.
        with patch.object(
            db_sync, "_get_in_process_embedder",
            side_effect=ImportError(
                "No module named 'sentence_transformers'"
            ),
        ) as patched:
            patched.side_effect.name = "sentence_transformers"
            result = db_sync._get_vector_in_process("hello")
        assert result is None

    def test_missing_torch_named_in_signature(
        self, reset_embedder_singleton, capsys
    ):
        # Operator-visible signature should NAME torch when torch is
        # the missing transitive — distinct from missing
        # sentence_transformers itself.
        from autonomous.db import db_sync

        err = ImportError("No module named 'torch'")
        err.name = "torch"
        with patch.object(
            db_sync, "_get_in_process_embedder", side_effect=err
        ), patch.object(
            db_sync, "_emit_hpc_unreachable"
        ) as mock_emit:
            db_sync._get_vector_in_process("hello")

        # Signature must include "in_process:ImportError:torch".
        signature = mock_emit.call_args.args[0]
        assert signature == "in_process:ImportError:torch"

    def test_missing_sentence_transformers_named_in_signature(
        self, reset_embedder_singleton
    ):
        from autonomous.db import db_sync

        err = ImportError("No module named 'sentence_transformers'")
        err.name = "sentence_transformers"
        with patch.object(
            db_sync, "_get_in_process_embedder", side_effect=err
        ), patch.object(
            db_sync, "_emit_hpc_unreachable"
        ) as mock_emit:
            db_sync._get_vector_in_process("hello")

        signature = mock_emit.call_args.args[0]
        assert signature == "in_process:ImportError:sentence_transformers"

    def test_remediation_hint_in_emitted_message(self, reset_embedder_singleton):
        # The marker MESSAGE (second arg) should name the
        # `pip install autonomous-app[embeddings]` remediation.
        # That's the discoverability hook for operators reading logs.
        from autonomous.db import db_sync

        err = ImportError("No module named 'torch'")
        err.name = "torch"
        with patch.object(
            db_sync, "_get_in_process_embedder", side_effect=err
        ), patch.object(
            db_sync, "_emit_hpc_unreachable"
        ) as mock_emit:
            db_sync._get_vector_in_process("hello")

        message = mock_emit.call_args.args[1]
        assert "[HPC-UNREACHABLE]" in message
        assert "embeddings" in message
        assert "pip install" in message

    def test_records_embedding_sync_event_on_importerror(
        self, reset_embedder_singleton
    ):
        from autonomous.db import db_sync

        err = ImportError("No module named 'torch'")
        err.name = "torch"
        with patch.object(
            db_sync, "_get_in_process_embedder", side_effect=err
        ), patch.object(
            db_sync, "record_embedding_sync_event"
        ) as mock_record:
            db_sync._get_vector_in_process("hello")

        mock_record.assert_called_once_with("hpc_failure")


class TestGetVectorInProcessGenericException:
    """Any other exception (model load error, encode crash, OOM)
    routes to the generic `in_process:exc:<ExcType>` signature so
    log parsers can group failures by exception class.
    """

    def test_runtime_error_returns_none(self, reset_embedder_singleton):
        from autonomous.db import db_sync

        with patch.object(
            db_sync, "_get_in_process_embedder",
            side_effect=RuntimeError("CUDA out of memory"),
        ):
            result = db_sync._get_vector_in_process("hello")

        assert result is None

    def test_signature_names_exception_type(self, reset_embedder_singleton):
        from autonomous.db import db_sync

        with patch.object(
            db_sync, "_get_in_process_embedder",
            side_effect=ValueError("bad model"),
        ), patch.object(
            db_sync, "_emit_hpc_unreachable"
        ) as mock_emit:
            db_sync._get_vector_in_process("hello")

        signature = mock_emit.call_args.args[0]
        assert signature == "in_process:exc:ValueError"

    def test_records_embedding_sync_event_on_generic_exception(
        self, reset_embedder_singleton
    ):
        from autonomous.db import db_sync

        with patch.object(
            db_sync, "_get_in_process_embedder",
            side_effect=RuntimeError("model load"),
        ), patch.object(
            db_sync, "record_embedding_sync_event"
        ) as mock_record:
            db_sync._get_vector_in_process("hello")

        mock_record.assert_called_once_with("hpc_failure")

    def test_encode_exception_routes_to_exc_signature(
        self, reset_embedder_singleton
    ):
        # The exception can come from `embedder.encode(text)`, not
        # just from the load. Both go through the same fallback.
        from autonomous.db import db_sync

        fake_embedder = MagicMock()
        fake_embedder.encode.side_effect = RuntimeError("nan in input")
        fake_module = MagicMock()
        fake_module.SentenceTransformer = MagicMock(return_value=fake_embedder)

        with patch.dict(sys.modules, {"sentence_transformers": fake_module}), \
                patch.object(db_sync, "_emit_hpc_unreachable") as mock_emit:
            result = db_sync._get_vector_in_process("hello")

        assert result is None
        signature = mock_emit.call_args.args[0]
        assert signature == "in_process:exc:RuntimeError"


class TestSymmetryWithExistingProviders:
    """The new `in_process` provider must follow the same observability
    contract as `_get_vector_local` and `_get_vector_openai` so log
    scrapers / dashboards keyed on the existing marker work uniformly.
    """

    def test_emits_hpc_unreachable_marker_family(self, reset_embedder_singleton):
        # Same `[HPC-UNREACHABLE]` prefix as the other providers.
        from autonomous.db import db_sync

        with patch.object(
            db_sync, "_get_in_process_embedder",
            side_effect=RuntimeError("any"),
        ), patch.object(
            db_sync, "_emit_hpc_unreachable"
        ) as mock_emit:
            db_sync._get_vector_in_process("hello")

        # Helper was called — that's the contract; the helper itself
        # is responsible for the marker prefix downstream.
        assert mock_emit.called
        # Message arg starts with the marker family.
        assert mock_emit.call_args.args[1].startswith("[HPC-UNREACHABLE]")
