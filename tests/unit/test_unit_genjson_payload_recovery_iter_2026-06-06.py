"""Independent test-agent coverage for PR #55 / issue #54:
``GenerateJSONParseError.payload`` — the un-truncated parsed object exposed
on a *schema-validation* miss so consumers can run tolerant recovery
(key-drift normalization, default-fill, re-validate) on the object already
in hand instead of burning a second model round-trip.

Written from a fresh read of the PR diff (no peeking at dev's
``tests/_dev_local/``). Three layers:

1. ``GenerateJSONParseError`` constructor — the new keyword-only
   ``payload`` attr, its default, its keyword-only contract, and that
   ``.raw`` truncation stays independent of it.
2. ``_schema_validate`` — ``.payload`` is the *live* object forwarded on
   the ``ValidationError`` branch and is ``None`` on the ``SchemaError``
   branch (caller's schema is at fault, not the model output).
3. ``JSONAgent.generate`` end-to-end — ``.payload`` flows through to the
   consumer on a schema miss, stays ``None`` for the parse / non-dict
   failure modes, and the headline >500-char recovery case where ``.raw``
   is a truncated *unparseable* fragment but ``.payload`` round-trips whole.
"""

import json

import pytest

from autonomous.ai._json_utils import _schema_validate
from autonomous.ai.exceptions import GenerateJSONParseError
from autonomous.ai.jsonagent import JSONAgent


# Requires both keys, forbids extras — any drift produces a ValidationError.
SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "count": {"type": "integer"},
    },
    "required": ["name", "count"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------
# Layer 1: GenerateJSONParseError constructor
# --------------------------------------------------------------------------
class TestExceptionConstructor:
    def test_payload_defaults_to_none(self):
        """Backward compat: existing raw-only call sites get .payload is None,
        not a missing attribute."""
        e = GenerateJSONParseError("boom", raw="diag")
        assert e.payload is None
        assert e.raw == "diag"

    def test_payload_keyword_stored_verbatim(self):
        """The keyword payload= is stored as-is; positional payload is
        rejected (keyword-only contract — the constructor signature is
        ``(msg, *, raw="", payload=None)``)."""
        obj = {"a": 1}
        e = GenerateJSONParseError("boom", raw="diag", payload=obj)
        assert e.payload == {"a": 1}
        with pytest.raises(TypeError):
            GenerateJSONParseError("boom", "diag", obj)  # positional → rejected

    def test_payload_is_live_reference_not_copy(self):
        """Documented contract: .payload is the live parsed object, not a
        snapshot. A recovery routine mutating it in place mutates the only
        artifact of the failed call."""
        obj = {"name": "x"}
        e = GenerateJSONParseError("boom", payload=obj)
        assert e.payload is obj
        e.payload["name"] = "normalized"
        assert obj["name"] == "normalized"  # mutation reaches the original

    def test_raw_bound_independent_of_payload(self):
        """.raw stays bounded by _RAW_MAX even when a large payload rides
        alongside — the two attrs are independent surfaces (diagnostic vs.
        programmatic)."""
        big_payload = {"k": "v" * 5000}
        e = GenerateJSONParseError("boom", raw="z" * 5000, payload=big_payload)
        assert len(e.raw) == GenerateJSONParseError._RAW_MAX == 500
        # payload is NOT subject to the bound
        assert e.payload["k"] == "v" * 5000


# --------------------------------------------------------------------------
# Layer 2: _schema_validate forwarding
# --------------------------------------------------------------------------
class TestSchemaValidateForwarding:
    def test_validation_miss_forwards_live_payload(self):
        """On a jsonschema.ValidationError, the exact object passed in is
        forwarded by identity on .payload."""
        obj = {"name": "x"}  # missing required "count"
        with pytest.raises(GenerateJSONParseError) as ei:
            _schema_validate(obj, SCHEMA, raw=json.dumps(obj))
        assert ei.value.payload is obj

    def test_full_recovery_when_raw_is_truncated_unparseable(self):
        """Headline case: a payload whose JSON dump exceeds _RAW_MAX. .raw
        is truncated to a fragment that json.loads can't parse, but .payload
        recovers the whole object — the entire reason the attr exists."""
        big = {"name": "n", "items": ["chunk-" + "x" * 40 for _ in range(20)]}
        raw_dump = json.dumps(big)
        assert len(raw_dump) > GenerateJSONParseError._RAW_MAX  # genuinely large

        with pytest.raises(GenerateJSONParseError) as ei:
            _schema_validate(big, SCHEMA, raw=raw_dump)  # extra key "items" → miss
        e = ei.value

        # .raw is the bounded, now-unparseable diagnostic fragment.
        assert len(e.raw) == GenerateJSONParseError._RAW_MAX
        with pytest.raises(json.JSONDecodeError):
            json.loads(e.raw)

        # .payload is the full object — round-trips, recovery is possible.
        assert e.payload == big
        assert e.payload is big

    def test_schema_error_branch_has_no_payload(self):
        """When the *caller's schema* is structurally invalid (SchemaError),
        the model output isn't at fault — .payload stays None, distinguishing
        it from a model schema-miss."""
        bad_schema = {"type": 12345}  # type must be string / list of strings
        with pytest.raises(GenerateJSONParseError, match="schema is invalid") as ei:
            _schema_validate({"any": "payload"}, bad_schema, raw="x")
        assert ei.value.payload is None

    def test_none_schema_is_noop(self):
        """No schema → no validation → no exception (and so no payload)."""
        _schema_validate({"whatever": True}, None)  # must not raise


# --------------------------------------------------------------------------
# Layer 3: JSONAgent.generate end-to-end (hermetic, stubbed provider)
# --------------------------------------------------------------------------
def _agent():
    """Bare JSONAgent that bypasses AutoModel persistence (no Mongo)."""
    agent = JSONAgent.__new__(JSONAgent)
    object.__setattr__(agent, "_data", {})
    object.__setattr__(agent, "_dynamic_fields", {})
    object.__setattr__(agent, "_changed_fields", [])
    object.__setattr__(agent, "_initialised", False)
    object.__setattr__(agent, "_created", True)
    agent._data["provider"] = "openai"
    return agent


class _StubProviderClient:
    def __init__(self, return_value):
        self.return_value = return_value

    def generate_json(self, message, **kwargs):
        return self.return_value


def _patched_agent(monkeypatch, client):
    agent = _agent()
    agent._data["provider"] = "openai"
    agent._meta_log = []
    monkeypatch.setattr(agent, "get_client", lambda _p=None: client)
    monkeypatch.setattr(
        agent, "add_to_job_meta", lambda k, v: agent._meta_log.append((k, v))
    )
    monkeypatch.delenv("JSON_AI_AGENT", raising=False)
    return agent


class TestGenerateEndToEnd:
    def test_schema_miss_exposes_payload_to_consumer(self, monkeypatch):
        """The storyteller lore-blueprint case: a provider returns a parseable
        object that fails schema validation; the consumer gets the parsed
        object back on .payload for tolerant normalization."""
        drifted = {"title": "Aria", "count": 3}  # has "title", not "name"
        agent = _patched_agent(monkeypatch, _StubProviderClient(drifted))

        with pytest.raises(GenerateJSONParseError) as ei:
            JSONAgent.generate(agent, "prompt", json_schema=SCHEMA)
        assert ei.value.payload == drifted

    def test_large_response_recoverable_through_generate(self, monkeypatch):
        """call-site change (dropped redundant [:500]) keeps .raw bounded
        while .payload carries the full >500-char object end-to-end."""
        big = {"name": "n", "blob": "y" * 800}  # extra key + >500 char dump
        agent = _patched_agent(monkeypatch, _StubProviderClient(big))

        with pytest.raises(GenerateJSONParseError) as ei:
            JSONAgent.generate(agent, "prompt", json_schema=SCHEMA)
        e = ei.value
        assert len(e.raw) <= GenerateJSONParseError._RAW_MAX
        assert e.payload == big  # full recovery despite truncated .raw

    def test_parse_failure_has_no_payload(self, monkeypatch):
        """A non-validation failure mode (unparseable string) carries no
        parsed object — .payload stays None."""
        agent = _patched_agent(monkeypatch, _StubProviderClient("not json at all"))

        with pytest.raises(GenerateJSONParseError) as ei:
            JSONAgent.generate(agent, "prompt")  # no schema; parse fails first
        assert ei.value.payload is None

    def test_non_dict_response_has_no_payload(self, monkeypatch):
        """A wrong-type response (int) also has no recoverable object."""
        agent = _patched_agent(monkeypatch, _StubProviderClient(42))

        with pytest.raises(GenerateJSONParseError) as ei:
            JSONAgent.generate(agent, "prompt")
        assert ei.value.payload is None

    def test_conforming_response_returns_normally(self, monkeypatch):
        """Sanity: a conforming response returns the dict, no exception,
        no payload surface involved."""
        ok = {"name": "x", "count": 1}
        agent = _patched_agent(monkeypatch, _StubProviderClient(ok))
        assert JSONAgent.generate(agent, "prompt", json_schema=SCHEMA) == ok

    def test_non_json_native_value_in_response_does_not_leak_typeerror(
        self, monkeypatch
    ):
        """/review-pr regression guard: dropping the redundant ``[:500]`` at
        the call site is correct for length, but ``json.dumps(result)``
        un-guarded raises TypeError on non-JSON-native values (datetime,
        bytes, Decimal) BEFORE ``_schema_validate`` runs. Without
        ``default=str``, the consumer's ``except GenerateJSONParseError``
        handler sees a bare TypeError and loses the entire typed-exception
        surface (no ``.raw``, no ``.payload``, no diagnostic context).

        This test passes a dict containing a ``datetime`` (a common
        non-native value providers sometimes surface through tool-call
        return-shaping) and asserts the consumer still gets a typed
        ``GenerateJSONParseError`` with the recovery surface intact —
        not a leaked TypeError.

        The schema misses on the datetime value (validator type:integer
        for count), so we exercise the ValidationError branch end-to-end
        WITH the non-serializable diagnostic-dump path. ``.raw`` is the
        ``default=str``-stringified diagnostic; ``.payload`` is the live
        dict including the original datetime value (unmodified).
        """
        from datetime import datetime
        when = datetime(2026, 6, 6, 12, 0, 0)
        drifted = {"name": "x", "count": when}  # count should be int
        agent = _patched_agent(monkeypatch, _StubProviderClient(drifted))

        # MUST be GenerateJSONParseError, NOT TypeError. The whole point
        # of the typed-exception design is preserved across the
        # non-serializable case.
        with pytest.raises(GenerateJSONParseError) as ei:
            JSONAgent.generate(agent, "prompt", json_schema=SCHEMA)

        # Recovery surface intact: payload is the live dict with the
        # original (non-serializable) value untouched.
        assert ei.value.payload is drifted
        assert ei.value.payload["count"] is when
        # Diagnostic surface intact: .raw is a non-empty string. The
        # default=str fallback stringified the datetime so the dump
        # succeeded; what specifically went into .raw is an
        # implementation detail (any string repr is acceptable).
        assert isinstance(ei.value.raw, str)
        assert len(ei.value.raw) > 0
