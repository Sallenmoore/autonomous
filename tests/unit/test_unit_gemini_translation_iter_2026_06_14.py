"""Independent coverage for PR #126 — gemini.generate_json canonical
signature + jsonagent per-provider branch removal (#47 slice 3).

Dev's lockstep tests for this PR cover three slices of the surface:
  - `test_unit_ai_protocol_conformance.py` — `_KNOWN_DRIFT` emptied
  - `test_unit_generate_json_typed_exc_iter_2026_05_25.py` — exception
    dispatch fixtures swapped to json_schema/schema_name shape
  - `test_unit_jsonagent_schema.py::TestDispatchGeminiUniform` +
    `test_unit_json_schema_structured_outputs_iter_2026-06-03.py::TestJSONAgentGeminiDispatch`
    — dispatch uniformity from JSONAgent

What's NOT covered by those tests:

- **The translation step itself.** Dev's tests verify dispatch
  uniformity (gemini gets json_schema=, not function=) and downstream
  exception dispatch, but never directly inspect the function dict
  that gemini synthesizes internally. If the translation produced a
  wrong shape (wrong key names, missing description, parameters set
  to None), the existing dev tests would still pass because they
  stub `_add_function` to a `{"name": ...}` shorthand.
- **`system_prompt` → `additional_instructions` variable mapping
  inside gemini.** Dev's `TestDispatchGeminiUniform` asserts the
  dispatcher PASSES `system_prompt=`; nothing verifies gemini
  internally translates that to `additional_instructions` before
  building `system_instruction`.
- **Parametrized parity across ALL providers.** Dev's slice-3
  tests focus on gemini specifically. The slice's invariant ("every
  provider sees the same call") needs parametrization across the
  full `MODEL_REGISTRY` to catch a regression where, e.g., a future
  slice re-adds an `if provider == "local":` branch.
- **The deprecated `function=` kwarg is gone (contract break).**
  Pre-slice-3 direct callers of `GeminiAIModel.generate_json(message,
  function=...)` worked; post-slice-3 they should TypeError. Dev
  swapped fixtures to the new shape but didn't pin that the old
  shape now errors.
- **`_KNOWN_DRIFT` emptiness invariant.** Dev's conformance test
  still uses the strict-xfail pattern with an empty dict. Pin that
  the catalog is genuinely empty, not "empty by accident because
  someone commented a line out."

If any of those regress, dev's suite stays green and mine catches it.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest


def _make_gemini_recorder():
    """Build a gemini instance that RECORDS what _add_function and
    generate_content receive, without setting up AutoModel.

    Different stub pattern from dev's `_make_gemini_stub`: that one
    stubs `_add_function` to return a `{"name": ...}` shorthand, which
    drops description/parameters from the inspectable surface. Mine
    captures the function dict verbatim so we can pin every field of
    the translation.
    """
    from autonomous.ai.models.gemini import GeminiAIModel

    captured: dict[str, object] = {}

    class _Recorder:
        instructions = "test"
        pk = "test-pk"
        _json_model = "gemini-test"
        file_refs: list = []

        def save(self):
            pass

        def _add_function(self, function):
            captured["function"] = function
            # Return a minimal stub that satisfies the
            # types.FunctionDeclaration construction downstream.
            return {"name": function["name"]}

        def _add_context(self, context):
            captured["context"] = context
            return []

        generate_json = GeminiAIModel.generate_json

    recorder = _Recorder()
    recorder.client = MagicMock()

    # Build an empty-candidates response so generate_json falls into
    # the EmptyResponseError path AFTER the translation step. We
    # don't care about the exception; we care about the function dict
    # we captured before it.
    response = MagicMock()
    response.candidates = []
    recorder.client.models.generate_content.return_value = response

    return recorder, captured


class TestGeminiFunctionDictTranslation:
    """Pin the structure gemini synthesizes from (json_schema, schema_name).

    Translation lives inside GeminiAIModel.generate_json (#47 slice 3).
    Dev's tests verify dispatch uniformity from JSONAgent's side; this
    file pins the function-dict shape gemini constructs internally.
    """

    def test_function_name_from_schema_name(self):
        from autonomous.ai.exceptions import GenerateJSONEmptyResponseError

        recorder, captured = _make_gemini_recorder()
        with pytest.raises(GenerateJSONEmptyResponseError):
            recorder.generate_json(
                "prompt",
                json_schema={"type": "object"},
                schema_name="custom_payload",
            )
        assert captured["function"]["name"] == "custom_payload"

    def test_function_name_defaults_to_response(self):
        from autonomous.ai.exceptions import GenerateJSONEmptyResponseError

        recorder, captured = _make_gemini_recorder()
        with pytest.raises(GenerateJSONEmptyResponseError):
            recorder.generate_json(
                "prompt", json_schema={"type": "object"}
            )
        assert captured["function"]["name"] == "response"

    def test_function_description_is_structured_response_shape(self):
        # The translation hardcodes the description string — gemini's
        # tool-call API requires a non-empty description (and
        # GeminiAIModel._add_function validates this). Pin it; a
        # future refactor renaming it to "" would silently fail
        # _add_function's validation.
        from autonomous.ai.exceptions import GenerateJSONEmptyResponseError

        recorder, captured = _make_gemini_recorder()
        with pytest.raises(GenerateJSONEmptyResponseError):
            recorder.generate_json(
                "prompt", json_schema={"type": "object"}
            )
        assert captured["function"]["description"] == "Structured response shape."

    def test_function_parameters_is_the_json_schema(self):
        from autonomous.ai.exceptions import GenerateJSONEmptyResponseError

        recorder, captured = _make_gemini_recorder()
        complex_schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer", "minimum": 0},
            },
            "required": ["name"],
        }
        with pytest.raises(GenerateJSONEmptyResponseError):
            recorder.generate_json(
                "prompt", json_schema=complex_schema
            )
        # The schema must round-trip without modification — gemini
        # forwards it as `parameters` for its tool call. A regression
        # that mutated the schema (e.g. stripping "minimum") would
        # silently break callers' validation contracts.
        assert captured["function"]["parameters"] == complex_schema

    def test_function_dict_has_exactly_three_keys(self):
        # Pin the dict shape: any extra key would either (a) leak into
        # gemini's tool spec causing a downstream API rejection or (b)
        # be silently ignored (worse — masking an intended override).
        from autonomous.ai.exceptions import GenerateJSONEmptyResponseError

        recorder, captured = _make_gemini_recorder()
        with pytest.raises(GenerateJSONEmptyResponseError):
            recorder.generate_json(
                "prompt", json_schema={"type": "object"}
            )
        assert set(captured["function"].keys()) == {
            "name", "description", "parameters"
        }


class TestGeminiSystemPromptMapping:
    """Verify `system_prompt` → `additional_instructions` translation.

    Dev tests cover the dispatcher PASSING system_prompt. None
    inspect gemini's downstream construction of `system_instruction`
    from `instructions` + `additional_instructions`. If the
    translation drops or renames `system_prompt`, the production
    system instruction sent to the API is silently wrong.
    """

    def test_system_prompt_lands_in_system_instruction(self):
        from autonomous.ai.exceptions import GenerateJSONEmptyResponseError

        recorder, _ = _make_gemini_recorder()
        with pytest.raises(GenerateJSONEmptyResponseError):
            recorder.generate_json(
                "prompt",
                system_prompt="be terse and accurate",
                json_schema={"type": "object"},
            )
        call_kwargs = recorder.client.models.generate_content.call_args.kwargs
        config = call_kwargs["config"]
        # The production code passes `config` as a `types.GenerateContentConfig`
        # object — we can read its system_instruction attribute back.
        system_instruction = getattr(config, "system_instruction", None) or config
        # Accept either the structured config object or a passthrough
        # dict shape; assert the string contains both halves.
        rendered = str(system_instruction)
        assert "test" in rendered  # `self.instructions = "test"`
        assert "be terse and accurate" in rendered

    def test_system_prompt_none_defaults_to_empty_string(self):
        # `additional_instructions = system_prompt or ""` — verify None
        # input doesn't blow up the string concatenation downstream.
        from autonomous.ai.exceptions import GenerateJSONEmptyResponseError

        recorder, _ = _make_gemini_recorder()
        # No system_prompt kwarg; default None.
        with pytest.raises(GenerateJSONEmptyResponseError):
            recorder.generate_json(
                "prompt", json_schema={"type": "object"}
            )
        # If `additional_instructions` were None instead of "" the
        # f-string `f"{self.instructions}.{additional_instructions}"`
        # would render "test.None" — visually broken; better to fail
        # noisily, but the empty-string default is the contract.
        call_kwargs = recorder.client.models.generate_content.call_args.kwargs
        config = call_kwargs["config"]
        system_instruction = getattr(config, "system_instruction", None) or config
        assert "None" not in str(system_instruction)


class TestGeminiMissingSchemaContract:
    """The ValueError-before-HTTP contract for `json_schema=None`.

    Dev's `test_missing_json_schema_raises_value_error` covers the
    raise + no-HTTP invariant. I cover the diagnostic content — a
    user reading the message should learn how to fix it (which
    caller method, which kwarg).
    """

    def test_message_names_json_schema_kwarg(self):
        recorder, _ = _make_gemini_recorder()
        with pytest.raises(ValueError) as exc_info:
            recorder.generate_json("prompt")
        assert "json_schema" in str(exc_info.value)

    def test_message_names_jsonagent_caller_path(self):
        # Discoverability: the user should learn the canonical caller
        # method (JSONAgent.generate) from the error message, not
        # have to grep the source.
        recorder, _ = _make_gemini_recorder()
        with pytest.raises(ValueError) as exc_info:
            recorder.generate_json("prompt")
        rendered = str(exc_info.value)
        assert "JSONAgent" in rendered

    def test_message_explains_why_gemini_needs_schema(self):
        # WHY this contract exists — gemini's structured output IS
        # tool-calling; the typed error explains for context.
        recorder, _ = _make_gemini_recorder()
        with pytest.raises(ValueError) as exc_info:
            recorder.generate_json("prompt")
        rendered = str(exc_info.value).lower()
        # At least one of these keywords appears — they explain the
        # constraint. (Looser than dev's exact-string match so future
        # rewording for clarity doesn't break the test.)
        assert any(k in rendered for k in ("tool", "tool-call", "tool-calling"))

    def test_no_http_call_on_missing_schema(self):
        # Dev covered this. I'm including it as a load-bearing
        # invariant: a config-error path that hits the network would
        # waste the user's quota + leak the broken prompt to the
        # provider. The check is cheap; the regression would be
        # expensive.
        recorder, _ = _make_gemini_recorder()
        with pytest.raises(ValueError):
            recorder.generate_json("prompt")
        recorder.client.models.generate_content.assert_not_called()


class TestDeprecatedFunctionKwargContractBreak:
    """Slice 3 dropped `function=` from gemini's generate_json signature.

    Direct callers using the pre-slice-3 shape should now error at
    the boundary (not silently no-op via `**kwargs`). Dev's tests
    swapped fixtures FROM the old shape TO the new; this pins that
    the OLD shape now errors — preventing accidental re-introduction
    of the kwarg via `**kwargs` capture.
    """

    def test_function_kwarg_raises_type_error(self):
        recorder, _ = _make_gemini_recorder()
        with pytest.raises(TypeError):
            recorder.generate_json(
                "prompt",
                function={"name": "x", "parameters": {}},
            )

    def test_additional_instructions_kwarg_raises_type_error(self):
        recorder, _ = _make_gemini_recorder()
        with pytest.raises(TypeError):
            recorder.generate_json(
                "prompt",
                additional_instructions="x",
                json_schema={"type": "object"},
            )

    def test_signature_has_no_function_parameter(self):
        from autonomous.ai.models.gemini import GeminiAIModel

        sig = inspect.signature(GeminiAIModel.generate_json)
        assert "function" not in sig.parameters
        assert "additional_instructions" not in sig.parameters

    def test_signature_has_canonical_protocol_params(self):
        from autonomous.ai.models.gemini import GeminiAIModel

        sig = inspect.signature(GeminiAIModel.generate_json)
        # Every canonical kwarg from AIModelProtocol must be present.
        for name in (
            "message",
            "system_prompt",
            "json_schema",
            "schema_name",
            "uri",
            "context",
            "temperature",
        ):
            assert name in sig.parameters, f"missing canonical kwarg: {name}"


class TestUniformDispatchAcrossAllProviders:
    """The slice-3 invariant — every provider gets the exact same
    kwarg set from JSONAgent dispatch — verified parametrically.

    Dev tests pin gemini specifically (the one that changed). I
    parametrize across the full registry so a regression that
    re-introduces an `if provider == "X":` branch for ANY provider
    is caught at this slice's gate.
    """

    def _make_provider_stub(self, return_value=None):
        client = MagicMock()
        client.generate_json.return_value = (
            return_value if return_value is not None else {"ok": True}
        )
        return client

    def _make_agent(self, provider, client):
        # Bypass AutoModel descriptor state — touching `.provider`
        # through the StringAttr descriptor needs `_initialised` etc.
        # Pattern mirrors the existing `_agent()` helper in
        # tests/unit/test_unit_jsonagent_schema.py.
        from autonomous.ai.jsonagent import JSONAgent

        agent = JSONAgent.__new__(JSONAgent)
        object.__setattr__(agent, "_data", {"provider": provider})
        object.__setattr__(agent, "_dynamic_fields", {})
        object.__setattr__(agent, "_changed_fields", [])
        object.__setattr__(agent, "_initialised", False)
        object.__setattr__(agent, "_created", True)
        agent.get_client = lambda *a, **kw: client  # noqa: ARG005
        agent.add_to_job_meta = lambda *a, **kw: None  # noqa: ARG005
        return agent

    @pytest.mark.parametrize(
        "provider",
        ["local", "gemini", "openai_compat", "mock"],
    )
    def test_dispatch_kwarg_set_is_uniform(self, provider, monkeypatch):
        """Every provider receives the same kwarg keys. If a future
        slice re-adds an `if provider == "X":` branch, the kwarg set
        diverges and this test fails.
        """
        from autonomous.ai.jsonagent import JSONAgent

        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        client = self._make_provider_stub()
        agent = self._make_agent(provider, client)

        JSONAgent.generate(
            agent, "prompt",
            json_schema={"type": "object"},
            schema_name="thing",
            system_prompt="terse",
        )

        call_kwargs = client.generate_json.call_args.kwargs
        # Canonical kwarg keys forwarded uniformly.
        assert set(call_kwargs.keys()) >= {
            "system_prompt", "json_schema", "schema_name",
            "uri", "context",
        }
        # Pre-slice-3 translation artifacts MUST NOT appear at the
        # dispatch boundary for any provider.
        assert "function" not in call_kwargs
        assert "additional_instructions" not in call_kwargs

    @pytest.mark.parametrize(
        "provider",
        ["local", "gemini", "openai_compat", "mock"],
    )
    def test_dispatch_kwarg_values_are_uniform(self, provider, monkeypatch):
        """Same inputs → same kwarg values, regardless of provider."""
        from autonomous.ai.jsonagent import JSONAgent

        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        client = self._make_provider_stub()
        agent = self._make_agent(provider, client)
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}

        JSONAgent.generate(
            agent, "prompt",
            json_schema=schema,
            schema_name="my_thing",
            system_prompt="precise",
        )

        call_kwargs = client.generate_json.call_args.kwargs
        assert call_kwargs["json_schema"] == schema
        assert call_kwargs["schema_name"] == "my_thing"
        assert call_kwargs["system_prompt"] == "precise"


class TestKnownDriftEmptyInvariant:
    """`_KNOWN_DRIFT` is the catalog of adapter-method pairs that
    fail conformance. Slice 3 emptied it.

    A regression that re-introduced a drift entry — without fixing
    the adapter — would silently get the strict-xfail pass and look
    "green." Pin the emptiness as an invariant.
    """

    def test_known_drift_is_empty(self):
        from tests.unit import test_unit_ai_protocol_conformance as conf

        assert conf._KNOWN_DRIFT == {}, (
            "_KNOWN_DRIFT is supposed to be empty post-slice-3 — every "
            "adapter conforms. Adding an entry without fixing the "
            "adapter masks the regression behind strict-xfail. If a "
            "future slice introduces new drift, the entry must cite "
            "the slice that will fix it AND the underlying adapter "
            "regression must be a separate, deliberate choice."
        )

    def test_no_xfail_marks_on_conformance_params(self):
        # Cross-check: with _KNOWN_DRIFT empty, _params() should
        # produce no entries with xfail marks. If anyone hardcodes
        # an xfail without going through _KNOWN_DRIFT, this catches
        # it.
        from tests.unit import test_unit_ai_protocol_conformance as conf

        params = conf._params()
        for p in params:
            # pytest.param's `.marks` is the tuple of attached marks.
            # An empty dict + no hardcoded marks = no entries with marks.
            assert not p.marks, (
                f"unexpected mark on conformance param: {p.id}; "
                f"marks={p.marks}"
            )
