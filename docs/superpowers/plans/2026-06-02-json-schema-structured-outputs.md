# JSON Schema / Structured Outputs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional `json_schema=` kwarg to `JSONAgent.generate` and provider `generate_json` methods, enabling OpenAI strict-mode structured outputs (with conservative fallback for non-supporting endpoints), gemini function-call translation, and unconditional client-side schema validation.

**Architecture:** Three concerns split across modules — OpenAI strict-mode + capability-discovery negative cache in `openai_compat.py`; client-side validation helper in `_json_utils.py`; per-provider dispatch + centralized validation in `JSONAgent.generate`. `jsonschema>=4.0` becomes a core dependency so the validation safety net is unconditionally available. Backward-compatible: existing call sites unaffected when `json_schema=None` (the default).

**Tech Stack:** Python 3.12+, `jsonschema>=4.0` (NEW core dep), `requests` (already required), `pytest`. Cross-provider compatibility with `GeminiAIModel`, `OpenAIClient`, `LocalAIModel`, `MockAIModel`.

**Spec:** `docs/superpowers/specs/2026-06-02-json-schema-structured-outputs-design.md`
**Tracked in:** `Sallenmoore/storyteller#12`

---

## File Structure

**Create:**
- `tests/unit/test_unit_json_utils_schema_validate.py` — `_schema_validate` helper coverage
- `tests/unit/test_unit_mock_model_json_schema.py` — mock kwarg absorption
- `tests/unit/test_unit_local_model_json_schema.py` — local provider log marker
- `tests/unit/test_unit_openai_compat_structured_outputs.py` — strict mode + fallback + cache (extended across Tasks 5–8)
- `tests/unit/test_unit_jsonagent_schema.py` — JSONAgent dispatch + centralized validation (extended across Tasks 9–11)

**Modify:**
- `pyproject.toml` — add `jsonschema>=4.0` to `[project].dependencies`
- `src/autonomous/ai/_json_utils.py` — add `_schema_validate` helper
- `src/autonomous/ai/models/mock_model.py:32` — accept `**kwargs` in `generate_json`
- `src/autonomous/ai/models/local_model.py:99` — accept `json_schema=None, schema_name="response"` kwargs; module-level log-once set
- `src/autonomous/ai/models/openai_compat.py` — module-level negative cache + helpers; `generate_json` strict-mode payload + fallback + cache short-circuit
- `src/autonomous/ai/jsonagent.py:21` — new `json_schema`/`schema_name` kwargs; per-provider dispatch (gemini translation); centralized `_schema_validate` call
- `MIGRATIONS.md` — new entry documenting the API addition + new core dep

---

## Task 1: Add `jsonschema` to core dependencies

**Files:**
- Modify: `pyproject.toml`
- Test: `tests/unit/test_unit_jsonschema_dependency.py` (new — minimal smoke check)

`jsonschema>=4.0` goes in core deps (not `[ai]` extra) per the spec — so the validation safety net is unconditionally available for every consumer that opts in via `json_schema=`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_unit_jsonschema_dependency.py`:

```python
"""jsonschema must be importable as a core dependency (not [ai] extra).
The validation safety net in JSONAgent.generate relies on this being
available even when consumers haven't installed [ai]."""


def test_jsonschema_importable():
    import jsonschema  # noqa: F401
    # Sanity-check the Draft 2020-12 validator path used by _schema_validate.
    assert callable(jsonschema.validate)
```

- [ ] **Step 2: Run to verify it passes (jsonschema may already be available transitively)**

Run: `pytest tests/unit/test_unit_jsonschema_dependency.py -v`

If PASS already (transitive dep): proceed to Step 3 anyway — the pyproject entry pins it.
If FAIL with `ModuleNotFoundError: No module named 'jsonschema'`: proceed to Step 3.

- [ ] **Step 3: Add `jsonschema>=4.0` to core deps**

In `pyproject.toml`, find the `[project].dependencies` list (NOT the `[project.optional-dependencies].ai` list). Append `"jsonschema>=4.0",` to it. Maintain alphabetical order within the list if present.

Example shape (adjust to match actual existing entries):

```toml
[project]
dependencies = [
    "Pillow>=10.0",
    "jsonschema>=4.0",        # NEW
    "PyMongo>=4.0",
    "python-dotenv>=1.0",
    "requests>=2.31",
    ...
]
```

- [ ] **Step 4: Install in current venv + verify**

Run:
```bash
pip install -e . && pytest tests/unit/test_unit_jsonschema_dependency.py -v
```
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/unit/test_unit_jsonschema_dependency.py
git commit -m "chore(deps): add jsonschema to core dependencies for structured-outputs validation"
```

---

## Task 2: `_schema_validate` helper in `_json_utils`

**Files:**
- Modify: `src/autonomous/ai/_json_utils.py`
- Test: `tests/unit/test_unit_json_utils_schema_validate.py` (new)

Pure function. Raises `GenerateJSONParseError` on validation mismatch with `raw` populated for diagnostics. No-op when schema is None.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_unit_json_utils_schema_validate.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_unit_json_utils_schema_validate.py -v`
Expected: FAIL — `_schema_validate` not yet defined (ImportError).

- [ ] **Step 3: Implement**

Read `src/autonomous/ai/_json_utils.py` to find the current contents (it already contains `clean_json_response` per the spec). Append the new helper:

```python
import jsonschema

from autonomous.ai.exceptions import GenerateJSONParseError


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
```

If `_json_utils.py` doesn't already import `from autonomous.ai.exceptions import ...`, this adds it. If imports are organized at top, add there; otherwise place near the function. Match the file's existing import style.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/unit/test_unit_json_utils_schema_validate.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/_json_utils.py tests/unit/test_unit_json_utils_schema_validate.py
git commit -m "feat(ai): _schema_validate helper for json-schema validation"
```

---

## Task 3: `MockAIModel.generate_json` absorbs `**kwargs`

**Files:**
- Modify: `src/autonomous/ai/models/mock_model.py:32`
- Test: `tests/unit/test_unit_mock_model_json_schema.py` (new)

Mock must accept `json_schema` and `schema_name` (and any future kwargs) without `TypeError` so JSONAgent dispatch tests using `provider="mock"` don't crash.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_unit_mock_model_json_schema.py`:

```python
"""MockAIModel.generate_json must accept the new json_schema / schema_name
kwargs (and any future ones) without TypeError, so JSONAgent dispatch
tests using provider='mock' don't crash. The mock ignores the kwargs by
design — schema-aware tests must construct mock data that conforms."""

from autonomous.ai.models.mock_model import MockAIModel


def _mock():
    return MockAIModel.__new__(MockAIModel)


def test_generate_json_accepts_json_schema_kwarg():
    out = MockAIModel.generate_json(
        _mock(), "prompt", json_schema={"type": "object"}
    )
    assert out is not None


def test_generate_json_accepts_schema_name_kwarg():
    out = MockAIModel.generate_json(
        _mock(), "prompt", schema_name="my_response"
    )
    assert out is not None


def test_generate_json_accepts_both_new_kwargs():
    out = MockAIModel.generate_json(
        _mock(),
        "prompt",
        json_schema={"type": "object"},
        schema_name="my_response",
    )
    assert out is not None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_unit_mock_model_json_schema.py -v`
Expected: FAIL — `TypeError: generate_json() got an unexpected keyword argument 'json_schema'`.

- [ ] **Step 3: Implement**

In `src/autonomous/ai/models/mock_model.py`, find `generate_json` (around line 32). Add `**kwargs` as the final parameter:

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

(Preserve the existing log call and return value verbatim. Only the signature changes.)

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/unit/test_unit_mock_model_json_schema.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/models/mock_model.py tests/unit/test_unit_mock_model_json_schema.py
git commit -m "test(mock): MockAIModel.generate_json absorbs json_schema/schema_name kwargs"
```

---

## Task 4: `LocalAIModel.generate_json` accepts `json_schema` + logs once

**Files:**
- Modify: `src/autonomous/ai/models/local_model.py:99` (signature + module-level set)
- Test: `tests/unit/test_unit_local_model_json_schema.py` (new)

Local has no equivalent of OpenAI strict mode. Accept the kwarg, log `[STRUCTURED-OUTPUTS-UNAVAILABLE]` once per (model, endpoint), then proceed via the existing prompt-only path.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_unit_local_model_json_schema.py`:

```python
"""LocalAIModel.generate_json accepts json_schema/schema_name but cannot
enforce strict mode (no Ollama equivalent). Logs once per (model,
endpoint) so operators know they're on the prompt-only path, then
proceeds normally.

These tests verify ONLY the kwarg absorption + log behavior. The full
generate_json path requires a real Ollama server, so we don't exercise it
here — that's covered by the integration tier."""

from unittest.mock import MagicMock, patch

from autonomous.ai.models import local_model
from autonomous.ai.models.local_model import LocalAIModel


def _local():
    """Bare LocalAIModel without DB persistence."""
    inst = LocalAIModel.__new__(LocalAIModel)
    return inst


class TestJSONSchemaAbsorption:
    def setup_method(self):
        # Each test gets a fresh log-once cache
        local_model._STRUCTURED_OUTPUTS_LOGGED.clear()

    def test_signature_accepts_json_schema(self, monkeypatch):
        # Patch the network call so the test never reaches Ollama.
        monkeypatch.setattr(
            LocalAIModel,
            "generate_json",
            LocalAIModel.generate_json,  # ensure the method is bound
        )
        # Inspect the signature directly — no network call needed.
        import inspect
        sig = inspect.signature(LocalAIModel.generate_json)
        assert "json_schema" in sig.parameters
        assert "schema_name" in sig.parameters
        assert sig.parameters["json_schema"].default is None
        assert sig.parameters["schema_name"].default == "response"

    def test_log_fires_once_per_model_endpoint(self, monkeypatch, caplog):
        local = _local()
        local._text_model = "test-model"
        local._ollama_url = "http://test-host:11434"

        # Stub the actual network call so we don't hit Ollama.
        # We're only testing the log behavior; the rest of generate_json
        # can stay un-executed via a short-circuit.
        captured_logs = []

        def fake_log(msg, *args, **kwargs):
            captured_logs.append(str(msg))

        monkeypatch.setattr(local_model, "log", fake_log)

        # Short-circuit the rest of generate_json by raising AFTER the
        # log block (we only care about the log behavior here).
        def raise_after_log(*a, **kw):
            raise RuntimeError("expected: short-circuit after log")

        monkeypatch.setattr(local_model._SESSION, "post", raise_after_log)

        # First call: should log the unavailable marker.
        try:
            LocalAIModel.generate_json(
                local, "prompt", json_schema={"type": "object"}
            )
        except RuntimeError:
            pass

        unavailable_logs = [
            m for m in captured_logs if "STRUCTURED-OUTPUTS-UNAVAILABLE" in m
        ]
        assert len(unavailable_logs) == 1, (
            f"Expected 1 unavailable marker, got: {unavailable_logs}"
        )

        # Second call: should NOT log again (same model+endpoint).
        try:
            LocalAIModel.generate_json(
                local, "prompt2", json_schema={"type": "string"}
            )
        except RuntimeError:
            pass

        unavailable_logs = [
            m for m in captured_logs if "STRUCTURED-OUTPUTS-UNAVAILABLE" in m
        ]
        assert len(unavailable_logs) == 1, (
            f"Expected still 1 unavailable marker after second call, "
            f"got: {unavailable_logs}"
        )

    def test_log_fires_for_different_model_endpoint_combos(self, monkeypatch):
        local = _local()
        local._text_model = "model-a"
        local._ollama_url = "http://host-a:11434"

        captured_logs = []
        monkeypatch.setattr(
            local_model, "log",
            lambda msg, *a, **kw: captured_logs.append(str(msg)),
        )
        monkeypatch.setattr(
            local_model._SESSION, "post",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("stop"))
        )

        try:
            LocalAIModel.generate_json(local, "p", json_schema={"type": "object"})
        except RuntimeError:
            pass

        # Change model+endpoint — new combo should re-log.
        local._text_model = "model-b"
        try:
            LocalAIModel.generate_json(local, "p", json_schema={"type": "object"})
        except RuntimeError:
            pass

        unavailable_logs = [
            m for m in captured_logs if "STRUCTURED-OUTPUTS-UNAVAILABLE" in m
        ]
        assert len(unavailable_logs) == 2

    def test_no_log_when_json_schema_is_none(self, monkeypatch):
        local = _local()
        local._text_model = "test-model"
        local._ollama_url = "http://test-host:11434"

        captured_logs = []
        monkeypatch.setattr(
            local_model, "log",
            lambda msg, *a, **kw: captured_logs.append(str(msg)),
        )
        monkeypatch.setattr(
            local_model._SESSION, "post",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("stop"))
        )

        try:
            LocalAIModel.generate_json(local, "prompt")  # no json_schema
        except RuntimeError:
            pass

        unavailable_logs = [
            m for m in captured_logs if "STRUCTURED-OUTPUTS-UNAVAILABLE" in m
        ]
        assert len(unavailable_logs) == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_unit_local_model_json_schema.py -v`
Expected: FAIL — `_STRUCTURED_OUTPUTS_LOGGED` not defined, signature doesn't include the new kwargs.

- [ ] **Step 3: Implement**

Open `src/autonomous/ai/models/local_model.py`. Find the existing module-level imports block (top of file). Add the new module-level set NEAR THE TOP, alongside `_SESSION`:

```python
# Module-level cache of (model, endpoint) combos we've already logged
# the "no structured outputs support" marker for. Avoids log spam on
# every JSON call. Cleared by process restart only.
_STRUCTURED_OUTPUTS_LOGGED: set[tuple[str, str]] = set()
```

Then update `generate_json` (around line 99) to add the new kwargs + the log block. Find the existing signature:

```python
    def generate_json(
        self, message, system_prompt=None, uri="", context=None, temperature=0.7, evaluation=False
    ):
```

Replace with:

```python
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
        # Client-side validation in JSONAgent.generate provides the safety net.
        if json_schema is not None:
            key = (self._text_model, self._ollama_url)
            if key not in _STRUCTURED_OUTPUTS_LOGGED:
                _STRUCTURED_OUTPUTS_LOGGED.add(key)
                log(
                    f"[STRUCTURED-OUTPUTS-UNAVAILABLE] LocalAIModel does not "
                    f"support strict-mode schema enforcement. "
                    f"model={self._text_model} endpoint={self._ollama_url}. "
                    f"Falling back to prompt-only shape guidance + "
                    f"client-side validation.",
                    _print=True,
                )

        # ... rest of existing method body unchanged ...
```

DO NOT inject `json_schema` into the prompt. The existing system-prompt logic stays as-is.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/unit/test_unit_local_model_json_schema.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/models/local_model.py tests/unit/test_unit_local_model_json_schema.py
git commit -m "feat(local): LocalAIModel.generate_json accepts json_schema, logs unavailable once"
```

---

## Task 5: OpenAIClient capability-discovery helpers

**Files:**
- Modify: `src/autonomous/ai/models/openai_compat.py` (module-level additions)
- Test: `tests/unit/test_unit_openai_compat_structured_outputs.py` (new, extended in Tasks 6-8)

Add the negative cache, the error-marker tuple, and two pure helpers: `_looks_like_unsupported_strict_mode` and `_reset_unsupported_cache`. No `generate_json` changes yet — those land in Tasks 6-8.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_unit_openai_compat_structured_outputs.py`:

```python
"""OpenAIClient strict-mode structured-outputs coverage.

Test classes (across Tasks 5-8):
- TestUnsupportedDetectionHelpers (this task): heuristic + cache reset
- TestStrictModePayload (Task 6): generate_json builds strict response_format
- TestStrictModeFallback (Task 7): conservative 400 → cache + retry loose
- TestStrictModeCacheShortCircuit (Task 8): second call skips strict"""

import pytest

from autonomous.ai.models import openai_compat
from autonomous.ai.models.openai_compat import (
    _UNSUPPORTED_STRICT_MODE,
    _looks_like_unsupported_strict_mode,
    _reset_unsupported_cache,
)


class TestUnsupportedDetectionHelpers:
    """Pure-function helpers — no network, no instance state."""

    def setup_method(self):
        _reset_unsupported_cache()

    @pytest.mark.parametrize(
        "status,body,expected",
        [
            # Conservative: only the explicit markers trigger True.
            (400, "Invalid response_format type 'json_schema'", True),
            (400, "{'error':{'code':'unsupported_parameter'}}", True),
            (400, "Structured output not implemented", True),
            (400, "json_schema not supported", True),
            (422, "json_schema validation error", True),  # 422 also accepted

            # Bare 400 with unrelated error: False (real client bug).
            (400, "Model not found", False),
            (400, "Bad request", False),
            (400, "Authentication required", False),

            # Non-4xx: always False (transport / success).
            (200, "json_schema mentioned but 200 status", False),
            (500, "json_schema unsupported", False),
            (503, "Service unavailable", False),
        ],
    )
    def test_heuristic_matches_only_strict_mode_signals(
        self, status, body, expected
    ):
        assert _looks_like_unsupported_strict_mode(status, body) is expected

    def test_reset_empties_cache(self):
        _UNSUPPORTED_STRICT_MODE.add(("model-x", "http://endpoint-y"))
        assert len(_UNSUPPORTED_STRICT_MODE) == 1
        _reset_unsupported_cache()
        assert len(_UNSUPPORTED_STRICT_MODE) == 0

    def test_cache_uses_tuple_keys(self):
        # Verifies the cache discriminates on (model, endpoint) — not just one.
        _UNSUPPORTED_STRICT_MODE.add(("model-a", "http://host-1"))
        _UNSUPPORTED_STRICT_MODE.add(("model-a", "http://host-2"))
        _UNSUPPORTED_STRICT_MODE.add(("model-b", "http://host-1"))
        assert len(_UNSUPPORTED_STRICT_MODE) == 3
        _reset_unsupported_cache()
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_unit_openai_compat_structured_outputs.py -v`
Expected: FAIL — `ImportError: cannot import name '_UNSUPPORTED_STRICT_MODE'`.

- [ ] **Step 3: Implement**

Open `src/autonomous/ai/models/openai_compat.py`. Add the new module-level constants + helpers near the existing `_SESSION` and `_TRANSPORT_FAILURE_CODES` declarations (top of module, after imports, before the `HPCUnreachableError` class):

```python
# Module-level negative cache: (model, base_url) tuples known to NOT
# support strict-mode response_format. Populated on first conservative
# 400 detection. Cleared by _reset_unsupported_cache() (tests + manual
# operator override). Process-lifetime granularity is appropriate —
# servers gain strict-mode support via deploys, deploys typically
# accompany worker restarts.
_UNSUPPORTED_STRICT_MODE: set[tuple[str, str]] = set()

# Substrings that indicate a 4xx response was specifically about
# strict-mode unsupported-ness (rather than a real client bug like
# bad schema or bad model name). Conservative — only fall back on
# explicit signals to avoid masking real errors.
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
    e.g. bad schema or bad model name) is intentionally NOT flagged —
    silently retrying in loose mode would mask the real error.

    Accepts 400 and 422 (some servers use 422 for validation rejections).
    """
    if status not in (400, 422):
        return False
    body_lower = body_text.lower()
    return any(m in body_lower for m in _STRICT_MODE_ERROR_MARKERS)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/unit/test_unit_openai_compat_structured_outputs.py::TestUnsupportedDetectionHelpers -v`
Expected: 13 passed (11 parametrized + 2 cache).

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/models/openai_compat.py tests/unit/test_unit_openai_compat_structured_outputs.py
git commit -m "feat(openai-compat): negative cache + heuristic for unsupported strict mode"
```

---

## Task 6: OpenAIClient `generate_json` builds strict-mode payload

**Files:**
- Modify: `src/autonomous/ai/models/openai_compat.py:199` (`generate_json` signature + payload)
- Test: `tests/unit/test_unit_openai_compat_structured_outputs.py` (extend)

Add the `json_schema=None, schema_name="response"` kwargs. When schema is set AND endpoint isn't in the negative cache, build strict-mode `response_format`. NO fallback yet (Task 7). NO cache short-circuit yet (Task 8).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_unit_openai_compat_structured_outputs.py`:

```python
class _FakeChatResponse:
    """Stand-in for the dict that _chat returns when given a payload."""


class TestStrictModePayload:
    """generate_json with json_schema= set builds the OpenAI strict-mode
    response_format payload. Without json_schema, the existing loose-mode
    payload is preserved (regression guard)."""

    SAMPLE_SCHEMA = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }

    def setup_method(self):
        _reset_unsupported_cache()

    def _client(self, monkeypatch, captured):
        """Build a bare OpenAIClient and stub _chat to capture the
        response_format that generate_json builds."""
        from autonomous.ai.models.openai_compat import OpenAIClient

        client = OpenAIClient.__new__(OpenAIClient)
        client._json_model = "test-model"
        client._base_url = "https://test-endpoint/api"
        client._api_key = "test-key"
        client.instructions = "Be a helpful AI."

        def fake_chat(model, system, user, response_format=None, temperature=0.7):
            captured["response_format"] = response_format
            captured["model"] = model
            return '{"value": "ok"}'

        monkeypatch.setattr(client, "_chat", fake_chat)
        return client

    def test_json_schema_none_uses_loose_mode(self, monkeypatch):
        """Regression guard: backward compatibility when json_schema not set."""
        captured = {}
        from autonomous.ai.models.openai_compat import OpenAIClient
        client = self._client(monkeypatch, captured)

        result = OpenAIClient.generate_json(client, "prompt")

        assert captured["response_format"] == {"type": "json_object"}
        assert result == {"value": "ok"}

    def test_json_schema_set_uses_strict_mode(self, monkeypatch):
        captured = {}
        from autonomous.ai.models.openai_compat import OpenAIClient
        client = self._client(monkeypatch, captured)

        OpenAIClient.generate_json(
            client, "prompt", json_schema=self.SAMPLE_SCHEMA
        )

        assert captured["response_format"] == {
            "type": "json_schema",
            "json_schema": {
                "name": "response",  # default schema_name
                "schema": self.SAMPLE_SCHEMA,
                "strict": True,
            },
        }

    def test_schema_name_kwarg_threads_through(self, monkeypatch):
        captured = {}
        from autonomous.ai.models.openai_compat import OpenAIClient
        client = self._client(monkeypatch, captured)

        OpenAIClient.generate_json(
            client,
            "prompt",
            json_schema=self.SAMPLE_SCHEMA,
            schema_name="party_reactions",
        )

        assert captured["response_format"]["json_schema"]["name"] == "party_reactions"
        assert captured["response_format"]["json_schema"]["strict"] is True
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_unit_openai_compat_structured_outputs.py::TestStrictModePayload -v`
Expected: FAIL — `generate_json` doesn't accept `json_schema` kwarg (TypeError).

- [ ] **Step 3: Implement**

In `src/autonomous/ai/models/openai_compat.py`, find `generate_json` (around line 199). Update the signature and the body. The current signature:

```python
    def generate_json(
        self, message, system_prompt=None, uri="", context=None, temperature=0.7, evaluation=False
    ):
```

Update to:

```python
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
```

Then, inside `generate_json`, find the existing block:

```python
        try:
            raw = self._chat(
                self._json_model,
                system,
                user,
                response_format={"type": "json_object"},
                temperature=temperature,
            )
        except (KeyError, IndexError, TypeError) as exc:
```

Replace with:

```python
        # Build the response_format payload. Strict mode when:
        #   - caller passed a schema
        #   - this (model, endpoint) is not in the negative cache
        # Otherwise loose mode (preserved existing behavior).
        endpoint_key = (self._json_model, self._base_url)
        use_strict = (
            json_schema is not None
            and endpoint_key not in _UNSUPPORTED_STRICT_MODE
        )
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
        except (KeyError, IndexError, TypeError) as exc:
```

Leave the rest of the method (empty-body check, JSON-parse) unchanged.

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_unit_openai_compat_structured_outputs.py -v`
Expected: 16 passed (13 helpers + 3 new payload tests).

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/models/openai_compat.py tests/unit/test_unit_openai_compat_structured_outputs.py
git commit -m "feat(openai-compat): generate_json builds strict-mode response_format"
```

---

## Task 7: OpenAIClient `generate_json` fallback on conservative 400

**Files:**
- Modify: `src/autonomous/ai/models/openai_compat.py` (extend `generate_json` try/except)
- Test: `tests/unit/test_unit_openai_compat_structured_outputs.py` (extend)

When `_chat` raises `requests.HTTPError` AND the response matches the unsupported-strict-mode heuristic, cache the endpoint and retry once with loose mode. Bare 400s (not matching the heuristic) propagate.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_unit_openai_compat_structured_outputs.py`:

```python
import requests


class _FakeHTTPError(requests.HTTPError):
    """HTTPError with a controllable response attached, mimicking what
    requests.Response.raise_for_status() produces."""

    def __init__(self, status, body):
        class _Resp:
            status_code = status
            text = body
        super().__init__(f"HTTP {status}")
        self.response = _Resp()


class TestStrictModeFallback:
    SAMPLE_SCHEMA = {
        "type": "object",
        "properties": {"v": {"type": "string"}},
        "required": ["v"],
    }

    def setup_method(self):
        _reset_unsupported_cache()

    def _client(self, monkeypatch, chat_side_effects):
        """Build a client whose _chat raises or returns per the side-effect list."""
        from autonomous.ai.models.openai_compat import OpenAIClient

        client = OpenAIClient.__new__(OpenAIClient)
        client._json_model = "fallback-model"
        client._base_url = "https://fallback-endpoint/api"
        client._api_key = "k"
        client.instructions = "Be a helpful AI."

        calls = {"count": 0, "response_formats": []}
        effects = list(chat_side_effects)

        def fake_chat(model, system, user, response_format=None, temperature=0.7):
            calls["count"] += 1
            calls["response_formats"].append(response_format)
            effect = effects.pop(0) if effects else None
            if isinstance(effect, Exception):
                raise effect
            return effect

        monkeypatch.setattr(client, "_chat", fake_chat)
        return client, calls

    def test_400_with_marker_falls_back_to_loose(self, monkeypatch):
        from autonomous.ai.models.openai_compat import OpenAIClient
        client, calls = self._client(
            monkeypatch,
            chat_side_effects=[
                _FakeHTTPError(400, "Invalid response_format type 'json_schema'"),
                '{"v": "ok"}',
            ],
        )

        result = OpenAIClient.generate_json(
            client, "prompt", json_schema=self.SAMPLE_SCHEMA
        )

        assert result == {"v": "ok"}
        assert calls["count"] == 2
        # First attempt was strict
        assert calls["response_formats"][0]["type"] == "json_schema"
        # Retry was loose
        assert calls["response_formats"][1] == {"type": "json_object"}
        # Endpoint cached
        assert (
            "fallback-model",
            "https://fallback-endpoint/api",
        ) in _UNSUPPORTED_STRICT_MODE

    def test_400_with_unsupported_parameter_marker_falls_back(self, monkeypatch):
        from autonomous.ai.models.openai_compat import OpenAIClient
        client, calls = self._client(
            monkeypatch,
            chat_side_effects=[
                _FakeHTTPError(
                    400,
                    '{"error":{"code":"unsupported_parameter","message":"x"}}',
                ),
                '{"v": "ok"}',
            ],
        )

        result = OpenAIClient.generate_json(
            client, "prompt", json_schema=self.SAMPLE_SCHEMA
        )

        assert result == {"v": "ok"}
        assert calls["count"] == 2

    def test_422_with_marker_falls_back(self, monkeypatch):
        from autonomous.ai.models.openai_compat import OpenAIClient
        client, calls = self._client(
            monkeypatch,
            chat_side_effects=[
                _FakeHTTPError(422, "json_schema validation error"),
                '{"v": "ok"}',
            ],
        )

        result = OpenAIClient.generate_json(
            client, "prompt", json_schema=self.SAMPLE_SCHEMA
        )
        assert result == {"v": "ok"}
        assert calls["count"] == 2

    def test_400_without_marker_propagates(self, monkeypatch):
        from autonomous.ai.models.openai_compat import OpenAIClient
        client, calls = self._client(
            monkeypatch,
            chat_side_effects=[
                _FakeHTTPError(400, "Model 'fallback-model' not found"),
            ],
        )

        with pytest.raises(requests.HTTPError, match="HTTP 400"):
            OpenAIClient.generate_json(
                client, "prompt", json_schema=self.SAMPLE_SCHEMA
            )

        # Only the strict attempt was made; no fallback.
        assert calls["count"] == 1
        # NOT cached — this is a real client bug, not unsupported strict mode.
        assert (
            "fallback-model",
            "https://fallback-endpoint/api",
        ) not in _UNSUPPORTED_STRICT_MODE

    def test_no_fallback_when_json_schema_none(self, monkeypatch):
        """If we didn't ask for strict mode in the first place, an HTTPError
        from _chat is a real error, not an unsupported-mode signal."""
        from autonomous.ai.models.openai_compat import OpenAIClient
        client, calls = self._client(
            monkeypatch,
            chat_side_effects=[
                _FakeHTTPError(400, "json_schema mentioned somehow"),
            ],
        )

        with pytest.raises(requests.HTTPError):
            OpenAIClient.generate_json(client, "prompt")  # no json_schema

        assert calls["count"] == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_unit_openai_compat_structured_outputs.py::TestStrictModeFallback -v`
Expected: FAIL — no try/except for HTTPError; first test crashes with the raw HTTPError instead of recovering.

- [ ] **Step 3: Implement**

In `src/autonomous/ai/models/openai_compat.py`, find the existing `try/except` in `generate_json` (the one Task 6 just touched). The current shape (after Task 6):

```python
        try:
            raw = self._chat(
                self._json_model,
                system,
                user,
                response_format=response_format,
                temperature=temperature,
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise GenerateJSONEmptyResponseError(...)
```

Replace with this expanded version that adds an HTTPError-catching branch BEFORE the existing one:

```python
        try:
            raw = self._chat(
                self._json_model,
                system,
                user,
                response_format=response_format,
                temperature=temperature,
            )
        except requests.HTTPError as exc:
            # Detect "this endpoint doesn't support strict mode" specifically
            # and fall back to loose. Bare 4xx (real client bug) propagates.
            resp = exc.response
            should_fallback = (
                use_strict
                and resp is not None
                and _looks_like_unsupported_strict_mode(resp.status_code, resp.text)
            )
            if not should_fallback:
                raise
            _UNSUPPORTED_STRICT_MODE.add(endpoint_key)
            log(
                f"[STRUCTURED-OUTPUTS-UNAVAILABLE] First detection: "
                f"model={self._json_model} endpoint={self._base_url} "
                f"status={resp.status_code} body_excerpt={resp.text[:200]!r} "
                f"(cached for this process)",
                _print=True,
            )
            # Retry once with loose mode.
            try:
                raw = self._chat(
                    self._json_model,
                    system,
                    user,
                    response_format={"type": "json_object"},
                    temperature=temperature,
                )
            except (KeyError, IndexError, TypeError) as inner_exc:
                raise GenerateJSONEmptyResponseError(
                    f"HPC chat endpoint returned a malformed body after fallback: {inner_exc}"
                ) from inner_exc
        except (KeyError, IndexError, TypeError) as exc:
            raise GenerateJSONEmptyResponseError(
                f"HPC chat endpoint returned a malformed body: {exc}"
            ) from exc
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_unit_openai_compat_structured_outputs.py -v`
Expected: 21 passed (16 prior + 5 new fallback tests).

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/models/openai_compat.py tests/unit/test_unit_openai_compat_structured_outputs.py
git commit -m "feat(openai-compat): generate_json falls back to loose mode on unsupported-strict 400"
```

---

## Task 8: OpenAIClient `generate_json` cache short-circuit

**Files:**
- Test: `tests/unit/test_unit_openai_compat_structured_outputs.py` (extend)

The implementation from Task 6 already gates `use_strict` on the cache, so this task is **test-only** — it covers the cache hit path that Tasks 6+7 made possible.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_unit_openai_compat_structured_outputs.py`:

```python
class TestStrictModeCacheShortCircuit:
    SAMPLE_SCHEMA = {
        "type": "object",
        "properties": {"v": {"type": "string"}},
        "required": ["v"],
    }

    def setup_method(self):
        _reset_unsupported_cache()

    def _client(self, monkeypatch, captured):
        from autonomous.ai.models.openai_compat import OpenAIClient

        client = OpenAIClient.__new__(OpenAIClient)
        client._json_model = "cache-model"
        client._base_url = "https://cache-endpoint/api"
        client._api_key = "k"
        client.instructions = "Be a helpful AI."

        def fake_chat(model, system, user, response_format=None, temperature=0.7):
            captured["response_formats"].append(response_format)
            return '{"v": "cached"}'

        monkeypatch.setattr(client, "_chat", fake_chat)
        captured.setdefault("response_formats", [])
        return client

    def test_pre_populated_cache_skips_strict(self, monkeypatch):
        from autonomous.ai.models.openai_compat import OpenAIClient
        # Simulate "we already discovered this combo doesn't support strict."
        _UNSUPPORTED_STRICT_MODE.add(("cache-model", "https://cache-endpoint/api"))

        captured = {}
        client = self._client(monkeypatch, captured)

        OpenAIClient.generate_json(
            client, "prompt", json_schema=self.SAMPLE_SCHEMA
        )

        # Only ONE call — went directly to loose mode, no strict attempt.
        assert len(captured["response_formats"]) == 1
        assert captured["response_formats"][0] == {"type": "json_object"}

    def test_different_endpoint_still_tries_strict(self, monkeypatch):
        """Cache is per (model, endpoint). A different endpoint isn't
        short-circuited just because some other combo failed."""
        from autonomous.ai.models.openai_compat import OpenAIClient
        _UNSUPPORTED_STRICT_MODE.add(("other-model", "https://other-endpoint/api"))

        captured = {}
        client = self._client(monkeypatch, captured)
        # Our client is ("cache-model", "https://cache-endpoint/api")

        OpenAIClient.generate_json(
            client, "prompt", json_schema=self.SAMPLE_SCHEMA
        )

        assert len(captured["response_formats"]) == 1
        assert captured["response_formats"][0]["type"] == "json_schema"

    def test_cache_persists_across_generate_json_calls(self, monkeypatch):
        """Once cached, every subsequent call to the same combo
        short-circuits — no per-call wasted attempts."""
        from autonomous.ai.models.openai_compat import OpenAIClient
        captured = {"response_formats": []}
        client = self._client(monkeypatch, captured)

        # Pre-populate as if a previous fallback discovered unsupported-ness.
        _UNSUPPORTED_STRICT_MODE.add(("cache-model", "https://cache-endpoint/api"))

        for _ in range(3):
            OpenAIClient.generate_json(
                client, "prompt", json_schema=self.SAMPLE_SCHEMA
            )

        assert len(captured["response_formats"]) == 3
        for rf in captured["response_formats"]:
            assert rf == {"type": "json_object"}
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/unit/test_unit_openai_compat_structured_outputs.py::TestStrictModeCacheShortCircuit -v`
Expected: 3 passed. (Implementation from Task 6 already supports this; the cache check is `endpoint_key not in _UNSUPPORTED_STRICT_MODE`.)

If tests fail, the bug is in Task 6's implementation — `use_strict` should be `json_schema is not None and endpoint_key not in _UNSUPPORTED_STRICT_MODE`. Fix that there, don't add new code in this task.

Also run the full file: `pytest tests/unit/test_unit_openai_compat_structured_outputs.py -v`
Expected: 24 passed (21 prior + 3 new).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_unit_openai_compat_structured_outputs.py
git commit -m "test(openai-compat): cache short-circuits strict attempt for known-unsupported endpoints"
```

---

## Task 9: `JSONAgent.generate` dispatch for openai/local/mock paths

**Files:**
- Modify: `src/autonomous/ai/jsonagent.py:21`
- Test: `tests/unit/test_unit_jsonagent_schema.py` (new, extended in Tasks 10-11)

Add `json_schema=None, schema_name="response"` to `JSONAgent.generate`. For openai/local/mock providers, pass kwargs through directly. Gemini's path is Task 10 (different signature). Centralized validation is Task 11.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_unit_jsonagent_schema.py`:

```python
"""JSONAgent.generate dispatch + centralized validation tests.

Covers (across Tasks 9-11):
- Task 9: openai/local/mock providers get json_schema= passed through
- Task 10: gemini provider gets json_schema= translated to function= dict
- Task 11: every provider's response runs through _schema_validate"""

import pytest

from autonomous.ai.jsonagent import JSONAgent


SAMPLE_SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
    "additionalProperties": False,
}


def _agent():
    """Bare JSONAgent that bypasses AutoModel persistence."""
    agent = JSONAgent.__new__(JSONAgent)
    agent._data = {}
    agent._initialised = False
    agent._data["provider"] = "openai"   # default for these dispatch tests
    return agent


class _StubProviderClient:
    """Captures the call signature; returns deterministic JSON."""

    def __init__(self, return_value):
        self.return_value = return_value
        self.calls = []

    def generate_json(self, message, **kwargs):
        self.calls.append({"message": message, **kwargs})
        return self.return_value


def _patched_agent(monkeypatch, provider, client):
    agent = _agent()
    agent._data["provider"] = provider
    agent._meta_log = []
    monkeypatch.setattr(agent, "get_client", lambda _p=None: client)
    monkeypatch.setattr(
        agent, "add_to_job_meta",
        lambda k, v: agent._meta_log.append((k, v)),
    )
    monkeypatch.delenv("JSON_AI_AGENT", raising=False)
    return agent


class TestDispatchOpenAI:
    def test_json_schema_passed_to_openai_provider(self, monkeypatch):
        client = _StubProviderClient({"value": "x"})
        agent = _patched_agent(monkeypatch, "openai", client)

        JSONAgent.generate(
            agent, "prompt", json_schema=SAMPLE_SCHEMA, schema_name="my_resp"
        )

        assert len(client.calls) == 1
        assert client.calls[0]["json_schema"] == SAMPLE_SCHEMA
        assert client.calls[0]["schema_name"] == "my_resp"

    def test_default_schema_name_is_response(self, monkeypatch):
        client = _StubProviderClient({"value": "x"})
        agent = _patched_agent(monkeypatch, "openai", client)

        JSONAgent.generate(agent, "prompt", json_schema=SAMPLE_SCHEMA)

        assert client.calls[0]["schema_name"] == "response"

    def test_none_schema_passes_none(self, monkeypatch):
        """Backward compat: when no schema, json_schema=None reaches provider."""
        client = _StubProviderClient({"value": "x"})
        agent = _patched_agent(monkeypatch, "openai", client)

        JSONAgent.generate(agent, "prompt")

        assert client.calls[0]["json_schema"] is None


class TestDispatchLocal:
    def test_json_schema_passed_to_local_provider(self, monkeypatch):
        client = _StubProviderClient({"value": "x"})
        agent = _patched_agent(monkeypatch, "local", client)

        JSONAgent.generate(agent, "prompt", json_schema=SAMPLE_SCHEMA)

        assert client.calls[0]["json_schema"] == SAMPLE_SCHEMA


class TestDispatchMock:
    def test_json_schema_passed_to_mock_provider(self, monkeypatch):
        # Mock returns deterministic dict regardless of schema.
        client = _StubProviderClient({"value": "ok"})
        agent = _patched_agent(monkeypatch, "mock", client)

        result = JSONAgent.generate(
            agent, "prompt", json_schema=SAMPLE_SCHEMA
        )

        # Mock client was called with schema (absorption tested in Task 3)
        assert client.calls[0]["json_schema"] == SAMPLE_SCHEMA
        # Result returns the mock's value
        assert result == {"value": "ok"}


class TestStringResponseParsing:
    """Existing behavior preserved: provider returning a JSON string
    gets parsed before validation/return."""

    def test_string_response_parsed(self, monkeypatch):
        client = _StubProviderClient('{"value": "ok"}')   # provider returns str
        agent = _patched_agent(monkeypatch, "openai", client)

        result = JSONAgent.generate(agent, "prompt")

        assert result == {"value": "ok"}

    def test_invalid_string_raises_value_error(self, monkeypatch):
        client = _StubProviderClient("not valid json")
        agent = _patched_agent(monkeypatch, "openai", client)

        with pytest.raises(ValueError, match="Invalid JSON response"):
            JSONAgent.generate(agent, "prompt")

    def test_non_dict_non_string_raises_value_error(self, monkeypatch):
        client = _StubProviderClient(42)   # provider returns int
        agent = _patched_agent(monkeypatch, "openai", client)

        with pytest.raises(ValueError, match="Invalid JSON response"):
            JSONAgent.generate(agent, "prompt")
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_unit_jsonagent_schema.py -v`
Expected: FAIL — `JSONAgent.generate` doesn't accept `json_schema`/`schema_name`; for the existing-behavior tests, may pass already.

- [ ] **Step 3: Implement**

Replace `JSONAgent.generate` in `src/autonomous/ai/jsonagent.py` with:

```python
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

        # Per-provider dispatch. Gemini's branch lands in Task 10 — for now,
        # all providers receive json_schema= as a passthrough kwarg.
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

        # Centralized client-side validation lands in Task 11.

        self.add_to_job_meta("Last JSON", result)
        return result
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_unit_jsonagent_schema.py -v`
Expected: 8 passed (3 openai + 1 local + 1 mock + 3 string-parsing).

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/jsonagent.py tests/unit/test_unit_jsonagent_schema.py
git commit -m "feat(jsonagent): dispatch json_schema kwarg to openai/local/mock providers"
```

---

## Task 10: `JSONAgent.generate` gemini translation

**Files:**
- Modify: `src/autonomous/ai/jsonagent.py` (extend `generate` with gemini branch)
- Test: `tests/unit/test_unit_jsonagent_schema.py` (extend)

Gemini's `generate_json(message, function, ...)` takes a `function` dict whose `parameters` field IS a JSON schema. For the gemini provider, synthesize that dict from `json_schema=` and pass via the existing `function=` parameter.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_unit_jsonagent_schema.py`:

```python
class _GeminiStubClient:
    """Captures gemini's distinct call signature: generate_json(message, function, ...)"""

    def __init__(self, return_value):
        self.return_value = return_value
        self.calls = []

    def generate_json(self, message, function=None, **kwargs):
        self.calls.append({"message": message, "function": function, **kwargs})
        return self.return_value


class TestDispatchGeminiTranslation:
    def test_json_schema_synthesizes_function_dict(self, monkeypatch):
        client = _GeminiStubClient({"value": "ok"})
        agent = _patched_agent(monkeypatch, "gemini", client)

        JSONAgent.generate(
            agent, "prompt",
            json_schema=SAMPLE_SCHEMA,
            schema_name="lore_blueprint",
        )

        assert len(client.calls) == 1
        call = client.calls[0]
        # Function dict synthesized with the schema as parameters.
        assert call["function"] == {
            "name": "lore_blueprint",
            "description": "Structured response shape.",
            "parameters": SAMPLE_SCHEMA,
        }
        # Should NOT have json_schema= or schema_name= leaked through
        # to gemini (it doesn't accept them).
        assert "json_schema" not in call
        assert "schema_name" not in call

    def test_default_schema_name_used_in_function_dict(self, monkeypatch):
        client = _GeminiStubClient({"value": "ok"})
        agent = _patched_agent(monkeypatch, "gemini", client)

        JSONAgent.generate(agent, "prompt", json_schema=SAMPLE_SCHEMA)

        assert client.calls[0]["function"]["name"] == "response"

    def test_no_schema_passes_no_function(self, monkeypatch):
        """When json_schema is None, gemini call MUST NOT receive a
        synthesized function dict — leaving caller free to use gemini's
        existing function= parameter directly (which JSONAgent doesn't
        forward today; this is preserved no-function behavior)."""
        client = _GeminiStubClient({"value": "ok"})
        agent = _patched_agent(monkeypatch, "gemini", client)

        JSONAgent.generate(agent, "prompt")

        # Gemini got called WITHOUT a function= kwarg.
        # (Hidden caveat: existing JSONAgent has a latent
        # signature-mismatch bug routing to gemini without function. This
        # test pins the new behavior: when json_schema is None, we do
        # NOT manufacture a function dict.)
        assert client.calls[0]["function"] is None

    def test_additional_instructions_passes_system_prompt(self, monkeypatch):
        """Gemini's signature: generate_json(message, function, additional_instructions, ...)
        Our system_prompt kwarg maps to additional_instructions on gemini."""
        client = _GeminiStubClient({"value": "ok"})
        agent = _patched_agent(monkeypatch, "gemini", client)

        JSONAgent.generate(
            agent, "prompt",
            system_prompt="you are concise",
            json_schema=SAMPLE_SCHEMA,
        )

        assert client.calls[0].get("additional_instructions") == "you are concise"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_unit_jsonagent_schema.py::TestDispatchGeminiTranslation -v`
Expected: FAIL — gemini still gets `json_schema=` instead of `function=`.

- [ ] **Step 3: Implement**

Update `JSONAgent.generate` in `src/autonomous/ai/jsonagent.py` to branch on provider. Replace the dispatch block:

```python
        result = client.generate_json(
            message,
            system_prompt=system_prompt,
            uri=uri,
            context=context,
            json_schema=json_schema,
            schema_name=schema_name,
            **kwargs,
        )
```

with:

```python
        # Per-provider dispatch. Gemini's existing function= parameter
        # already IS a JSON-schema carrier (function.parameters), so we
        # synthesize a function dict from json_schema. Other providers
        # accept json_schema= directly.
        if provider == "gemini":
            function = None
            if json_schema is not None:
                function = {
                    "name": schema_name,
                    "description": "Structured response shape.",
                    "parameters": json_schema,
                }
            result = client.generate_json(
                message,
                function=function,
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
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_unit_jsonagent_schema.py -v`
Expected: 12 passed (8 prior + 4 gemini).

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/jsonagent.py tests/unit/test_unit_jsonagent_schema.py
git commit -m "feat(jsonagent): translate json_schema to gemini function dict"
```

---

## Task 11: `JSONAgent.generate` centralized schema validation

**Files:**
- Modify: `src/autonomous/ai/jsonagent.py` (call `_schema_validate` after parsing)
- Test: `tests/unit/test_unit_jsonagent_schema.py` (extend)

Run `_schema_validate(result, json_schema, raw=...)` after the result has been parsed to a dict. Catches provider bugs across ALL providers — including gemini's strict function-calling response.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_unit_jsonagent_schema.py`:

```python
from autonomous.ai.exceptions import GenerateJSONParseError


class TestCentralizedValidation:
    """The centralized _schema_validate call runs after every provider's
    response is parsed to a dict. Catches drift even when the provider
    claims strict-mode compliance — defense in depth."""

    def test_conforming_response_passes(self, monkeypatch):
        client = _StubProviderClient({"value": "ok"})
        agent = _patched_agent(monkeypatch, "openai", client)

        result = JSONAgent.generate(
            agent, "prompt", json_schema=SAMPLE_SCHEMA
        )
        assert result == {"value": "ok"}

    def test_missing_required_raises_parse_error(self, monkeypatch):
        # Provider returns dict missing required "value" field.
        client = _StubProviderClient({"other": "field"})
        agent = _patched_agent(monkeypatch, "openai", client)

        with pytest.raises(GenerateJSONParseError):
            JSONAgent.generate(agent, "prompt", json_schema=SAMPLE_SCHEMA)

    def test_extra_property_raises_parse_error(self, monkeypatch):
        # additionalProperties=False on SAMPLE_SCHEMA forbids extras.
        client = _StubProviderClient({"value": "ok", "unexpected": True})
        agent = _patched_agent(monkeypatch, "openai", client)

        with pytest.raises(GenerateJSONParseError):
            JSONAgent.generate(agent, "prompt", json_schema=SAMPLE_SCHEMA)

    def test_validation_skipped_when_no_schema(self, monkeypatch):
        # Non-conforming would-be result — but no schema → no validation.
        client = _StubProviderClient({"anything": "goes"})
        agent = _patched_agent(monkeypatch, "openai", client)

        result = JSONAgent.generate(agent, "prompt")  # no json_schema
        assert result == {"anything": "goes"}

    def test_validation_runs_for_gemini_too(self, monkeypatch):
        """Defense in depth: gemini's strict function-calling can still
        produce wrong-shape output (provider bugs); validate it too."""
        client = _GeminiStubClient({"other": "field"})  # missing "value"
        agent = _patched_agent(monkeypatch, "gemini", client)

        with pytest.raises(GenerateJSONParseError):
            JSONAgent.generate(agent, "prompt", json_schema=SAMPLE_SCHEMA)

    def test_validation_error_raw_populated(self, monkeypatch):
        client = _StubProviderClient({"other": "field"})
        agent = _patched_agent(monkeypatch, "openai", client)

        with pytest.raises(GenerateJSONParseError) as exc_info:
            JSONAgent.generate(agent, "prompt", json_schema=SAMPLE_SCHEMA)
        # raw should contain (at least a prefix of) the failing response
        assert "other" in exc_info.value.raw or "field" in exc_info.value.raw
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_unit_jsonagent_schema.py::TestCentralizedValidation -v`
Expected: FAIL on tests that expect `GenerateJSONParseError` — validation isn't wired yet.

- [ ] **Step 3: Implement**

In `src/autonomous/ai/jsonagent.py`, add the import (top of file):

```python
from autonomous.ai._json_utils import _schema_validate
```

Then, in `JSONAgent.generate`, add the validation call AFTER the `isinstance` checks (which guarantee `result` is a dict) and BEFORE `self.add_to_job_meta("Last JSON", result)`:

```python
        # Defense in depth: validate every provider's output. Catches
        # provider bugs even when the provider claims schema compliance
        # (gemini function-calling, OpenAI strict mode). No-op when
        # json_schema is None.
        _schema_validate(result, json_schema, raw=json.dumps(result)[:500])

        self.add_to_job_meta("Last JSON", result)
        return result
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_unit_jsonagent_schema.py -v`
Expected: 18 passed (12 prior + 6 new validation).

Also verify no regressions in other test files: `pytest tests/unit/ -q --no-cov-on-fail 2>&1 | tail -5`. The only failing test should be the pre-existing Sphinx one (covered separately).

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/jsonagent.py tests/unit/test_unit_jsonagent_schema.py
git commit -m "feat(jsonagent): centralized schema validation on every provider's response"
```

---

## Task 12: MIGRATIONS.md entry

**Files:**
- Modify: `MIGRATIONS.md`

Document the consumer-visible additions per the project convention.

- [ ] **Step 1: Find the next item number**

```bash
head -10 MIGRATIONS.md
```

Identify the next sequential item number to use (after the most recent — possibly Item 25 if FLUX-routing landed first as Item 24, or Item 24 if not).

- [ ] **Step 2: Add the entry**

Insert at the top of the items list (after the preamble, before the previous top item):

```markdown
### JSON Schema / Structured Outputs support (Item <N>)

**What changed.**

- New optional kwargs on `JSONAgent.generate`: `json_schema=None`,
  `schema_name="response"`. When `json_schema` is set, the response is
  validated against the schema before return; mismatches raise
  `GenerateJSONParseError` with the raw response on `.raw`.
- New optional kwargs on `OpenAIClient.generate_json`: `json_schema=None`,
  `schema_name="response"`. When set AND the (model, endpoint) is not
  known-unsupported, builds an OpenAI strict-mode `response_format`
  payload (`{"type": "json_schema", "json_schema": {...}, "strict": true}`).
  Conservative 400/422 detection (looks for `json_schema`,
  `response_format`, `unsupported_parameter`, `structured output` in the
  error body) triggers a one-time fallback to loose mode and caches the
  combo for the rest of the process. Operator log marker on first
  detection: `[STRUCTURED-OUTPUTS-UNAVAILABLE]`.
- New optional kwargs on `LocalAIModel.generate_json`: `json_schema=None`,
  `schema_name="response"`. Local has no equivalent of strict mode;
  passing a schema logs `[STRUCTURED-OUTPUTS-UNAVAILABLE]` once per
  (model, endpoint) and proceeds via the existing prompt-only path.
  Client-side validation in `JSONAgent.generate` still applies.
- `MockAIModel.generate_json` absorbs the new kwargs via `**kwargs`.
- `GeminiAIModel.generate_json` is unchanged — its existing `function=`
  parameter already takes a JSON schema. `JSONAgent.generate` translates
  `json_schema=` into the gemini `function` dict at the dispatch layer.
- New core dependency: `jsonschema>=4.0`. The client-side validation
  safety net is unconditionally available (not gated on the `[ai]` extra).
- New helper: `autonomous.ai.models.openai_compat._reset_unsupported_cache()`
  — clears the negative cache. Tests use this for isolation; operators
  may use it after deploying a server-side fix to re-probe strict-mode
  support without restarting the worker.

**Migration.**

No source change required for existing consumers. With `json_schema`
unset (the default), `JSONAgent.generate` behaves identically to today,
and the validation no-ops.

To opt in (per call site):

```python
LORE_BLUEPRINT_SCHEMA = {
    "type": "object",
    "properties": {...},
    "required": [...],
    "additionalProperties": False,
}

result = self.world.system.generate_json(
    prompt=stage1_prompt,
    primer=stage1_primer,
    json_schema=LORE_BLUEPRINT_SCHEMA,
    schema_name="lore_blueprint",   # optional; defaults to "response"
)
```

Behavior when something goes wrong:
- Strict-mode unavailable on the (model, endpoint): one-time
  `[STRUCTURED-OUTPUTS-UNAVAILABLE]` log + fallback to loose mode +
  cache for the process. Subsequent calls go directly to loose mode.
- Response fails client-side validation: `GenerateJSONParseError`
  raised with `.raw` populated.

**Provider support matrix (as known on 2026-06-02).**

| Provider | Strict-mode native | Client-side validation |
|---|---|---|
| `GeminiAIModel` (via `function=`) | Yes (function-calling) | Yes (defense in depth) |
| `OpenAIClient` (chat.binghamton.edu, OpenAI direct) | Endpoint-dependent — fallback handles mismatch | Yes |
| `LocalAIModel` (Ollama) | No (prompt-only) | Yes |
| `MockAIModel` | n/a (deterministic) | Yes — test authors must construct conforming mock data |

**Tracked in:** `Sallenmoore/storyteller#12` (filed against the consumer's tracker; library work happens in autonomous).
```

(Adjust `Item <N>` to the actual next number from Step 1.)

- [ ] **Step 3: Commit**

```bash
git add MIGRATIONS.md
git commit -m "docs(migrations): JSON Schema / structured outputs support"
```

---

## Task 13: Full-suite sanity + push + PR

**Files:** none

Final wrap-up. Verify everything green, push the feature branch, open the PR.

- [ ] **Step 1: Run the full unit suite**

```bash
pytest tests/unit -q --no-cov-on-fail 2>&1 | tail -10
```

Expected: all green. The pre-existing Sphinx test should also pass (if the FLUX iteration's `docs/conf.py` exclude landed; otherwise expect 1 pre-existing failure unrelated to this PR). Note the count.

- [ ] **Step 2: Lint (flake8 syntax-only gate per CI)**

```bash
flake8 . --select=E9,F63,F7,F82
```

Expected: clean (exit 0).

- [ ] **Step 3: Build + twine check**

```bash
python -m build && python -m twine check dist/* && rm -rf dist/ src/autonomous_app.egg-info/
```

Expected: PASSED for both sdist and wheel.

- [ ] **Step 4: Push branch + open PR**

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git push -u origin "$BRANCH"

gh pr create --repo Sallenmoore/autonomous \
  --base test --head "$BRANCH" \
  --title "iter/2026-06-02: JSON Schema / structured outputs support" \
  --body "$(cat <<'EOF'
## Summary

Adds optional `json_schema=` kwarg to `JSONAgent.generate` and provider
`generate_json` methods. OpenAI strict-mode `response_format` is built
when a schema is passed AND the (model, endpoint) supports it; conservative
400/422 detection triggers a one-time fallback to loose mode and caches
the combo for the process. Gemini's existing `function=` parameter
already takes a JSON schema; `JSONAgent.generate` translates `json_schema=`
into the gemini function dict at the dispatch layer. Local logs once and
proceeds prompt-only. Mock absorbs the kwarg.

`jsonschema>=4.0` becomes a core dependency so the client-side validation
safety net is unconditionally available — every provider's response is
validated when a schema is passed (defense in depth, including gemini's
strict function-calling output).

Backward-compatible: existing call sites unaffected when `json_schema=None`
(the default).

Spec: `docs/superpowers/specs/2026-06-02-json-schema-structured-outputs-design.md`
Plan: `docs/superpowers/plans/2026-06-02-json-schema-structured-outputs.md`
Tracked in: `Sallenmoore/storyteller#12`

## Test plan

- [x] `tests/unit/test_unit_jsonschema_dependency.py` — core dep present
- [x] `tests/unit/test_unit_json_utils_schema_validate.py` — 6 validation cases
- [x] `tests/unit/test_unit_mock_model_json_schema.py` — kwarg absorption
- [x] `tests/unit/test_unit_local_model_json_schema.py` — log-once + signature
- [x] `tests/unit/test_unit_openai_compat_structured_outputs.py` — 24 tests:
      heuristic helpers, strict-mode payload, fallback paths (400 with
      marker, 422 with marker, bare 400 propagates), cache short-circuit,
      cross-(model,endpoint) isolation
- [x] `tests/unit/test_unit_jsonagent_schema.py` — 18 tests: dispatch
      across providers (openai/local/mock + gemini translation), centralized
      validation including for gemini paths, string-response parsing
      preserved
- [x] Full unit suite green
- [x] flake8 syntax gate clean
- [x] build + twine check pass
- [ ] Operator: bump `autonomous-app` in storyteller-dev via
      `bump-autonomous.sh ${NEW_VERSION}` after release
- [ ] Storyteller: adopt per call site (lore-builder Stage 1 first as
      smoke test, then ~10 others per the issue's framing)

## Necessary follow-ups (separate iterations)

- Storyteller-side adoption per call site (~11 generators; storyteller tree)
- Silent-ignore detection (server returns 200 + non-conforming) — secondary
  cache mechanism, only if adoption surfaces the case
- OpenAI direct-API support matrix verification across the endpoints
  storyteller actually uses
EOF
)"
```

- [ ] **Step 5: Watch CI**

```bash
PR=<your-pr-number>
gh pr checks "$PR" --repo Sallenmoore/autonomous --watch
gh pr checks "$PR" --repo Sallenmoore/autonomous
```

Until green or 3 fix-up cycles still red.

---

## Necessary follow-ups (NOT in this plan)

Tracked here for visibility; each gets its own brainstorm → spec → plan cycle if/when prioritized:

1. **Storyteller-side adoption per call site** — ~11 generators per the issue. Each gets a schema design + adoption PR in the storyteller tree. Lore-builder Stage 1 first (smoke test); then Stage 2; then the others.
2. **Silent-ignore detection** — secondary cache mechanism that populates `_UNSUPPORTED_STRICT_MODE` after N consecutive client-side validation failures with `use_strict=True`. Only worth doing if real-world adoption surfaces the case.
3. **OpenAI support matrix verification** — confirm against the real endpoints storyteller uses (chat.binghamton.edu primarily; OpenAI direct as backup if configured).

---

## Self-Review

**Spec coverage:**
- Context + non-goals → covered by Tasks 1-12; non-goals respected (no storyteller-side adoption tasks, no gemini API surface changes)
- Architecture (three concerns split) → Tasks 2 (validation), 5-8 (openai strict/cache), 9-11 (jsonagent dispatch + validation)
- Components and interfaces → every file in the spec's "Components" section has a task
- Data flow (4 worked examples) → tests in Tasks 6-11 cover happy path, fallback, cache hit, gemini translation
- Error handling table → tests in Tasks 2 (validation raises), 6 (loose vs strict payload), 7 (fallback vs propagate), 10-11 (validation on dict result)
- Testing strategy (5 new test files) → Tasks 2, 3, 4, 5, 9 each create one of the 5 files
- Rollout plan → Task 13 handles library-side release; storyteller-side flagged as follow-up
- Necessary follow-ups → reproduced in plan body

**Placeholder scan:** None. Every step has actual file paths, complete code blocks, exact commands, and expected outputs.

**Type consistency:**
- `_schema_validate(payload, schema, raw="")` signature: defined in Task 2, called in Task 11 with `_schema_validate(result, json_schema, raw=json.dumps(result)[:500])` — kwarg names match.
- `_UNSUPPORTED_STRICT_MODE: set[tuple[str, str]]` shape: defined in Task 5, used in Tasks 6 (check), 7 (add), 8 (test pre-population). Tuple ordering `(model, base_url)` consistent throughout.
- `_looks_like_unsupported_strict_mode(status, body_text)` signature: defined in Task 5, called in Task 7.
- `_reset_unsupported_cache()` signature: defined in Task 5, used in test `setup_method`s in Tasks 5, 6, 7, 8.
- `_STRUCTURED_OUTPUTS_LOGGED: set[tuple[str, str]]` shape: defined in Task 4, only used internally.
- Kwarg names `json_schema` and `schema_name` consistent across Tasks 3, 4, 6, 9, 10.
- Gemini's `function` dict shape: `{"name": schema_name, "description": "Structured response shape.", "parameters": json_schema}` consistent in Task 10 spec + test.
- `GenerateJSONParseError(message, raw=...)` constructor consistent with existing usage; `.raw` attribute access consistent in Tasks 2 + 11 tests.
