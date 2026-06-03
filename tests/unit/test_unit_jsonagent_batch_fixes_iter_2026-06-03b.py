"""Independent coverage for PR #25 — the batch fix for issues
#20 (schema-check), #21 (gemini None guard), #22 (mock test overrides).

Written without consulting dev's ``tests/_dev_local/`` (gitignored
anyway — and PR #25 doesn't ship any committed test files, by design;
dev's ephemeral tests proved the fixes end-to-end and the test agent
writes the only committed coverage from a fresh perspective). This is
the second perspective in the two-perspective testing design in
CLAUDE.md — and unusually pure, because there is no committed dev
test surface to accidentally peek at.

Three concern groups are covered:

1. ``_json_utils._schema_check`` — None no-op; valid schema returns
   silently; malformed schema raises ``GenerateJSONParseError`` with
   the original ``jsonschema.SchemaError`` chained as ``__cause__``;
   the error message attributes the bug to the caller's schema (so
   debugging points at the right side).

2. ``JSONAgent.generate`` schema-pre-check ordering — malformed schema
   raises BEFORE any provider dispatch (no HTTP call, no
   ``get_client`` traversal, no log noise). This is the load-bearing
   contract for #20: if a caller passes a typoed schema, the
   ``OpenAIClient`` negative cache must NOT be poisoned by the
   server-side 400 that would otherwise be misclassified as
   "endpoint doesn't support strict mode."

3. ``GeminiAIModel._add_function`` None guard — passing ``None``
   raises ``ValueError`` (not the obscure ``AttributeError`` from
   ``None.get("name")``); the error message points to the public API
   (``function=`` or ``json_schema=``); valid dicts and partial dicts
   (missing-keys) preserve the pre-existing error path.

4. ``MockAIModel.generate_json`` test overrides — per-call
   ``_mock_response=`` returns verbatim and short-circuits the
   heuristic dict; per-instance ``_mock_json_response`` attribute
   does the same and survives across calls; per-call wins when both
   are set; the underscore prefix marks both as not-for-production
   surface.

5. ``JSONAgent.generate`` + ``MockAIModel`` + ``json_schema=`` together
   — the consumer-facing integration scenario that motivated #22:
   schema-aware tests can now route through ``JSONAgent.generate`` and
   get a response that conforms to the schema (without the centralized
   ``_schema_validate`` rejecting the default heuristic dict).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from autonomous.ai._json_utils import _schema_check
from autonomous.ai.exceptions import GenerateJSONParseError


# ---------------------------------------------------------------------------
# 1. _schema_check — None / valid / malformed
# ---------------------------------------------------------------------------


class TestSchemaCheckNoOp:
    def test_none_returns_silently(self):
        """Validation is opt-in. ``schema=None`` is the opt-out path
        and MUST NOT raise — otherwise default-no-schema callers would
        break."""
        _schema_check(None)
        # No assertion needed — passes iff no exception.


class TestSchemaCheckValid:
    @pytest.mark.parametrize(
        "schema",
        [
            {"type": "object"},
            {"type": "object", "properties": {"x": {"type": "string"}}},
            {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
            {"type": "string"},  # primitive schemas are valid JSON Schema too
            {"type": "array", "items": {"type": "integer"}},
            {"oneOf": [{"type": "string"}, {"type": "integer"}]},
        ],
    )
    def test_valid_schemas_return_silently(self, schema):
        _schema_check(schema)


class TestSchemaCheckMalformed:
    """Pin the structural failure modes that motivated #20 — every
    one of these would, pre-fix, have gone to the server and risked
    poisoning ``OpenAIClient``'s negative cache via a 400 that
    matched the strict-mode-unsupported markers."""

    @pytest.mark.parametrize(
        "schema",
        [
            {"type": "not-a-real-type"},
            {"type": ["object", "garbage"]},  # mixed valid/invalid type union
            {"type": "object", "properties": "should-be-an-object"},
            {"type": "object", "required": "should-be-a-list"},
            {"type": "object", "additionalProperties": "must-be-bool-or-schema"},
        ],
    )
    def test_malformed_schemas_raise_parse_error(self, schema):
        with pytest.raises(GenerateJSONParseError) as exc_info:
            _schema_check(schema)
        # Error message attributes blame to the caller, not the model,
        # so debugging points at the right side.
        assert "json_schema is invalid" in str(exc_info.value).lower()

    def test_jsonschema_exception_chained_as_cause(self):
        """``raise from`` preserves the original SchemaError on
        ``__cause__`` for debugger introspection. The library wraps
        for typed-exception consistency but does not lose the
        underlying diagnostic."""
        import jsonschema
        with pytest.raises(GenerateJSONParseError) as exc_info:
            _schema_check({"type": "not-a-real-type"})
        assert isinstance(exc_info.value.__cause__, jsonschema.SchemaError)

    def test_raw_is_empty_on_check_failure(self):
        """``_schema_check`` runs BEFORE any provider response is
        seen, so ``.raw`` is empty by construction. Pin this so a
        future "helpfully populate .raw" refactor doesn't lie about
        provider output that never existed."""
        with pytest.raises(GenerateJSONParseError) as exc_info:
            _schema_check({"type": "garbage"})
        assert exc_info.value.raw == ""


# ---------------------------------------------------------------------------
# 2. JSONAgent.generate — schema-check ordering (no HTTP on malformed)
# ---------------------------------------------------------------------------


class _FakeJSONAgent:
    """Borrow ``JSONAgent.generate`` onto a plain class — same pattern
    as the prior iter tests."""

    from autonomous.ai.jsonagent import JSONAgent  # noqa: E402

    generate = JSONAgent.generate

    def __init__(self, provider: str = "gemini"):
        self.provider = provider
        self.name = "test-agent"
        self.instructions = "test"
        self.description = "test"
        self.meta_calls: list[tuple] = []

    def get_client(self, provider=None, *, persist: bool = True):
        raise NotImplementedError("patch get_client per-test")

    def add_to_job_meta(self, k, v):
        self.meta_calls.append((k, v))


class TestSchemaCheckOrdering:
    """The schema-check must fire BEFORE ``get_client``, BEFORE any
    HTTP work, BEFORE any provider dispatch. This is what prevents
    the OpenAI negative-cache poisoning of #20."""

    def test_malformed_schema_does_not_call_get_client(self, monkeypatch):
        """No provider dispatch should happen when the schema is
        structurally invalid — the agent must short-circuit at the
        pre-check."""
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        agent = _FakeJSONAgent(provider="openai")
        get_client_calls = []

        def get_client(provider=None, *, persist=True):
            get_client_calls.append(provider)
            return MagicMock()

        agent.get_client = get_client  # type: ignore[assignment]

        with pytest.raises(GenerateJSONParseError):
            agent.generate("prompt", json_schema={"type": "garbage"})
        assert get_client_calls == []

    def test_malformed_schema_does_not_dispatch_to_gemini(
        self, monkeypatch
    ):
        """Same invariant from the gemini path — the schema-check at
        the top of generate() runs unconditionally regardless of
        which provider is configured."""
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        agent = _FakeJSONAgent(provider="gemini")
        client = MagicMock()
        agent.get_client = lambda *a, **kw: client  # noqa: ARG005

        with pytest.raises(GenerateJSONParseError):
            agent.generate("prompt", json_schema={"type": "garbage"})
        assert client.generate_json.call_count == 0

    def test_valid_schema_still_dispatches_normally(self, monkeypatch):
        """Defense in depth — confirm the pre-check is correctly
        gated on the schema being invalid, not just on its presence.
        A valid schema must still reach the provider."""
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        agent = _FakeJSONAgent(provider="openai")
        client = MagicMock()
        client.generate_json.return_value = {"x": 1}
        agent.get_client = lambda *a, **kw: client  # noqa: ARG005

        agent.generate(
            "prompt",
            json_schema={
                "type": "object",
                "properties": {"x": {"type": "integer"}},
            },
        )
        assert client.generate_json.call_count == 1


# ---------------------------------------------------------------------------
# 3. GeminiAIModel._add_function — None guard
# ---------------------------------------------------------------------------


class TestGeminiAddFunctionNoneGuard:
    """Issue #21: pre-fix, ``_add_function(None)`` did
    ``None.get("name")`` → ``AttributeError``. Now: clear
    ``ValueError`` with a pointer to the public API."""

    @pytest.fixture
    def gemini(self):
        from autonomous.ai.models.gemini import GeminiAIModel
        return GeminiAIModel.__new__(GeminiAIModel)

    def test_none_raises_value_error_not_attribute_error(self, gemini):
        """The fix replaces ``AttributeError`` with ``ValueError`` —
        ValueError is the canonical type for "caller passed something
        that's wrong-shape for this API," AttributeError implies an
        internal bug. The type change IS observable."""
        with pytest.raises(ValueError):
            gemini._add_function(None)
        # Confirm it's NOT AttributeError (the pre-fix failure).
        with pytest.raises(ValueError):
            try:
                gemini._add_function(None)
            except AttributeError:
                pytest.fail(
                    "Pre-fix AttributeError leaked — None guard missing"
                )

    def test_error_message_points_to_public_api(self, gemini):
        """The error message must mention both entry points
        (``function=`` direct and ``json_schema=`` via JSONAgent) so
        the consumer knows how to recover."""
        with pytest.raises(ValueError) as exc_info:
            gemini._add_function(None)
        msg = str(exc_info.value)
        assert "function=" in msg
        assert "json_schema=" in msg

    def test_valid_function_dict_passes_through_unchanged(self, gemini):
        """The None guard must not regress the valid-input path —
        a complete function dict still returns the tool_schema."""
        func = {
            "name": "extract",
            "description": "Extract structured data.",
            "parameters": {"type": "object"},
        }
        result = gemini._add_function(func)
        assert result == {
            "name": "extract",
            "description": "Extract structured data.",
            "parameters": {"type": "object"},
        }

    @pytest.mark.parametrize(
        "partial",
        [
            {"description": "x", "parameters": {"type": "object"}},  # no name
            {"name": "x", "parameters": {"type": "object"}},  # no description
            {"name": "x", "description": "y"},  # no parameters
            {},  # empty dict
        ],
    )
    def test_partial_function_dict_preserves_pre_existing_error(
        self, gemini, partial
    ):
        """The pre-existing 'Tool schema must have name + description
        + parameters' ValueError still fires for missing keys. The
        None guard is purely additive."""
        with pytest.raises(ValueError, match="name.*description.*parameters"):
            gemini._add_function(partial)


# ---------------------------------------------------------------------------
# 4. MockAIModel.generate_json — test overrides
# ---------------------------------------------------------------------------


class TestMockOverrides:
    """Issue #22: schema-aware tests routing through
    ``JSONAgent.generate`` need the mock provider to return a
    response that conforms to the caller's schema. The default
    heuristic dict won't, so the centralized ``_schema_validate``
    rejects. Two override paths solve this."""

    @pytest.fixture
    def mock(self):
        from autonomous.ai.models.mock_model import MockAIModel
        # __new__ bypass to avoid AutoModel init.
        return MockAIModel.__new__(MockAIModel)

    def test_per_call_override_returns_verbatim(self, mock):
        override = {"name": "Aria", "level": 5, "class": "Fighter"}
        result = mock.generate_json("prompt", _mock_response=override)
        # Must be the SAME object — not a copy — so caller can rely
        # on identity-based assertions.
        assert result is override

    def test_per_instance_override_returns_verbatim(self, mock):
        override = {"name": "Beren", "stat": 42}
        mock._mock_json_response = override
        result = mock.generate_json("prompt")
        assert result is override

    def test_per_instance_override_survives_multiple_calls(self, mock):
        """Unlike per-call (which only applies to a single call),
        the per-instance override persists. Important for code paths
        like JSONAgent.generate that don't thread test kwargs
        through to providers."""
        override = {"persisted": True}
        mock._mock_json_response = override

        for _ in range(3):
            assert mock.generate_json("any prompt") is override

    def test_per_call_wins_over_per_instance(self, mock):
        """When both are set, per-call should take precedence — the
        per-call form is the more specific intent for that single
        call."""
        mock._mock_json_response = {"who": "instance-default"}
        per_call = {"who": "per-call-winner"}
        result = mock.generate_json("p", _mock_response=per_call)
        assert result is per_call

    def test_no_override_falls_through_to_heuristic_default(self, mock):
        """Without either override the existing heuristic-dict path
        runs — preserves backward compatibility for tests that don't
        opt in to the new override hooks."""
        result = mock.generate_json("p")
        assert isinstance(result, dict)
        # The heuristic returns an empty dict for plain prompts with
        # no context — this pins the unchanged baseline behavior.
        assert result == {}

    def test_override_returns_arbitrary_shape(self, mock):
        """The override returns whatever the caller asks for, not
        just dicts — useful for testing the
        ``isinstance(result, dict)`` check in JSONAgent.generate."""
        for shape in [
            {"k": "v"},
            {"nested": {"deep": {"value": 1}}},
            {"with_list": [1, 2, 3]},
            {},  # empty dict is a legitimate override
        ]:
            result = mock.generate_json("p", _mock_response=shape)
            assert result is shape

    def test_underscore_prefix_kwarg_in_signature(self, mock):
        """The underscore-prefix on ``_mock_response`` is a naming
        convention signaling "not for production". Pin that the
        kwarg name is exactly that (a future refactor renaming to
        ``mock_response`` without underscore would break test code
        relying on the documented contract)."""
        # Calling with the documented kwarg name must work...
        result = mock.generate_json("p", _mock_response={"ok": 1})
        assert result == {"ok": 1}

    def test_arbitrary_extra_kwargs_still_absorbed(self, mock):
        """The ``**kwargs`` from the prior PR (#19) still absorbs
        forward-compat kwargs alongside the new ``_mock_response``."""
        result = mock.generate_json(
            "p",
            json_schema={"type": "object"},
            schema_name="x",
            _mock_response={"ok": True},
            future_kwarg=42,
        )
        assert result == {"ok": True}


# ---------------------------------------------------------------------------
# 5. JSONAgent + MockAIModel + json_schema= — the consumer scenario for #22
# ---------------------------------------------------------------------------


class TestIntegrationMockSchemaAware:
    """The motivating scenario for #22: a test author wants to
    exercise ``JSONAgent.generate`` end-to-end with a
    ``json_schema=`` validator gate, using the mock provider. Pre-#22
    the default heuristic dict failed centralized ``_schema_validate``
    and the test couldn't even run the happy path."""

    def test_schema_aware_test_can_route_through_jsonagent_via_per_instance_override(
        self, monkeypatch
    ):
        """The intended consumer use of the per-instance override:
        set a conforming response, then drive
        ``JSONAgent.generate(json_schema=...)`` end-to-end. The
        centralized validator must see the conforming response and
        not raise."""
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        from autonomous.ai.models.mock_model import MockAIModel

        mock = MockAIModel.__new__(MockAIModel)
        # The per-instance override is the right hook here because
        # JSONAgent.generate doesn't thread test kwargs through to
        # the provider — only `temperature` / `json_schema` / the
        # standard signature get forwarded.
        mock._mock_json_response = {
            "name": "Aria",
            "level": 5,
        }
        agent = _FakeJSONAgent(provider="mock")
        agent.get_client = lambda *a, **kw: mock  # noqa: ARG005

        schema = {
            "type": "object",
            "required": ["name", "level"],
            "properties": {
                "name": {"type": "string"},
                "level": {"type": "integer"},
            },
            "additionalProperties": False,
        }
        result = agent.generate("Create a character", json_schema=schema)
        # The validator did not raise; the conforming override was returned.
        assert result == {"name": "Aria", "level": 5}

    def test_schema_aware_test_catches_non_conforming_override(
        self, monkeypatch
    ):
        """And — defense-in-depth from #19 still works: a test author
        who passes a non-conforming override gets a clear
        ``GenerateJSONParseError`` from the centralized validator.
        The override hook is for legitimate tests, not for bypassing
        the safety net."""
        monkeypatch.delenv("JSON_AI_AGENT", raising=False)
        from autonomous.ai.models.mock_model import MockAIModel

        mock = MockAIModel.__new__(MockAIModel)
        mock._mock_json_response = {"name": 42}  # name should be string
        agent = _FakeJSONAgent(provider="mock")
        agent.get_client = lambda *a, **kw: mock  # noqa: ARG005

        schema = {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        }
        with pytest.raises(GenerateJSONParseError):
            agent.generate("p", json_schema=schema)
