"""
Shared utilities for cleaning JSON responses from LLMs that don't reliably
honor structured-output requests (Llama 3 / Gemma family in particular, but
also OpenAI-compatible endpoints when `response_format=json_object` is
ignored by the served model).
"""

import re

import jsonschema

from autonomous.ai.exceptions import GenerateJSONParseError


def clean_json_response(text):
    """
    Robust cleaner for LLM JSON outputs.

    Handles markdown code blocks, prose chatter before/after the JSON object,
    and the case where the model returns naked field-pairs without a wrapping
    `{ }`.

    Returns a string that is expected to be valid JSON; the caller is still
    responsible for `json.loads(...)`.
    """
    text = text.strip()

    # 1. Strip markdown code blocks (```json ... ``` or ``` ... ```).
    if "```" in text:
        pattern = r"```(?:json)?\s*(\{.*?\})\s*```"
        match = re.search(pattern, text, re.DOTALL)
        if match:
            text = match.group(1)
        else:
            # Fallback: take everything between the first and last triple-tick.
            start = text.find("```")
            end = text.rfind("```")
            first_newline = text.find("\n", start)
            if first_newline != -1 and first_newline < end:
                text = text[first_newline:end]

    # 2. Heuristic: extract from the first '{' to the last '}'.
    # Fixes "Here is the JSON: { ... }" and similar prose-prefixed responses.
    start_idx = text.find("{")
    end_idx = text.rfind("}")

    if start_idx != -1 and end_idx != -1:
        text = text[start_idx : end_idx + 1]
    elif text.strip() and '":' in text:
        # Naked field-pairs: '"name": "Aria", "desc": "..."' -> wrap in '{ }'.
        # Gated on `":"` so prose error strings ("I couldn't generate that.")
        # without JSON structure aren't wrapped.
        stripped = text.strip().rstrip(",")
        text = "{" + stripped + "}"

    return text.strip()


def _schema_check(schema):
    """Validate that ``schema`` is itself a structurally-valid JSON Schema.

    Called at the ``JSONAgent.generate`` entry point BEFORE any HTTP work
    so a malformed caller-supplied schema surfaces as a clear
    ``GenerateJSONParseError`` instead of triggering a server-side 400
    that ``OpenAIClient.generate_json``'s strict-mode fallback heuristic
    might misclassify as "endpoint doesn't support strict mode" — the
    false-positive caching bug tracked in issue #20.

    No-op when ``schema`` is None (the opt-out path).

    **Limitation:** ``check_schema`` validates against the JSON Schema
    meta-schema only; it does NOT enforce OpenAI strict-output dialect
    restrictions (every property in ``required``, ``additionalProperties:
    false`` mandatory, no ``format``/``$ref``). A meta-schema-valid but
    OpenAI-strict-invalid schema can still trip the negative cache. That
    narrower closure is tracked separately — the right fix lives in
    ``_looks_like_unsupported_strict_mode`` (tighten markers to capability
    phrases) rather than here.
    """
    if schema is None:
        return
    # Pre-check: jsonschema's check_schema raises TypeError on non-dict
    # input (e.g. a bare list). Surface as the typed parse error here so
    # the caller gets one consistent exception class to catch.
    if not isinstance(schema, dict):
        raise GenerateJSONParseError(
            f"Caller-supplied json_schema must be a dict, "
            f"got {type(schema).__name__}.",
            raw="",
        )
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise GenerateJSONParseError(
            f"Caller-supplied json_schema is invalid: {exc.message}",
            raw="",
        ) from exc


def _schema_validate(payload, schema, raw=""):
    """Validate ``payload`` against a JSON Schema.

    No-op when ``schema`` is None — the validation safety net is opt-in
    via the ``json_schema=`` kwarg on ``JSONAgent.generate``. When set,
    raises ``GenerateJSONParseError`` with ``raw`` populated for caller
    diagnostics.

    Called centrally from ``JSONAgent.generate`` after every provider
    returns, including gemini's strict function-calling response —
    defense in depth against provider bugs.
    """
    if schema is None:
        return
    try:
        jsonschema.validate(instance=payload, schema=schema)
    except jsonschema.ValidationError as exc:
        raise GenerateJSONParseError(
            f"Response failed schema validation: {exc.message}",
            raw=raw or "",
        ) from exc
    except jsonschema.SchemaError as exc:
        raise GenerateJSONParseError(
            f"Caller-supplied schema is invalid: {exc.message}",
            raw=raw or "",
        ) from exc
