"""_schema_validate is the centralized validation safety net used by
JSONAgent.generate after every provider returns. It must:
  - no-op when schema is None
  - raise GenerateJSONParseError (with raw populated) on mismatch
  - return silently on conforming payloads"""

import pytest

from autonomous.ai._json_utils import _schema_validate
from autonomous.ai.exceptions import GenerateJSONParseError


SAMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "count": {"type": "integer"},
    },
    "required": ["name", "count"],
    "additionalProperties": False,
}


class TestSchemaValidate:
    def test_none_schema_noop(self):
        # Should not raise regardless of payload.
        _schema_validate({"anything": True}, None)
        _schema_validate("not even a dict", None)
        _schema_validate(None, None)

    def test_conforming_payload_silent(self):
        # No raise on a valid payload.
        _schema_validate({"name": "x", "count": 3}, SAMPLE_SCHEMA)

    def test_missing_required_raises(self):
        with pytest.raises(GenerateJSONParseError) as exc_info:
            _schema_validate({"name": "x"}, SAMPLE_SCHEMA)
        # raw defaults to "" when not provided
        assert exc_info.value.raw == ""

    def test_wrong_type_raises(self):
        with pytest.raises(GenerateJSONParseError) as exc_info:
            _schema_validate({"name": "x", "count": "three"}, SAMPLE_SCHEMA)
        # error message mentions the validation failure
        assert "validation" in str(exc_info.value).lower()

    def test_extra_property_raises(self):
        # additionalProperties=False forbids extras
        with pytest.raises(GenerateJSONParseError):
            _schema_validate(
                {"name": "x", "count": 3, "extra": True}, SAMPLE_SCHEMA
            )

    def test_raw_populated_on_failure(self):
        with pytest.raises(GenerateJSONParseError) as exc_info:
            _schema_validate(
                {"name": "x"}, SAMPLE_SCHEMA, raw="<<the raw response>>"
            )
        assert exc_info.value.raw == "<<the raw response>>"

    def test_malformed_schema_raises_parse_error(self):
        """A SchemaError (caller passed an invalid schema) is wrapped
        in GenerateJSONParseError to preserve the typed-exception contract.
        Without this guard, jsonschema.SchemaError would leak through
        JSONAgent.generate to callers who don't import jsonschema."""
        bad_schema = {"type": 12345}  # type must be a string or list of strings
        with pytest.raises(GenerateJSONParseError, match="schema is invalid"):
            _schema_validate({"any": "payload"}, bad_schema, raw="x")
