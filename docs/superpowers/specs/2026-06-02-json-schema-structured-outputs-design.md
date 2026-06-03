# JSON Schema / Structured Outputs support for autonomous

**Status:** Approved, awaiting implementation plan
**Date:** 2026-06-02
**Owner:** samoore
**Tracked in:** `Sallenmoore/storyteller#12` (filed against the consumer's tracker; library work happens in autonomous)
**Affected packages:** `autonomous.ai.jsonagent`, `autonomous.ai._json_utils`, `autonomous.ai.models.openai_compat`, `autonomous.ai.models.local_model`, `autonomous.ai.models.mock_model`

## Context

Storyteller's lore-builder has been hitting a recurring class of failures (issues #18 / #20 / #23 in the storyteller tracker) where the AI returns a structurally-different content shape than requested — e.g., a scene blueprint instead of party reactions. The root cause is that `JSONAgent` → `OpenAIClient.generate_json` currently sets `response_format={"type": "json_object"}` (loose mode at `src/autonomous/ai/models/openai_compat.py:229`) — this forces "valid JSON" but allows the model to pick any shape.

Storyteller has already shipped a **belt-and-suspenders prompt-restructuring fix** (two-stage pipeline, inverted prompt order, one-shot example — design at `docs/superpowers/specs/2026-05-28-lore-prompt-restructure-design.md` in the storyteller tree). That works on any model regardless of API surface.

This design is the **cleaner, stronger primary fix**: use OpenAI's structured-outputs strict mode (`response_format: {"type": "json_schema", "json_schema": {...}, "strict": true}`) so the server-side decoder makes shape-drift structurally impossible. The library-side change adds the optional `json_schema=` parameter; storyteller adoption follows per call site at the consumer's pace.

### Current state per provider

| Provider | Schema enforcement today |
|---|---|
| `GeminiAIModel.generate_json(message, function, ...)` | Strict — `function.parameters` is a JSON schema bound via function-calling |
| `OpenAIClient.generate_json(message, ...)` | **Loose** — `response_format={"type": "json_object"}` only (the gap this design closes) |
| `LocalAIModel.generate_json(message, ...)` | None — system prompt + `clean_json_response()` regex cleanup |
| `MockAIModel.generate_json(message, ...)` | n/a — returns deterministic mock |

`JSONAgent.generate(message, system_prompt, uri, context, temperature)` dispatches to whichever provider `JSON_AI_AGENT` env var selects. No schema parameter today.

## Goal

Add cross-provider `json_schema=` support to `JSONAgent.generate` and its providers' `generate_json` methods, so storyteller call sites can declare the expected response shape and have it enforced at every layer the runtime supports — server-side strict mode when available, client-side validation always.

## Non-goals

- Storyteller-side adoption. Per-call-site schema design + integration is downstream work in the storyteller tree, one PR per generator, at storyteller's cadence.
- Changing `GeminiAIModel.generate_json`'s existing public surface. Its current `function=` parameter already takes a schema; the new `json_schema=` is handled by translation at the `JSONAgent` dispatch layer, not by changing gemini's API.
- Detecting silent-ignore (server returns 200 but ignored the strict-mode field). The client-side validation safety net raises `GenerateJSONParseError` in that case, but we do not auto-cache the endpoint as unsupported in v1. If silent-ignore turns out to be common, add the secondary detection later.
- Schema-driven retry strategies (e.g., re-prompting with the validation error). Validation failure is terminal in v1; caller decides whether to retry.

## Architecture

A new optional `json_schema=` kwarg threads through `JSONAgent.generate` and the three non-gemini providers' `generate_json` methods. `JSONAgent` does per-provider translation at dispatch time and a centralized client-side validation pass on every response.

Three concerns split across modules:

1. **OpenAI strict-mode + capability discovery** lives in `openai_compat.py` (the new payload shape, the conservative 400-detection heuristic, the negative-cache, the loose-mode fallback).
2. **Client-side validation** lives in `_json_utils._schema_validate` (uses `jsonschema.validate()` from a new core dependency; raises `GenerateJSONParseError` on mismatch).
3. **Cross-provider translation** lives in `JSONAgent.generate` (gemini path synthesizes the existing `function` dict from the schema; openai/local/mock paths pass `json_schema=` through directly).

`jsonschema>=4.0` is added to **core** dependencies in `pyproject.toml` (not `[ai]` extra) so the validation safety net is unconditionally available for every consumer that opts in by passing a schema. Footprint cost: ~250KB including jsonschema's own deps. Trade-off accepted for simpler contract.

## Components and interfaces

### `src/autonomous/ai/_json_utils.py` — addition

```python
import jsonschema

from autonomous.ai.exceptions import GenerateJSONParseError


def _schema_validate(payload, schema, raw=""):
    """Validate ``payload`` against ``schema`` (jsonschema Draft 2020-12
    by default). No-op when ``schema`` is None.

    Raises ``GenerateJSONParseError`` on mismatch with ``raw`` populated
    for caller diagnostics. The library's defense-in-depth layer: every
    provider's response is validated, even gemini's strict
    function-calling response, because provider bugs do happen.
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
```

### `src/autonomous/ai/jsonagent.py` — extension

Adds two new kwargs and per-provider dispatch + centralized validation:

```python
class JSONAgent(BaseAgent):
    # ... existing class attrs unchanged ...

    def generate(
        self,
        message,
        system_prompt="",
        uri="",
        context="",
        temperature=None,
        json_schema=None,
        schema_name="response",
    ):
        provider = os.environ.get("JSON_AI_AGENT", self.provider)
        client = self.get_client(provider)

        kwargs = {}
        if temperature is not None:
            kwargs["temperature"] = temperature

        # Per-provider translation. Gemini's existing function= parameter
        # already IS a JSON-schema carrier (function.parameters), so the
        # translation here just rewraps; other providers accept json_schema=
        # directly and handle it internally.
        if provider == "gemini" and json_schema is not None:
            function = {
                "name": schema_name,
                "description": "Structured response shape.",
                "parameters": json_schema,
            }
            result = client.generate_json(
                message,
                function,
                additional_instructions=system_prompt,
                uri=uri,
                context=context,
                **kwargs,
            )
        else:
            result = client.generate_json(
                message,
                system_prompt=system_prompt,
                uri=uri,
                context=context,
                json_schema=json_schema,
                schema_name=schema_name,
                **kwargs,
            )

        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                raise ValueError(f"Invalid JSON response from AI model.\n\n{result}")
        elif not isinstance(result, dict):
            raise ValueError(f"Invalid JSON response from AI model.\n\n{result}")

        # Defense in depth: validate every provider's output, including
        # gemini's strict function-calling response. Provider bugs happen.
        from autonomous.ai._json_utils import _schema_validate
        _schema_validate(result, json_schema, raw=json.dumps(result)[:500])

        self.add_to_job_meta("Last JSON", result)
        return result
```

### `src/autonomous/ai/models/openai_compat.py` — extension

New strict-mode payload, conservative 400 detection, negative cache, fallback:

```python
# Module-level negative cache: (model, base_url) tuples known to NOT
# support strict-mode response_format. Populated on first conservative
# 400 detection. Cleared by _reset_unsupported_cache() (tests + manual
# operator override). Process-lifetime granularity is appropriate —
# servers gain strict-mode support via deploys, deploys typically
# accompany worker restarts.
_UNSUPPORTED_STRICT_MODE: set[tuple[str, str]] = set()

_STRICT_MODE_ERROR_MARKERS = (
    "json_schema",
    "response_format",
    "unsupported_parameter",
    "structured output",
)


def _reset_unsupported_cache() -> None:
    """Clear the negative cache. Tests use this for isolation; operators
    use it after deploying a server-side fix to re-probe strict-mode
    support without restarting the worker."""
    _UNSUPPORTED_STRICT_MODE.clear()


def _looks_like_unsupported_strict_mode(status: int, body_text: str) -> bool:
    """Conservative heuristic: only flag responses whose body explicitly
    mentions strict-mode-specific terms. A bare 400 (real client bug,
    e.g. bad schema or bad model name) is intentionally NOT cached —
    silently retrying in loose mode would mask the real error."""
    if status not in (400, 422):
        return False
    body_lower = body_text.lower()
    return any(m in body_lower for m in _STRICT_MODE_ERROR_MARKERS)


class OpenAIClient(AutoModel):
    # ... existing class body unchanged through _chat ...

    def generate_json(
        self,
        message,
        system_prompt=None,
        uri="",
        context=None,
        temperature=0.7,
        evaluation=False,
        json_schema=None,
        schema_name="response",
    ):
        # ... existing system prompt + user message construction ...

        # Build the response_format payload. Strict mode when:
        #   - caller passed a schema
        #   - this (model, endpoint) is not in the negative cache
        # Otherwise loose mode (the existing behavior).
        endpoint_key = (self._json_model, self._base_url)
        use_strict = json_schema is not None and endpoint_key not in _UNSUPPORTED_STRICT_MODE
        if use_strict:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "schema": json_schema,
                    "strict": True,
                },
            }
        else:
            response_format = {"type": "json_object"}

        try:
            raw = self._chat(
                self._json_model,
                system,
                user,
                response_format=response_format,
                temperature=temperature,
            )
        except requests.HTTPError as exc:
            # requests raises HTTPError on response.raise_for_status();
            # the response is exc.response. Inspect for unsupported-strict-mode
            # signature and fall back if it matches.
            resp = exc.response
            if (
                use_strict
                and resp is not None
                and _looks_like_unsupported_strict_mode(resp.status_code, resp.text)
            ):
                _UNSUPPORTED_STRICT_MODE.add(endpoint_key)
                log(
                    f"[STRUCTURED-OUTPUTS-UNAVAILABLE] First detection: "
                    f"model={self._json_model} endpoint={self._base_url} "
                    f"status={resp.status_code} body_excerpt={resp.text[:200]!r} "
                    f"(cached for this process)",
                    _print=True,
                )
                # Retry once with loose mode.
                raw = self._chat(
                    self._json_model,
                    system,
                    user,
                    response_format={"type": "json_object"},
                    temperature=temperature,
                )
            else:
                raise
        except (KeyError, IndexError, TypeError) as exc:
            raise GenerateJSONEmptyResponseError(
                f"HPC chat endpoint returned a malformed body: {exc}"
            ) from exc

        # ... existing empty-body + JSON-parse handling unchanged ...

        # Note: JSONAgent.generate handles client-side schema validation
        # centrally. We do NOT call _schema_validate here.
```

Implementation note: the existing code uses `response.raise_for_status()` inside `_post`, which raises `requests.HTTPError`. The new try/except above catches that specifically. The existing `_TRANSPORT_FAILURE_CODES` path (401/502/503/504 → `HPCUnreachableError`) is unaffected.

### `src/autonomous/ai/models/local_model.py` — extension

```python
# Module-level cache of (model, endpoint) combos we've already logged
# the "no structured outputs support" marker for. Avoids log spam on
# every JSON call.
_STRUCTURED_OUTPUTS_LOGGED: set[tuple[str, str]] = set()


class LocalAIModel(AutoModel):
    def generate_json(
        self,
        message,
        system_prompt=None,
        uri="",
        context=None,
        temperature=0.7,
        evaluation=False,
        json_schema=None,
        schema_name="response",
    ):
        # The local Ollama path has no equivalent of OpenAI's strict-mode
        # response_format. Log once per (model, endpoint) so operators know
        # they're on the prompt-only enforcement path, and proceed as today.
        if json_schema is not None:
            key = (self._text_model, self._ollama_url)
            if key not in _STRUCTURED_OUTPUTS_LOGGED:
                _STRUCTURED_OUTPUTS_LOGGED.add(key)
                log(
                    f"[STRUCTURED-OUTPUTS-UNAVAILABLE] LocalAIModel does not "
                    f"support strict-mode schema enforcement. Model={self._text_model} "
                    f"endpoint={self._ollama_url}. Falling back to prompt-only "
                    f"shape guidance + client-side validation.",
                    _print=True,
                )

        # ... existing implementation unchanged ...
```

The schema is *not* injected into the prompt — the prompt-restructuring belt-and-suspenders in storyteller already handles shape guidance via examples and structure. Adding the schema to the prompt could fight that. Client-side validation in `JSONAgent.generate` provides the safety net.

### `src/autonomous/ai/models/mock_model.py` — extension

```python
def generate_json(
    self,
    message,
    system_prompt=None,
    uri="",
    context=None,
    temperature=None,
    **kwargs,  # absorb json_schema, schema_name, future kwargs
):
    log(f"⚡ [MOCK] Generating JSON for prompt: {message[:20]}...", _print=True)
    return self._MOCK_JSON
```

Mock JSON is deterministic; schema validation against arbitrary schemas would fail in tests that don't tailor mock data to the schema. Test authors who want schema-validation testing should construct mock data that conforms.

### `pyproject.toml` — dependency change

Add `jsonschema>=4.0` to the core `[project].dependencies` list (not to the `[project.optional-dependencies].ai` extra). Rationale: validation is part of the JSONAgent contract once a schema is passed; making it conditional on an extra creates a surprising "feature works in some installs, raises in others" gotcha.

## Data flow

### Worked example 1 — storyteller calls with schema; HPC supports strict mode

```
storyteller → JSONAgent.generate(message, json_schema=LORE_BLUEPRINT_SCHEMA)
  │
  ├─ provider = "openai" (via JSON_AI_AGENT env)
  ├─ client = OpenAIClient(...)
  │
  ├─ client.generate_json(message, json_schema=LORE_BLUEPRINT_SCHEMA, schema_name="response")
  │     │
  │     ├─ endpoint_key = ("gpt-oss:20b", "https://chat.binghamton.edu/api")
  │     ├─ endpoint_key NOT in _UNSUPPORTED_STRICT_MODE → use_strict=True
  │     ├─ response_format = {"type": "json_schema", "json_schema": {name, schema, strict}}
  │     ├─ POST /chat/completions → 200 with valid conforming JSON
  │     └─ return raw JSON string
  │
  ├─ json.loads(raw) → dict
  ├─ _schema_validate(result, LORE_BLUEPRINT_SCHEMA) → passes (defense in depth)
  ├─ job_meta.Last JSON = result
  └─ return result
```

### Worked example 2 — same call, HPC returns conservative 400 on first attempt

```
storyteller → JSONAgent.generate(message, json_schema=LORE_BLUEPRINT_SCHEMA)
  │
  ├─ client.generate_json(message, json_schema=...)
  │     │
  │     ├─ use_strict=True
  │     ├─ POST /chat/completions → HTTPError 400, body="...response_format not supported..."
  │     ├─ _looks_like_unsupported_strict_mode(400, body) → True
  │     ├─ _UNSUPPORTED_STRICT_MODE.add(endpoint_key)
  │     ├─ log("[STRUCTURED-OUTPUTS-UNAVAILABLE] First detection: ...")
  │     ├─ POST /chat/completions with {"type": "json_object"} → 200 with JSON-shaped response
  │     └─ return raw JSON string
  │
  ├─ json.loads(raw) → dict
  ├─ _schema_validate(result, LORE_BLUEPRINT_SCHEMA) → may pass or fail (loose mode)
  │     │
  │     └─ on fail: raises GenerateJSONParseError(raw=...) — caller catches per MIGRATIONS contract
  └─ return result (if validation passed)
```

### Worked example 3 — second call to the same (model, endpoint)

```
storyteller → JSONAgent.generate(message, json_schema=LORE_BLUEPRINT_SCHEMA)
  │
  ├─ client.generate_json(...)
  │     │
  │     ├─ endpoint_key IN _UNSUPPORTED_STRICT_MODE → use_strict=False
  │     ├─ response_format = {"type": "json_object"}  (skip strict entirely)
  │     ├─ POST /chat/completions → 200
  │     └─ return raw JSON string
  │
  ├─ _schema_validate(result, LORE_BLUEPRINT_SCHEMA) → as above
  └─ return result
```

### Worked example 4 — gemini path with schema

```
storyteller → JSONAgent.generate(message, json_schema=LORE_BLUEPRINT_SCHEMA)
  │
  ├─ provider = "gemini"
  ├─ json_schema is not None AND provider == "gemini":
  │     synthesize function = {"name": "response", "description": "...", "parameters": LORE_BLUEPRINT_SCHEMA}
  │     client.generate_json(message, function=function, additional_instructions=..., ...)
  │
  ├─ GeminiAIModel.generate_json executes its existing function-calling path:
  │     response = Gemini API call with function_declarations=[function]
  │     extract function_call.args → dict
  │
  ├─ _schema_validate(result, LORE_BLUEPRINT_SCHEMA) → defense-in-depth check on gemini's output
  └─ return result
```

## Error handling

| Condition | Behavior |
|---|---|
| `json_schema=None` (default) | All paths behave as today. Backward-compatible. |
| `jsonschema` import fails | n/a — it's a core dependency; package install guarantees presence. If it's missing somehow, `import jsonschema` at module load surfaces it. |
| OpenAI returns 400 matching `_STRICT_MODE_ERROR_MARKERS` | Cache + fall back to loose mode + retry once. No exception. |
| OpenAI returns 400 NOT matching the markers | Propagate as `requests.HTTPError`. Don't cache. (Real client bug — bad schema, bad model.) |
| OpenAI returns 500 / network failure | Existing `HPCUnreachableError` path. Not affected by this design. |
| OpenAI returns 200 + JSON that fails schema validation | `JSONAgent.generate` raises `GenerateJSONParseError(raw=...)`. Caller decides retry/recover. |
| Gemini's function-calling returns wrong shape | Same — central `_schema_validate` catches it; `GenerateJSONParseError` raised. |
| Local/mock with `json_schema=` | Local logs once + proceeds prompt-only. Mock returns mock JSON. Validation in `JSONAgent.generate` enforces the schema regardless. |
| Concurrent first-call against unsupported endpoint | Both threads pay one wasted strict attempt + fall back. `_UNSUPPORTED_STRICT_MODE.add()` is idempotent under GIL. No race condition. |

## Testing strategy

### Hermetic unit tests (`tests/unit/`)

**`test_unit_jsonagent_schema.py`** — `JSONAgent.generate` dispatch + centralized validation:
- json_schema=None → no validation, behavior unchanged
- json_schema passed + dict result conforms → returns result
- json_schema passed + dict result violates → raises `GenerateJSONParseError`
- gemini path translates json_schema → function dict with correct name/parameters
- openai path passes json_schema= through unchanged
- schema_name kwarg threads through to provider
- string result from provider is parsed before validation (existing path preserved)
- non-dict / non-string result raises `ValueError` (existing path preserved)

**`test_unit_openai_compat_structured_outputs.py`** — strict-mode + fallback + cache:
- json_schema=None → loose-mode payload unchanged (regression guard)
- json_schema=dict → strict-mode payload shape correct
- `schema_name="custom"` appears in payload
- First call to unsupported endpoint: 400 with "response_format" in body → cached + fallback succeeds
- First call to unsupported endpoint: 400 with "unsupported_parameter" → cached + fallback
- 400 with unrelated message (e.g., "model not found") → NOT cached + propagates HTTPError
- 422 with marker → cached + fallback (status 422 included in heuristic)
- Second call to same (model, endpoint): cache hit → skip strict, go directly to loose
- Different (model, endpoint) tuples tracked independently
- `_reset_unsupported_cache()` empties the set
- Successful strict-mode response does NOT populate cache

**`test_unit_local_model_json_schema.py`** — local provider:
- json_schema=None → behavior unchanged
- json_schema=dict → log marker fires once per (model, endpoint)
- Second call with same (model, endpoint) does NOT re-log
- Response generation still proceeds normally

**`test_unit_mock_model_json_schema.py`** — mock provider:
- json_schema=dict accepted without TypeError
- schema_name=string accepted without TypeError
- Other future kwargs absorbed via `**kwargs`

**`test_unit_json_utils_schema_validate.py`** — validation helper:
- schema=None → no-op
- schema=valid + payload conforms → returns silently
- schema=valid + payload violates → raises `GenerateJSONParseError` with `raw` populated
- raw="" default works without explicit pass

### Integration tests (`tests/integration/`)

None new. The HPC integration test stack is intentionally not extended for this work — strict-mode behavior against HPC will vary by deployment and is exactly the "discovery" problem the cache exists to solve. The hermetic units cover the contract; production observability (the log markers + job_meta) covers what units can't.

### Pre-existing test sanity

`test_unit_jsonagent_*.py` (if present) and the openai_compat existing tests must remain green — all new kwargs default to None and old call sites are unchanged.

## Rollout plan

1. **Land the library PR.** All new kwargs default to None / loose-mode behavior; existing call sites see no change.
2. **Release autonomous via `./scripts/release.sh`** — patch version bump.
3. **Storyteller side** (out of scope for this plan): operator runs `bump-autonomous.sh ${NEW_VERSION}` in `/opt/projects/storyteller-dev/`, then adopts the new kwarg one call site at a time. Recommended order:
   - Lore-builder Stage 1 first (the originating motivator) — smoke test
   - Lore-builder Stage 2 second
   - Other ~9 generators wrapped in storyteller's PR #6 / PR #4 — at storyteller's pace, one per PR
4. **Observability during adoption:** operator watches for `[STRUCTURED-OUTPUTS-UNAVAILABLE]` log markers across the storyteller deployment to learn which (model, endpoint) combos lack support. This informs whether to keep the prompt-restructuring belt-and-suspenders or eventually retire it.

Rollback (library side): revert the PR. Storyteller's existing prompt-restructuring fix continues to work; behavior reverts to today. No data migration.

## Necessary follow-ups

Not in scope for v1, but tracked here so they don't get lost:

1. **Storyteller adoption per call site.** ~11 generators. Schema design for each is a separate decision. Tracked in the storyteller tree.
2. **Silent-ignore detection.** If storyteller adoption surfaces cases where the server returns 200 + non-conforming JSON (validation catches it but the cache doesn't), add a secondary detection mechanism: cache the endpoint after N consecutive validation failures with strict mode "enabled" (a heuristic — N=3 likely).
3. **OpenAI direct-API support matrix verification.** Spec assumes OpenAI direct, Azure OpenAI, recent vLLM all work. Verify against the real endpoints storyteller uses (HPC primarily; OpenAI direct as backup if configured).

## Optional future work

Lower-priority, not committed:

- **Per-call validation override** — `validate=False` kwarg to skip client-side validation for performance-critical paths that don't need it. Probably YAGNI; validation is cheap.
- **Schema-driven retry** — when validation fails, re-prompt with the validation error as additional context. Could improve recovery on weak models. Risk: amplifies cost on persistent failures.
- **`_reset_unsupported_cache()` as a public maintenance API** — currently treated as a test helper + manual operator override. If operators need it routinely, promote to a documented API.
- **Schema registry** — a `autonomous.ai.schemas` module that holds reusable schema fragments (common storyteller types). Out of scope; better lived in the storyteller tree.
