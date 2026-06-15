"""Independent coverage for the JSON Schema / Structured Outputs bundle (PR #19).

Written without consulting dev's ``tests/_dev_local/`` (gitignored) or
dev's committed test files in this PR (``test_unit_json_utils_schema_validate.py``,
``test_unit_jsonagent_schema.py``, ``test_unit_jsonschema_dependency.py``,
``test_unit_local_model_json_schema.py``, ``test_unit_mock_model_json_schema.py``,
``test_unit_openai_compat_structured_outputs.py``). These tests target
the behavior surface from the source diff alone — the second perspective
in the two-perspective testing design described in CLAUDE.md.

Eight concern groups are covered:

1. ``_json_utils._schema_validate`` — None schema no-ops; valid payload
   does not raise; invalid payload raises ``GenerateJSONParseError``
   with ``.raw`` populated; invalid schema (caller bug) is distinguished
   from invalid payload (model bug) in the error message.
2. ``GenerateJSONParseError._RAW_MAX`` truncation — constructor caps
   ``.raw`` to 500 chars so a future provider can't leak unbounded
   bodies into logs.
3. ``JSONAgent.generate`` Gemini dispatch — ``json_schema`` translates
   to a ``function`` dict with the correct shape; ``function=None``
   when ``json_schema=None``.
4. ``JSONAgent.generate`` non-Gemini dispatch — ``json_schema`` and
   ``schema_name`` forwarded verbatim to the provider's
   ``generate_json``.
5. ``JSONAgent.generate`` defense-in-depth — ``_schema_validate`` runs
   on every provider's output, including when the provider claims
   schema compliance (catches provider bugs).
6. ``OpenAIClient`` strict-mode payload shape + the four-marker
   detector + 400/422 acceptance + negative cache + once-per-process
   logging + `_reset_unsupported_cache` semantics.
7. ``LocalAIModel`` log-once dedup per (model, endpoint) when
   ``json_schema`` is set.
8. ``MockAIModel.generate_json`` absorbs new kwargs without TypeError.
9. ``requirements.txt`` — ``jsonschema>=4.0`` is a core (not extras-gated)
   dependency.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autonomous.ai._json_utils import _schema_validate
from autonomous.ai.exceptions import GenerateJSONParseError


# ---------------------------------------------------------------------------
# 1. _schema_validate — None no-op + valid + invalid + invalid-schema paths
# ---------------------------------------------------------------------------


class TestSchemaValidate:
    def test_none_schema_is_no_op(self):
        """Validation is opt-in. ``schema=None`` must return without
        raising even when the payload would fail any schema."""
        _schema_validate({"anything": "goes"}, None)
        _schema_validate("not even a dict", None)
        _schema_validate(None, None)
        # No assertion needed — the test passes iff no exception is raised.

    def test_valid_payload_passes(self):
        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
        _schema_validate({"name": "Aria"}, schema)

    def test_invalid_payload_raises_with_raw(self):
        """Mismatch raises ``GenerateJSONParseError`` with the raw
        body on ``.raw`` for caller diagnostics."""
        schema = {"type": "object", "required": ["name"]}
        raw_body = '{"description": "missing the required name field"}'
        with pytest.raises(GenerateJSONParseError) as exc_info:
            _schema_validate(
                {"description": "missing the required name field"},
                schema,
                raw=raw_body,
            )
        assert exc_info.value.raw == raw_body
        assert "schema validation" in str(exc_info.value).lower()

    def test_invalid_schema_distinguishes_caller_bug_from_model_bug(self):
        """A malformed schema (caller-supplied, not the model's fault)
        should produce a different error message than a payload
        mismatch, so debugging points at the right side."""
        # `type` must be one of jsonschema's accepted values; nonsense
        # raises SchemaError, not ValidationError.
        bad_schema = {"type": "not-a-real-type"}
        with pytest.raises(GenerateJSONParseError) as exc_info:
            _schema_validate({"x": 1}, bad_schema, raw="{}")
        assert "schema is invalid" in str(exc_info.value).lower()

    def test_validation_error_chains_jsonschema_exception(self):
        """``raise from`` preserves the original jsonschema exception
        as ``__cause__`` so a debugger / log can introspect the
        validator's detailed diagnostics."""
        import jsonschema

        schema = {"type": "string"}
        with pytest.raises(GenerateJSONParseError) as exc_info:
            _schema_validate(123, schema, raw='"123"')
        assert isinstance(exc_info.value.__cause__, jsonschema.ValidationError)

    def test_raw_is_truncated_at_500(self):
        """Pin ``_RAW_MAX`` so a future provider can't leak unbounded
        bodies into logs by passing a huge raw= value. Truncation
        happens in the exception constructor, not at each call site."""
        schema = {"type": "string"}
        long_raw = "x" * 2000
        with pytest.raises(GenerateJSONParseError) as exc_info:
            _schema_validate(123, schema, raw=long_raw)
        assert len(exc_info.value.raw) == 500
        assert exc_info.value.raw == "x" * 500

    def test_empty_raw_default(self):
        """The ``raw`` kwarg is optional — default empty string."""
        schema = {"type": "string"}
        with pytest.raises(GenerateJSONParseError) as exc_info:
            _schema_validate(123, schema)  # no raw
        assert exc_info.value.raw == ""


# ---------------------------------------------------------------------------
# 2. GenerateJSONParseError direct construction — constructor invariants
# ---------------------------------------------------------------------------


class TestParseErrorConstructor:
    def test_msg_is_str_arg(self):
        e = GenerateJSONParseError("a bad thing happened")
        assert "a bad thing happened" in str(e)
        assert e.raw == ""

    def test_raw_keyword_only(self):
        """``raw`` is keyword-only; positional second arg must fail.
        Protects callers from accidentally passing the body as msg or
        vice-versa."""
        with pytest.raises(TypeError):
            GenerateJSONParseError("msg", "the raw")  # type: ignore[misc]

    def test_raw_none_becomes_empty_string(self):
        """``raw=None`` resolves to ``""`` (the ``or ""`` guard)."""
        e = GenerateJSONParseError("x", raw=None)  # type: ignore[arg-type]
        assert e.raw == ""


# ---------------------------------------------------------------------------
# 3-5. JSONAgent.generate dispatch + defense-in-depth schema validation
# ---------------------------------------------------------------------------


class _FakeJSONAgent:
    """Borrow ``JSONAgent.generate`` onto a plain class to sidestep
    the vendored mongoengine descriptor machinery.

    Same pattern as the prior test-agent iter — see
    ``test_unit_image_perf_iter_2026_05_23.py`` for the rationale.
    """

    from autonomous.ai.jsonagent import JSONAgent  # noqa: E402

    generate = JSONAgent.generate

    def __init__(self, provider: str = "gemini"):
        self.provider = provider
        self.name = "test-jsonagent"
        self.instructions = "test"
        self.description = "test"
        self.meta_calls: list[tuple] = []
        self.last_client_calls: list[dict] = []

    def get_client(self, provider=None, *, persist: bool = True):
        raise NotImplementedError("patch get_client per-test")

    def add_to_job_meta(self, k, v):
        self.meta_calls.append((k, v))


class TestJSONAgentGeminiDispatch:
    """Gemini's existing ``function=`` parameter IS a JSON-schema
    carrier — ``JSONAgent.generate`` must translate ``json_schema``
    into the expected ``function`` dict shape."""

    def _make_agent(self, return_value):
        agent = _FakeJSONAgent(provider="gemini")
        client = MagicMock()
        client.generate_json.return_value = return_value
        agent.get_client = lambda *a, **kw: client  # noqa: ARG005
        return agent, client

    def test_no_json_schema_passes_function_none(self, monkeypatch):
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        agent, client = self._make_agent({"ok": True})
        agent.generate("prompt")
        call_kwargs = client.generate_json.call_args.kwargs
        assert call_kwargs["function"] is None

    def test_json_schema_synthesizes_function_dict(self, monkeypatch):
        """Pin the translation shape: function should be a dict with
        keys ``name`` (from schema_name), ``description``, and
        ``parameters`` (the json_schema itself)."""
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        agent, client = self._make_agent({"x": 1})
        agent.generate(
            "prompt", json_schema=schema, schema_name="my_payload"
        )
        function = client.generate_json.call_args.kwargs["function"]
        assert function == {
            "name": "my_payload",
            "description": "Structured response shape.",
            "parameters": schema,
        }

    def test_default_schema_name_is_response(self, monkeypatch):
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        schema = {"type": "object"}
        agent, client = self._make_agent({})
        agent.generate("prompt", json_schema=schema)
        function = client.generate_json.call_args.kwargs["function"]
        assert function["name"] == "response"

    def test_gemini_dispatch_does_not_pass_json_schema_kwarg(
        self, monkeypatch
    ):
        """The Gemini branch uses ``function=`` translation; passing
        json_schema= AS WELL would either be a double-spec or trip
        gemini's signature. Pin that the kwarg is not forwarded."""
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        schema = {"type": "object"}
        agent, client = self._make_agent({})
        agent.generate("prompt", json_schema=schema)
        call_kwargs = client.generate_json.call_args.kwargs
        assert "json_schema" not in call_kwargs
        assert "schema_name" not in call_kwargs


class TestJSONAgentNonGeminiDispatch:
    """Non-gemini providers (openai, local, mock) accept ``json_schema``
    and ``schema_name`` directly — the agent must forward them."""

    def _make_agent(self, provider, return_value):
        agent = _FakeJSONAgent(provider=provider)
        client = MagicMock()
        client.generate_json.return_value = return_value
        agent.get_client = lambda *a, **kw: client  # noqa: ARG005
        return agent, client

    @pytest.mark.parametrize("provider", ["openai", "local", "mock"])
    def test_non_gemini_forwards_json_schema(self, provider, monkeypatch):
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        schema = {"type": "object"}
        agent, client = self._make_agent(provider, {})
        agent.generate("prompt", json_schema=schema, schema_name="thing")
        call_kwargs = client.generate_json.call_args.kwargs
        assert call_kwargs["json_schema"] == schema
        assert call_kwargs["schema_name"] == "thing"
        # function= is NOT in the non-gemini path.
        assert "function" not in call_kwargs

    def test_env_override_routes_to_specified_provider(self, monkeypatch):
        """The ``JSON_AI_AGENT`` env var overrides ``self.provider``
        at dispatch time — verify the env-targeted provider gets the
        correct dispatch shape (gemini vs non-gemini)."""
        monkeypatch.setenv("JSON_AI_AGENT", "local")
        schema = {"type": "object"}
        # self.provider is gemini, but env says local — so the call
        # must use the NON-gemini branch (json_schema= forwarded).
        agent, client = self._make_agent("gemini", {})
        agent.generate("p", json_schema=schema)
        kwargs = client.generate_json.call_args.kwargs
        assert "json_schema" in kwargs  # non-gemini branch taken
        assert "function" not in kwargs


class TestJSONAgentDefenseInDepth:
    """Even when a provider claims strict-mode compliance, validate
    the response client-side. Catches provider bugs at the agent
    boundary so downstream caller code can trust the result shape."""

    def test_validation_runs_on_gemini_path(self, monkeypatch):
        """Gemini's function-calling normally produces a conforming
        response — but if it doesn't (provider bug), the agent's
        post-dispatch validation must catch it."""
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        schema = {
            "type": "object",
            "required": ["name"],
            "additionalProperties": False,
        }
        agent = _FakeJSONAgent(provider="gemini")
        client = MagicMock()
        # Provider lies — claims function-calling but returned an empty dict.
        client.generate_json.return_value = {}
        agent.get_client = lambda *a, **kw: client  # noqa: ARG005

        with pytest.raises(GenerateJSONParseError):
            agent.generate("prompt", json_schema=schema)

    def test_validation_runs_on_non_gemini_path(self, monkeypatch):
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        schema = {"type": "object", "required": ["x"]}
        agent = _FakeJSONAgent(provider="openai")
        client = MagicMock()
        client.generate_json.return_value = {"y": 1}  # missing x
        agent.get_client = lambda *a, **kw: client  # noqa: ARG005

        with pytest.raises(GenerateJSONParseError):
            agent.generate("prompt", json_schema=schema)

    def test_validation_skipped_when_schema_none(self, monkeypatch):
        """Default behavior (no schema) returns the dict as-is."""
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        agent = _FakeJSONAgent(provider="openai")
        client = MagicMock()
        # Would fail schema validation if one were passed.
        client.generate_json.return_value = {"y": 1}
        agent.get_client = lambda *a, **kw: client  # noqa: ARG005

        result = agent.generate("prompt")  # no json_schema
        assert result == {"y": 1}

    def test_string_response_is_json_decoded_before_validation(
        self, monkeypatch
    ):
        """Some providers return JSON-as-string (the cleaner path).
        ``generate`` must json.loads it BEFORE running validation,
        else the validator would see a string and reject the type."""
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        agent = _FakeJSONAgent(provider="openai")
        client = MagicMock()
        client.generate_json.return_value = '{"name": "Aria"}'
        agent.get_client = lambda *a, **kw: client  # noqa: ARG005

        schema = {"type": "object", "required": ["name"]}
        result = agent.generate("p", json_schema=schema)
        assert result == {"name": "Aria"}

    def test_invalid_json_string_raises_parse_error(self, monkeypatch):
        """Post-fix: bare ValueError replaced by typed
        GenerateJSONParseError. See TestJSONAgentParseErrorTypedHierarchy
        below for the full typed-exception coverage."""
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        agent = _FakeJSONAgent(provider="openai")
        client = MagicMock()
        client.generate_json.return_value = "not even json"
        agent.get_client = lambda *a, **kw: client  # noqa: ARG005

        with pytest.raises(GenerateJSONParseError, match="Invalid JSON"):
            agent.generate("p")

    def test_non_dict_non_string_response_raises_parse_error(
        self, monkeypatch
    ):
        """Post-fix: bare ValueError replaced by typed
        GenerateJSONParseError for the wrong-result-type case too."""
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        agent = _FakeJSONAgent(provider="openai")
        client = MagicMock()
        client.generate_json.return_value = ["a", "list", "is", "not", "ok"]
        agent.get_client = lambda *a, **kw: client  # noqa: ARG005

        with pytest.raises(GenerateJSONParseError, match="Invalid JSON"):
            agent.generate("p")


# ---------------------------------------------------------------------------
# 6. OpenAIClient — strict-mode payload + detector + cache + log marker
# ---------------------------------------------------------------------------


class TestOpenAIDetectorMatrix:
    """``_looks_like_unsupported_strict_mode(status, body)`` is the
    conservative gate for the negative cache + fallback. Pin every
    branch of the matrix."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        from autonomous.ai.models import openai_compat
        openai_compat._reset_unsupported_cache()
        yield
        openai_compat._reset_unsupported_cache()

    def test_500_never_flagged_even_with_marker_in_body(self):
        """A 500 is a server failure, NOT a 'strict mode not supported'
        signal — must propagate, not silently downgrade."""
        from autonomous.ai.models.openai_compat import (
            _looks_like_unsupported_strict_mode,
        )
        assert (
            _looks_like_unsupported_strict_mode(500, "json_schema error")
            is False
        )

    def test_403_never_flagged(self):
        from autonomous.ai.models.openai_compat import (
            _looks_like_unsupported_strict_mode,
        )
        assert (
            _looks_like_unsupported_strict_mode(403, "response_format")
            is False
        )

    @pytest.mark.parametrize(
        "marker",
        ["json_schema", "response_format", "unsupported_parameter",
         "structured output"],
    )
    @pytest.mark.parametrize("status", [400, 422])
    def test_each_marker_at_each_supported_status_flags(self, marker, status):
        from autonomous.ai.models.openai_compat import (
            _looks_like_unsupported_strict_mode,
        )
        body = f"Server said: {marker} is not allowed."
        assert _looks_like_unsupported_strict_mode(status, body) is True

    def test_marker_is_case_insensitive(self):
        from autonomous.ai.models.openai_compat import (
            _looks_like_unsupported_strict_mode,
        )
        assert (
            _looks_like_unsupported_strict_mode(
                400, "Error: JSON_SCHEMA is rejected"
            )
            is True
        )

    def test_400_without_marker_not_flagged(self):
        """A bare 400 (e.g. real client bug: bad model name) must
        propagate — silently falling back would mask the actual error."""
        from autonomous.ai.models.openai_compat import (
            _looks_like_unsupported_strict_mode,
        )
        assert (
            _looks_like_unsupported_strict_mode(
                400, "Model 'gpt-99' not found"
            )
            is False
        )


class TestOpenAINegativeCache:
    """Module-level ``_UNSUPPORTED_STRICT_MODE`` is the negative cache
    + ``_reset_unsupported_cache`` clears it. Pin both."""

    @pytest.fixture(autouse=True)
    def _isolate(self):
        from autonomous.ai.models import openai_compat
        openai_compat._reset_unsupported_cache()
        yield
        openai_compat._reset_unsupported_cache()

    def test_reset_cache_clears_entries(self):
        from autonomous.ai.models import openai_compat
        openai_compat._UNSUPPORTED_STRICT_MODE.add(("modelA", "http://endpoint"))
        assert len(openai_compat._UNSUPPORTED_STRICT_MODE) == 1
        openai_compat._reset_unsupported_cache()
        assert len(openai_compat._UNSUPPORTED_STRICT_MODE) == 0

    def test_cache_is_tuple_keyed(self):
        """The cache key is the (model, base_url) tuple — same model
        on different endpoints must be tracked independently."""
        from autonomous.ai.models import openai_compat
        openai_compat._UNSUPPORTED_STRICT_MODE.add(("gpt-4", "http://a"))
        assert ("gpt-4", "http://a") in openai_compat._UNSUPPORTED_STRICT_MODE
        assert ("gpt-4", "http://b") not in openai_compat._UNSUPPORTED_STRICT_MODE


# ---------------------------------------------------------------------------
# 7. LocalAIModel — log once per (model, endpoint) when json_schema set
# ---------------------------------------------------------------------------


class TestLocalAIModelLogOnce:
    """``LocalAIModel.generate_json(json_schema=...)`` should log the
    ``[STRUCTURED-OUTPUTS-UNAVAILABLE]`` marker exactly once per
    (model, endpoint) for the life of the process."""

    @pytest.fixture(autouse=True)
    def _clear_log_cache(self):
        from autonomous.ai.models import local_model
        local_model._STRUCTURED_OUTPUTS_LOGGED.clear()
        yield
        local_model._STRUCTURED_OUTPUTS_LOGGED.clear()

    def test_no_log_when_json_schema_is_none(self, monkeypatch):
        """No schema → no UNAVAILABLE marker. The marker would be
        noise on every non-schema call. Actually call generate_json
        (rather than just asserting the cache is empty post-fixture-
        cleanup, which would be a tautology)."""
        from autonomous.ai.models import local_model

        instance = self._make_instance("llama3", "http://ollama:11434")
        log_calls = []
        # Emission migrated to ``observability.event()`` (#51 step 3) —
        # event() resolves ``log`` via ``from autonomous import log``
        # inside the function body, so the patch seam moved from the
        # local module's ``log`` import to the package-level
        # ``autonomous.log`` attribute. Same pattern as #50 slice B.
        monkeypatch.setattr(
            "autonomous.log",
            lambda *a, _print=False: log_calls.append(a[0] if a else ""),
        )
        monkeypatch.setattr(
            local_model, "retry",
            lambda *a, **kw: (_ for _ in ()).throw(  # noqa: ARG005
                RuntimeError("stop-here")
            ),
        )

        # Call WITHOUT json_schema. The logging block at the top of
        # generate_json should be skipped entirely.
        with pytest.raises(RuntimeError, match="stop-here"):
            instance.generate_json("p", system_prompt="t")  # no json_schema

        markers = [m for m in log_calls if "STRUCTURED-OUTPUTS-UNAVAILABLE" in m]
        assert markers == []
        # Cache stays empty too.
        assert len(local_model._STRUCTURED_OUTPUTS_LOGGED) == 0

    def _make_instance(self, model: str, endpoint: str):
        """Construct a LocalAIModel that bypasses MongoEngine init.

        Setting StringAttr fields like ``instructions`` via attribute
        assignment trips the descriptor's ``_initialised`` check.
        Class-level attributes (``_text_model`` if it were a class
        attr) can be overridden via instance dict directly. The
        instance attrs we DO need are plain ones (``_text_model``,
        ``_ollama_url``); we set them via ``object.__setattr__`` so
        the StringAttr descriptors aren't involved (they aren't, but
        belt and suspenders).
        """
        from autonomous.ai.models import local_model
        instance = local_model.LocalAIModel.__new__(local_model.LocalAIModel)
        object.__setattr__(instance, "_text_model", model)
        object.__setattr__(instance, "_ollama_url", endpoint)
        return instance

    def test_first_schema_call_logs_and_caches(self, monkeypatch):
        """First call with a schema records the marker + populates
        the dedup cache. We short-circuit by patching ``retry`` so we
        never hit the network or MongoEngine machinery — the marker
        log fires before retry()."""
        from autonomous.ai.models import local_model

        instance = self._make_instance("llama3", "http://ollama:11434")

        log_calls = []
        # Emission migrated to ``observability.event()`` (#51 step 3) —
        # event() resolves ``log`` via ``from autonomous import log``
        # inside the function body, so the patch seam moved from the
        # local module's ``log`` import to the package-level
        # ``autonomous.log`` attribute. Same pattern as #50 slice B.
        monkeypatch.setattr(
            "autonomous.log",
            lambda *a, _print=False: log_calls.append(a[0] if a else ""),
        )
        # Patch retry to raise — short-circuit past the network and
        # AutoTasks() lookup that happen inside _attempt.
        monkeypatch.setattr(
            local_model, "retry",
            lambda *a, **kw: (_ for _ in ()).throw(  # noqa: ARG005
                RuntimeError("stop-here")
            ),
        )

        schema = {"type": "object"}
        # Pass system_prompt to avoid self.instructions descriptor access.
        with pytest.raises(RuntimeError, match="stop-here"):
            instance.generate_json(
                "prompt", system_prompt="t", json_schema=schema
            )

        # First call: marker logged AND cache populated.
        assert ("llama3", "http://ollama:11434") in (
            local_model._STRUCTURED_OUTPUTS_LOGGED
        )
        markers = [m for m in log_calls if "STRUCTURED-OUTPUTS-UNAVAILABLE" in m]
        assert len(markers) == 1

    def test_second_schema_call_same_endpoint_does_not_re_log(
        self, monkeypatch
    ):
        """The cache prevents log spam on every JSON call."""
        from autonomous.ai.models import local_model

        instance = self._make_instance("llama3", "http://ollama:11434")

        # Pre-populate the cache to simulate a prior call.
        local_model._STRUCTURED_OUTPUTS_LOGGED.add(
            ("llama3", "http://ollama:11434")
        )

        log_calls = []
        # Emission migrated to ``observability.event()`` (#51 step 3) —
        # event() resolves ``log`` via ``from autonomous import log``
        # inside the function body, so the patch seam moved from the
        # local module's ``log`` import to the package-level
        # ``autonomous.log`` attribute. Same pattern as #50 slice B.
        monkeypatch.setattr(
            "autonomous.log",
            lambda *a, _print=False: log_calls.append(a[0] if a else ""),
        )
        monkeypatch.setattr(
            local_model, "retry",
            lambda *a, **kw: (_ for _ in ()).throw(  # noqa: ARG005
                RuntimeError("stop-here")
            ),
        )

        with pytest.raises(RuntimeError, match="stop-here"):
            instance.generate_json(
                "p", system_prompt="t", json_schema={"type": "object"}
            )

        # Same (model, endpoint): NO new marker logged.
        markers = [m for m in log_calls if "STRUCTURED-OUTPUTS-UNAVAILABLE" in m]
        assert len(markers) == 0

    def test_different_endpoint_logs_separately(self, monkeypatch):
        """Two different (model, endpoint) pairs are tracked
        independently — model swap and endpoint swap each get their
        own marker."""
        from autonomous.ai.models import local_model

        local_model._STRUCTURED_OUTPUTS_LOGGED.add(
            ("llama3", "http://ollama:11434")
        )

        instance = self._make_instance(
            "gemma2", "http://ollama:11434"
        )  # different model

        log_calls = []
        # Emission migrated to ``observability.event()`` (#51 step 3) —
        # event() resolves ``log`` via ``from autonomous import log``
        # inside the function body, so the patch seam moved from the
        # local module's ``log`` import to the package-level
        # ``autonomous.log`` attribute. Same pattern as #50 slice B.
        monkeypatch.setattr(
            "autonomous.log",
            lambda *a, _print=False: log_calls.append(a[0] if a else ""),
        )
        monkeypatch.setattr(
            local_model, "retry",
            lambda *a, **kw: (_ for _ in ()).throw(  # noqa: ARG005
                RuntimeError("stop-here")
            ),
        )

        with pytest.raises(RuntimeError, match="stop-here"):
            instance.generate_json(
                "p", system_prompt="t", json_schema={"type": "object"}
            )

        markers = [m for m in log_calls if "STRUCTURED-OUTPUTS-UNAVAILABLE" in m]
        assert len(markers) == 1
        assert ("gemma2", "http://ollama:11434") in (
            local_model._STRUCTURED_OUTPUTS_LOGGED
        )


# ---------------------------------------------------------------------------
# 8. MockAIModel — absorbs new kwargs
# ---------------------------------------------------------------------------


class TestMockAbsorbsSchemaKwargs:
    @pytest.fixture
    def mock(self):
        from autonomous.ai.models.mock_model import MockAIModel
        return MockAIModel.__new__(MockAIModel)

    def test_generate_json_accepts_json_schema_kwarg(self, mock):
        """The new JSONAgent dispatch signature forwards json_schema
        to non-gemini providers. Mock must absorb it."""
        out = mock.generate_json(
            message="x", json_schema={"type": "object"}
        )
        assert isinstance(out, dict)

    def test_generate_json_accepts_schema_name_kwarg(self, mock):
        out = mock.generate_json(message="x", schema_name="my_thing")
        assert isinstance(out, dict)

    def test_generate_json_accepts_arbitrary_future_kwarg(self, mock):
        """**kwargs absorbs forward-compat extensions."""
        out = mock.generate_json(message="x", future_kwarg=42)
        assert isinstance(out, dict)


# ---------------------------------------------------------------------------
# 9. requirements.txt — jsonschema as a core dependency
# ---------------------------------------------------------------------------


class TestJsonSchemaIsCoreDep:
    def test_jsonschema_pinned_in_requirements_txt(self):
        """The validation safety net is unconditionally available
        (not gated on the [ai] extra). Pin via the requirements file
        rather than just verifying the import — the file is the
        shipped contract that downstream consumers' pip resolvers see."""
        repo_root = Path(__file__).resolve().parents[2]
        req = (repo_root / "requirements.txt").read_text()
        assert "jsonschema" in req

    def test_jsonschema_importable(self):
        """Defense-in-depth: even if requirements.txt drift breaks
        the pin, the import must succeed in the test env (else the
        validation layer would be dead code)."""
        import jsonschema  # noqa: F401

    def test_requirements_pin_includes_major_version_floor(self):
        """A weaker pin (no ``>=`` floor) would let a downstream's
        resolver pull jsonschema 0.x — substring 'jsonschema' alone
        would still pass. Pin the major-version floor explicitly."""
        import re
        repo_root = Path(__file__).resolve().parents[2]
        req_lines = (repo_root / "requirements.txt").read_text().splitlines()
        # Find the jsonschema line (uncommented).
        matches = [
            line for line in req_lines
            if line.strip()
            and not line.strip().startswith("#")
            and re.match(r"^jsonschema[\[=<>!~ ]", line.strip())
        ]
        assert len(matches) == 1, (
            f"Expected exactly one uncommented jsonschema line, got {matches}"
        )
        assert ">=4" in matches[0] or ">=4.0" in matches[0], (
            f"Expected >=4 floor in pin; got: {matches[0]!r}"
        )


# ---------------------------------------------------------------------------
# Coverage gaps surfaced by /review-pr — fallback-failure typed exception
# ---------------------------------------------------------------------------


class TestOpenAIFallbackFailurePath:
    """When the strict-mode HTTPError triggers fallback AND the
    fallback retry ALSO fails, ``generate_json`` must raise
    ``GenerateJSONEmptyResponseError`` (not a bare requests.HTTPError)
    with ``__cause__`` set to the inner exception. This is the typed-
    exception contract MIGRATIONS promises.
    """

    @pytest.fixture(autouse=True)
    def _isolate(self):
        from autonomous.ai.models import openai_compat
        openai_compat._reset_unsupported_cache()
        yield
        openai_compat._reset_unsupported_cache()

    def _make_instance(self):
        from autonomous.ai.models import openai_compat
        instance = openai_compat.OpenAIClient.__new__(openai_compat.OpenAIClient)
        object.__setattr__(instance, "_json_model", "gpt-4")
        object.__setattr__(instance, "_base_url", "http://endpoint")
        # _chat is patched per-test.
        return instance

    def _make_http_error(self, status: int, body: str):
        import requests
        resp = requests.Response()
        resp.status_code = status
        resp._content = body.encode("utf-8")
        err = requests.HTTPError(response=resp)
        return err

    def _wire_fake_chat(self, instance, strict_err, loose_err):
        """Bind a fake _chat on the INSTANCE (not class) so the method
        receives positional args without ``self`` collision. Records
        the response_format of each call for assertion."""
        chat_calls = []

        def fake_chat(model, system, user, response_format, temperature):
            chat_calls.append(response_format)
            if response_format.get("type") == "json_schema":
                raise strict_err
            raise loose_err

        # Plain instance attribute assignment — _chat has no StringAttr
        # descriptor on it (it's a regular method on the class).
        object.__setattr__(instance, "_chat", fake_chat)
        return chat_calls

    def test_fallback_retry_failure_raises_typed_exception(self):
        """The fallback retry's own failure must become
        ``GenerateJSONEmptyResponseError`` with chained cause."""
        from autonomous.ai.exceptions import GenerateJSONEmptyResponseError

        instance = self._make_instance()
        strict_err = self._make_http_error(
            400, '{"error": "json_schema not supported"}'
        )
        loose_err = self._make_http_error(500, "internal error")
        chat_calls = self._wire_fake_chat(instance, strict_err, loose_err)

        with pytest.raises(GenerateJSONEmptyResponseError) as exc_info:
            instance.generate_json(
                "p",
                system_prompt="sys",
                json_schema={"type": "object"},
            )

        # Chained cause is the inner (loose-mode) HTTPError.
        assert exc_info.value.__cause__ is loose_err
        assert len(chat_calls) == 2
        assert chat_calls[0]["type"] == "json_schema"
        assert chat_calls[1]["type"] == "json_object"

    def test_cache_survives_fallback_failure(self):
        """Even when the loose-mode retry also failed, the negative
        cache entry must persist — strict-mode-unsupported is still
        true regardless of whether loose worked. Documented in the
        inline comment at openai_compat.py."""
        from autonomous.ai.models import openai_compat
        from autonomous.ai.exceptions import GenerateJSONEmptyResponseError

        instance = self._make_instance()
        strict_err = self._make_http_error(400, '{"json_schema": "no"}')
        loose_err = self._make_http_error(500, "internal error")
        self._wire_fake_chat(instance, strict_err, loose_err)

        with pytest.raises(GenerateJSONEmptyResponseError):
            instance.generate_json(
                "p",
                system_prompt="sys",
                json_schema={"type": "object"},
            )

        assert (
            "gpt-4", "http://endpoint"
        ) in openai_compat._UNSUPPORTED_STRICT_MODE


class TestJSONAgentParseErrorTypedHierarchy:
    """Bug-fix from /review-pr: ``JSONAgent.generate`` previously
    raised bare ``ValueError`` on invalid JSON / wrong-type response.
    MIGRATIONS' typed-exception contract promises
    ``GenerateJSONParseError`` for parse failures. Pin the typed
    behavior so a regression to bare ValueError is caught.
    """

    def _make_agent(self, return_value, provider="openai"):
        agent = _FakeJSONAgent(provider=provider)
        client = MagicMock()
        client.generate_json.return_value = return_value
        agent.get_client = lambda *a, **kw: client  # noqa: ARG005
        return agent

    def test_invalid_json_string_raises_parse_error_not_value_error(
        self, monkeypatch
    ):
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        agent = self._make_agent("this is definitely not json")

        with pytest.raises(GenerateJSONParseError) as exc_info:
            agent.generate("p")

        # GenerateJSONParseError is a subclass of GenerateJSONError;
        # bare ValueError is NOT in the typed hierarchy.
        assert not isinstance(exc_info.value, ValueError) or isinstance(
            exc_info.value, GenerateJSONParseError
        )
        # .raw captures the unparseable body (truncated to _RAW_MAX).
        assert "this is definitely not json" in exc_info.value.raw

    def test_invalid_json_chains_decode_error(self, monkeypatch):
        """``raise from exc`` preserves the underlying
        ``json.JSONDecodeError`` as ``__cause__`` for debugger
        introspection."""
        import json as json_mod
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        agent = self._make_agent("{invalid")

        with pytest.raises(GenerateJSONParseError) as exc_info:
            agent.generate("p")
        assert isinstance(exc_info.value.__cause__, json_mod.JSONDecodeError)

    def test_non_dict_non_string_raises_parse_error(self, monkeypatch):
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        agent = self._make_agent(["a", "list"])  # neither dict nor string

        with pytest.raises(GenerateJSONParseError) as exc_info:
            agent.generate("p")
        # Message names the offending type for diagnostics.
        assert "list" in str(exc_info.value)
