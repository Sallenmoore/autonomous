"""Independent second-perspective coverage for PR #174 (issue #173) —
per-call ``model=`` override on the AI generation pipeline.

Written from a fresh read of the PR diff (no peek at dev's
``tests/_dev_local/``). The PR-contract claims under test:

- **Signature pin** — every adapter's ``generate_text`` /
  ``generate_json`` / ``summarize_text`` declares ``model=None`` (or
  accepts it via ``**kwargs`` on ``mock``). Every public agent surface
  threads ``model=`` through. ``AIModelProtocol.generate_json``
  declares the kwarg.
- **Default preserves env behavior** — omitting ``model`` (the default)
  keeps every adapter on its persisted ``_text_model`` /
  ``_json_model`` / ``_summary_model`` / ``_chat`` arg-zero (pre-#173
  wire shape).
- **openai_compat strict-mode cache keys on effective model** — a
  per-call ``model="other"`` poisons the cache entry for
  ``("other", base_url)``, NOT for the configured default
  ``(self._json_model, base_url)``, and vice versa.
- **openai_compat ``_emit_strict_unavailable`` ``model=`` is wired** —
  helper accepts ``model=``, threads to the ``event(... model=...)``
  payload, defaults to ``self._json_model`` when omitted (existing
  caller back-compat).
- **local_model effective-model threads through** — the once-per-process
  ``_STRUCTURED_OUTPUTS_LOGGED`` key, the ``event(... model=...)``
  payload, the ``chat`` payload's ``"model"`` field, and the on-retry
  ``flush_memory(...)`` argument all use ``effective_model``.
- **local_model._evaluate_response accepts model=** — eval-critic call
  routes through the effective model when ``generate_text(evaluation=
  True, model="x")``.
- **gemini effective-model threads through** — ``model or
  self._text_model`` / ``model or self._json_model`` / ``model or
  self._summary_model`` reach ``client.models.generate_content``.
- **MIGRATIONS.md entry exists** — the consumer-visible documentation
  shipped alongside the surface change.

Forward-looking signature pins are deliberately listed as such — they
PASS on pre-#174 source for any adapter that already accepted ``model=``
via ``**kwargs`` (mock_model.generate_json). The cache-keying behavior
and the threading proofs are PR-contract-bound and fail on revert.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# A — Signature pin: every adapter + agent declares model=None
# ---------------------------------------------------------------------------


class TestAdapterSignatures:
    """Every adapter method declares (or accepts via **kwargs)
    ``model=None`` in the PR-canonical position."""

    def _adapter_classes(self):
        from autonomous.ai.models.flux import FluxAIModel
        from autonomous.ai.models.gemini import GeminiAIModel
        from autonomous.ai.models.local_model import LocalAIModel
        from autonomous.ai.models.mock_model import MockAIModel
        from autonomous.ai.models.openai_compat import OpenAIClient

        return {
            "openai_compat": OpenAIClient,
            "local": LocalAIModel,
            "gemini": GeminiAIModel,
            "mock": MockAIModel,
            "flux": FluxAIModel,
        }

    def _accepts_model_kwarg(self, sig: inspect.Signature) -> bool:
        if "model" in sig.parameters:
            return True
        return any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in sig.parameters.values()
        )

    def _model_default_is_none(self, sig: inspect.Signature) -> bool:
        param = sig.parameters.get("model")
        if param is None:
            # Absorbed via **kwargs — semantically defaults to "not passed".
            return True
        return param.default is None

    @pytest.mark.parametrize("method", ["generate_text", "generate_json", "summarize_text"])
    def test_openai_compat_declares_model_kwarg(self, method):
        from autonomous.ai.models.openai_compat import OpenAIClient

        sig = inspect.signature(getattr(OpenAIClient, method))
        assert self._accepts_model_kwarg(sig), f"openai_compat.{method} missing model kwarg"
        assert self._model_default_is_none(sig)

    @pytest.mark.parametrize("method", ["generate_text", "generate_json", "summarize_text"])
    def test_local_model_declares_model_kwarg(self, method):
        from autonomous.ai.models.local_model import LocalAIModel

        sig = inspect.signature(getattr(LocalAIModel, method))
        assert self._accepts_model_kwarg(sig)
        assert self._model_default_is_none(sig)

    @pytest.mark.parametrize("method", ["generate_text", "generate_json", "summarize_text"])
    def test_gemini_declares_model_kwarg(self, method):
        from autonomous.ai.models.gemini import GeminiAIModel

        sig = inspect.signature(getattr(GeminiAIModel, method))
        assert self._accepts_model_kwarg(sig)
        assert self._model_default_is_none(sig)

    @pytest.mark.parametrize("method", ["generate_text", "generate_json", "summarize_text"])
    def test_mock_declares_or_absorbs_model_kwarg(self, method):
        from autonomous.ai.models.mock_model import MockAIModel

        sig = inspect.signature(getattr(MockAIModel, method))
        assert self._accepts_model_kwarg(sig)

    def test_flux_generate_json_declares_model_kwarg(self):
        """flux.generate_json raises NotSupportedByProvider — signature
        pin only, for protocol conformance."""
        from autonomous.ai.models.flux import FluxAIModel

        sig = inspect.signature(FluxAIModel.generate_json)
        assert "model" in sig.parameters
        assert sig.parameters["model"].default is None


class TestAgentSignatures:
    """TextAgent / JSONAgent expose the per-call ``model=`` kwarg."""

    def test_textagent_generate_declares_model_kwarg(self):
        from autonomous.ai.textagent import TextAgent

        sig = inspect.signature(TextAgent.generate)
        assert "model" in sig.parameters
        assert sig.parameters["model"].default is None

    def test_textagent_summarize_text_declares_model_kwarg(self):
        from autonomous.ai.textagent import TextAgent

        sig = inspect.signature(TextAgent.summarize_text)
        assert "model" in sig.parameters
        assert sig.parameters["model"].default is None

    def test_jsonagent_generate_declares_model_kwarg(self):
        from autonomous.ai.jsonagent import JSONAgent

        sig = inspect.signature(JSONAgent.generate)
        assert "model" in sig.parameters
        assert sig.parameters["model"].default is None


class TestProtocolSignature:
    """``AIModelProtocol.generate_json`` declares the canonical
    ``model: str | None = None`` kwarg."""

    def test_protocol_generate_json_declares_model_kwarg(self):
        from autonomous.ai.protocol import AIModelProtocol

        sig = inspect.signature(AIModelProtocol.generate_json)
        assert "model" in sig.parameters
        assert sig.parameters["model"].default is None


# ---------------------------------------------------------------------------
# B — openai_compat: strict-mode negative cache keys on EFFECTIVE model
# ---------------------------------------------------------------------------


class _FakeHTTPError(Exception):
    """Mirrors the test_unit_openai_compat_structured_outputs._FakeHTTPError
    shape so the strict-mode fallback paths trigger."""

    def __init__(self, status, body):
        import requests

        super().__init__(f"HTTP {status}")
        self.response = type("R", (), {"status_code": status, "text": body})()
        self._real = requests.HTTPError(f"HTTP {status}", response=self.response)


def _bare_openai_client(monkeypatch, captured, *, json_model, base_url):
    """Build a stripped OpenAIClient with stubbed _chat that captures every
    (model, response_format) pair the strict-mode flow sends."""
    from autonomous.ai.models.openai_compat import OpenAIClient

    client = OpenAIClient.__new__(OpenAIClient)
    object.__setattr__(client, "_data", {"instructions": "Be helpful."})
    object.__setattr__(client, "_dynamic_fields", {})
    object.__setattr__(client, "_changed_fields", [])
    object.__setattr__(client, "_initialised", True)
    object.__setattr__(client, "_created", False)
    client._json_model = json_model
    client._base_url = base_url
    client._api_key = "test-key"

    def fake_chat(model, system, user, response_format=None, temperature=0.7):
        captured.setdefault("calls", []).append(
            {"model": model, "response_format": response_format}
        )
        return '{"value": "ok"}'

    monkeypatch.setattr(client, "_chat", fake_chat)
    return client


class TestOpenAICompatEffectiveModelThreading:
    SAMPLE_SCHEMA = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }

    def setup_method(self):
        from autonomous.ai.models.openai_compat import _reset_unsupported_cache

        _reset_unsupported_cache()

    def test_per_call_model_threads_to_chat_first_arg_loose(self, monkeypatch):
        captured = {}
        client = _bare_openai_client(
            monkeypatch, captured,
            json_model="default-json-model",
            base_url="https://endpoint/api",
        )
        from autonomous.ai.models.openai_compat import OpenAIClient

        OpenAIClient.generate_json(client, "prompt", model="override-model")

        assert captured["calls"][0]["model"] == "override-model"

    def test_default_model_threads_self_json_model_loose(self, monkeypatch):
        """Omitting model= preserves pre-#174 wire shape (self._json_model)."""
        captured = {}
        client = _bare_openai_client(
            monkeypatch, captured,
            json_model="default-json-model",
            base_url="https://endpoint/api",
        )
        from autonomous.ai.models.openai_compat import OpenAIClient

        OpenAIClient.generate_json(client, "prompt")  # no model=

        assert captured["calls"][0]["model"] == "default-json-model"

    def test_per_call_text_model_threads_to_chat(self, monkeypatch):
        captured = {}
        client = _bare_openai_client(
            monkeypatch, captured,
            json_model="ignored",
            base_url="https://endpoint/api",
        )
        client._text_model = "default-text-model"
        from autonomous.ai.models.openai_compat import OpenAIClient

        OpenAIClient.generate_text(client, "prompt", model="text-override")

        assert captured["calls"][0]["model"] == "text-override"

    def test_per_call_summary_model_threads_to_chat(self, monkeypatch):
        captured = {}
        client = _bare_openai_client(
            monkeypatch, captured,
            json_model="ignored",
            base_url="https://endpoint/api",
        )
        client._summary_model = "default-summary"
        from autonomous.ai.models.openai_compat import OpenAIClient

        OpenAIClient.summarize_text(client, "long text", model="summary-override")

        assert captured["calls"][0]["model"] == "summary-override"


class TestOpenAICompatStrictModeCacheKeying:
    """The KEY invariant — strict-mode unsupported cache keys on
    ``(effective_model, base_url)``, never the class default.

    These tests prove that an override and the default occupy
    INDEPENDENT cache entries — poisoning one does NOT block the other.
    """

    SAMPLE_SCHEMA = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }

    def setup_method(self):
        from autonomous.ai.models.openai_compat import _reset_unsupported_cache

        _reset_unsupported_cache()

    def _client_with_chat_effects(self, monkeypatch, *, json_model, base_url, effects):
        from autonomous.ai.models.openai_compat import OpenAIClient

        client = OpenAIClient.__new__(OpenAIClient)
        object.__setattr__(client, "_data", {"instructions": "Be helpful."})
        object.__setattr__(client, "_dynamic_fields", {})
        object.__setattr__(client, "_changed_fields", [])
        object.__setattr__(client, "_initialised", True)
        object.__setattr__(client, "_created", False)
        client._json_model = json_model
        client._base_url = base_url
        client._api_key = "test-key"

        calls = {"count": 0, "model_each": [], "rf_each": []}

        def fake_chat(model, system, user, response_format=None, temperature=0.7):
            calls["count"] += 1
            calls["model_each"].append(model)
            calls["rf_each"].append(response_format)
            effect = effects.pop(0) if effects else None
            if isinstance(effect, BaseException):
                raise effect
            return effect

        monkeypatch.setattr(client, "_chat", fake_chat)
        return client, calls

    def test_override_strict_failure_caches_override_key_not_default(self, monkeypatch):
        """Strict-mode 400 on a per-call override key MUST go into the
        cache as (override, base_url), NOT (default, base_url).

        This is the headline correctness fix in PR #174. Reverted source
        would poison (default-json, base_url) and break the next default-
        model strict probe.
        """
        import requests

        from autonomous.ai.models.openai_compat import _UNSUPPORTED_STRICT_MODE

        real_err = requests.HTTPError("HTTP 400")
        real_err.response = type(
            "R", (), {"status_code": 400, "text": "Invalid response_format type 'json_schema'"}
        )()

        client, calls = self._client_with_chat_effects(
            monkeypatch,
            json_model="default-json",
            base_url="https://endpoint/api",
            effects=[real_err, '{"v": "ok"}'],
        )
        from autonomous.ai.models.openai_compat import OpenAIClient

        OpenAIClient.generate_json(
            client, "prompt", json_schema=self.SAMPLE_SCHEMA, model="override-model"
        )

        # The override key is cached; the default key is NOT.
        assert ("override-model", "https://endpoint/api") in _UNSUPPORTED_STRICT_MODE
        assert ("default-json", "https://endpoint/api") not in _UNSUPPORTED_STRICT_MODE

    def test_default_strict_failure_caches_default_key_not_override(self, monkeypatch):
        """Mirror case: failure on the env default cache only against
        the default key, never any override."""
        import requests

        from autonomous.ai.models.openai_compat import _UNSUPPORTED_STRICT_MODE

        real_err = requests.HTTPError("HTTP 400")
        real_err.response = type(
            "R", (), {"status_code": 400, "text": "json_schema not supported"}
        )()

        client, calls = self._client_with_chat_effects(
            monkeypatch,
            json_model="default-json",
            base_url="https://endpoint/api",
            effects=[real_err, '{"v": "ok"}'],
        )
        from autonomous.ai.models.openai_compat import OpenAIClient

        OpenAIClient.generate_json(client, "prompt", json_schema=self.SAMPLE_SCHEMA)

        assert ("default-json", "https://endpoint/api") in _UNSUPPORTED_STRICT_MODE
        assert ("override-model", "https://endpoint/api") not in _UNSUPPORTED_STRICT_MODE

    def test_cached_override_skips_strict_for_override_but_default_still_strict(self, monkeypatch):
        """A cached (override, endpoint) means override-routed calls
        skip strict-mode probe — but a default-routed call still uses
        strict mode because the default key isn't in the cache.

        This is the cache-bifurcation property: independence in both
        directions."""
        import requests

        from autonomous.ai.models.openai_compat import _UNSUPPORTED_STRICT_MODE

        # Pre-poison only the override key.
        _UNSUPPORTED_STRICT_MODE.add(("override-model", "https://endpoint/api"))

        client, calls = self._client_with_chat_effects(
            monkeypatch,
            json_model="default-json",
            base_url="https://endpoint/api",
            effects=['{"v": "ok"}', '{"v": "ok"}'],
        )
        from autonomous.ai.models.openai_compat import OpenAIClient

        OpenAIClient.generate_json(
            client, "prompt", json_schema=self.SAMPLE_SCHEMA, model="override-model"
        )
        OpenAIClient.generate_json(client, "prompt", json_schema=self.SAMPLE_SCHEMA)

        # Override-routed: skipped strict (loose-mode response_format)
        assert calls["rf_each"][0] == {"type": "json_object"}
        # Default-routed: strict-mode response_format still attempted
        assert calls["rf_each"][1]["type"] == "json_schema"


# ---------------------------------------------------------------------------
# C — openai_compat _emit_strict_unavailable accepts model= and threads
# ---------------------------------------------------------------------------


class TestEmitStrictUnavailableModelKwarg:
    """``_emit_strict_unavailable(model=...)`` threads through to
    ``event(... model=...)``. When omitted, falls back to
    ``self._json_model`` (existing callers stay attribution-correct)."""

    def setup_method(self):
        from autonomous.ai.models.openai_compat import _reset_unsupported_cache

        _reset_unsupported_cache()

    def _client(self):
        from autonomous.ai.models.openai_compat import OpenAIClient

        client = OpenAIClient.__new__(OpenAIClient)
        object.__setattr__(client, "_data", {"instructions": "Be helpful."})
        object.__setattr__(client, "_dynamic_fields", {})
        object.__setattr__(client, "_changed_fields", [])
        object.__setattr__(client, "_initialised", True)
        object.__setattr__(client, "_created", False)
        client._json_model = "default-json"
        client._base_url = "https://endpoint/api"
        client._api_key = "test-key"
        return client

    def test_emit_signature_declares_model_kwarg(self):
        from autonomous.ai.models.openai_compat import OpenAIClient

        sig = inspect.signature(OpenAIClient._emit_strict_unavailable)
        assert "model" in sig.parameters
        assert sig.parameters["model"].default is None

    def test_event_payload_uses_explicit_model(self):
        from autonomous.ai.models import openai_compat

        client = self._client()
        with patch.object(openai_compat, "event") as mock_event:
            client._emit_strict_unavailable(
                status=400, body_excerpt="x", detection="first", model="override-x"
            )

        # `event` resolves through the module namespace — patch.object
        # on the module object catches the call.
        assert mock_event.called
        kwargs = mock_event.call_args.kwargs
        assert kwargs["model"] == "override-x"

    def test_event_payload_falls_back_to_self_json_model(self):
        from autonomous.ai.models import openai_compat

        client = self._client()
        with patch.object(openai_compat, "event") as mock_event:
            client._emit_strict_unavailable(
                status=400, body_excerpt="x", detection="first"
            )

        kwargs = mock_event.call_args.kwargs
        assert kwargs["model"] == "default-json"


# ---------------------------------------------------------------------------
# D — local_model: effective_model threads through cache key, telemetry,
#     chat payload, and on-retry flush_memory
# ---------------------------------------------------------------------------


@pytest.fixture
def local_model_fixture():
    from autonomous.ai.models.local_model import LocalAIModel

    m = LocalAIModel.__new__(LocalAIModel)
    # Prime MongoEngine descriptor state so ``self.instructions`` reads
    # the seeded value without touching Mongo (see analogous
    # openai_compat fixture in test_unit_openai_compat_structured_outputs).
    object.__setattr__(m, "_data", {"instructions": "Be a helpful AI."})
    object.__setattr__(m, "_dynamic_fields", {})
    object.__setattr__(m, "_changed_fields", [])
    object.__setattr__(m, "_initialised", True)
    object.__setattr__(m, "_created", False)
    for key, val in {
        "_ollama_url": "http://mock-ollama",
        "_media_url": "http://mock-media",
        "_image_url": "http://mock-media",
        "_audio_url": "http://mock-media",
        "_text_model": "default-text",
        "_context_limit": 32768,
        "_retry_sleep": 0,
        "_json_timeout": 1,
        "_text_timeout": 1,
        "_summary_timeout": 1,
        "_media_timeout": 1,
    }.items():
        object.__setattr__(m, key, val)
    return m


class TestLocalModelEffectiveModelThreading:
    SCHEMA = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }

    def _reset_logged_set(self):
        from autonomous.ai.models import local_model

        local_model._STRUCTURED_OUTPUTS_LOGGED.clear()

    @pytest.fixture(autouse=True)
    def _silence_autotasks(self):
        with patch("autonomous.ai.models.local_model.AutoTasks") as mock_tasks:
            mock_tasks.return_value.get_current_task.return_value = None
            yield

    def test_generate_json_chat_payload_model_is_effective(self, local_model_fixture, monkeypatch):
        self._reset_logged_set()
        captured = {}

        class FakeResp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": '{"value": "ok"}'}}

        def fake_post(url, json=None, timeout=None, **kw):
            captured["json"] = json
            return FakeResp()

        monkeypatch.setattr(
            "autonomous.ai.models.local_model._HTTP.post", fake_post
        )

        local_model_fixture.generate_json("prompt", model="override-x")

        assert captured["json"]["model"] == "override-x"

    def test_generate_json_default_model_falls_back_to_text_model(self, local_model_fixture, monkeypatch):
        """Omitting model= keeps the pre-#174 wire shape — payload
        carries ``self._text_model`` (Ollama uses text model for JSON)."""
        self._reset_logged_set()
        captured = {}

        class FakeResp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": '{"value": "ok"}'}}

        def fake_post(url, json=None, timeout=None, **kw):
            captured["json"] = json
            return FakeResp()

        monkeypatch.setattr(
            "autonomous.ai.models.local_model._HTTP.post", fake_post
        )

        local_model_fixture.generate_json("prompt")

        assert captured["json"]["model"] == "default-text"

    def test_structured_outputs_logged_keys_on_effective_model(self, local_model_fixture, monkeypatch):
        """``_STRUCTURED_OUTPUTS_LOGGED`` cache MUST key on the effective
        per-call model so override + default each get their own
        once-per-process emission."""
        from autonomous.ai.models import local_model as lm_mod

        self._reset_logged_set()

        class FakeResp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": '{"value": "ok"}'}}

        def fake_post(url, json=None, timeout=None, **kw):
            return FakeResp()

        monkeypatch.setattr("autonomous.ai.models.local_model._HTTP.post", fake_post)

        # Drive both branches under the same client; verify keys.
        local_model_fixture.generate_json(
            "prompt", model="override-x", json_schema=self.SCHEMA
        )
        local_model_fixture.generate_json("prompt", json_schema=self.SCHEMA)

        assert ("override-x", "http://mock-ollama") in lm_mod._STRUCTURED_OUTPUTS_LOGGED
        assert ("default-text", "http://mock-ollama") in lm_mod._STRUCTURED_OUTPUTS_LOGGED

    def test_structured_outputs_event_model_is_effective(self, local_model_fixture, monkeypatch):
        """The ``event()`` payload's ``model`` field carries the effective
        per-call model, not the class default."""
        from autonomous.ai.models import local_model as lm_mod

        self._reset_logged_set()

        class FakeResp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": '{"value": "ok"}'}}

        def fake_post(url, json=None, timeout=None, **kw):
            return FakeResp()

        monkeypatch.setattr("autonomous.ai.models.local_model._HTTP.post", fake_post)

        with patch.object(lm_mod, "event") as mock_event:
            local_model_fixture.generate_json(
                "prompt", model="override-x", json_schema=self.SCHEMA
            )

        assert mock_event.called
        # find the structured_outputs_unavailable event
        for call in mock_event.call_args_list:
            if call.args and call.args[0] == "structured_outputs_unavailable":
                assert call.kwargs["model"] == "override-x"
                return
        pytest.fail("structured_outputs_unavailable event not emitted")

    def test_generate_text_payload_model_is_effective(self, local_model_fixture, monkeypatch):
        captured = {}

        class FakeResp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": "result text"}}

        def fake_post(url, json=None, timeout=None, **kw):
            captured["json"] = json
            return FakeResp()

        monkeypatch.setattr("autonomous.ai.models.local_model._HTTP.post", fake_post)

        local_model_fixture.generate_text("hi", model="override-text")

        assert captured["json"]["model"] == "override-text"

    def test_summarize_text_payload_model_is_effective(self, local_model_fixture, monkeypatch):
        captured = {"payloads": []}

        class FakeResp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": "a summary"}}

        def fake_post(url, json=None, timeout=None, **kw):
            captured["payloads"].append(json)
            return FakeResp()

        monkeypatch.setattr("autonomous.ai.models.local_model._HTTP.post", fake_post)

        local_model_fixture.summarize_text("text", model="override-sum")

        assert captured["payloads"]
        assert all(p["model"] == "override-sum" for p in captured["payloads"])

    def test_generate_json_on_retry_flushes_effective_model(self, local_model_fixture, monkeypatch):
        """The on-retry ``flush_memory(...)`` flushes the effective per-call
        model's KV cache, NOT the class default's."""
        flushes = []

        # First call raises ConnectionError to trigger _on_retry; second succeeds.
        class FakeResp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": '{"value": "ok"}'}}

        call_counter = {"n": 0}

        def fake_post(url, json=None, timeout=None, **kw):
            call_counter["n"] += 1
            if call_counter["n"] == 1 and "/api/chat" in url:
                import requests as _r

                raise _r.ConnectionError("boom once")
            return FakeResp()

        monkeypatch.setattr("autonomous.ai.models.local_model._HTTP.post", fake_post)

        def fake_flush(model_name):
            flushes.append(model_name)

        monkeypatch.setattr(local_model_fixture, "flush_memory", fake_flush)

        # Use override model — on-retry must flush THIS, not _text_model.
        local_model_fixture.generate_json("prompt", model="override-flush")

        assert flushes, "flush_memory should have fired on retry"
        assert flushes[0] == "override-flush"


class TestLocalModelEvaluateResponseModelKwarg:
    """``_evaluate_response`` accepts ``model=`` and uses it as the eval
    prompt's ``model`` field. When omitted, reads
    ``OLLAMA_TEXT_MODEL`` live (matches pre-#173 contract)."""

    def test_signature_declares_model_kwarg(self):
        from autonomous.ai.models.local_model import LocalAIModel

        sig = inspect.signature(LocalAIModel._evaluate_response)
        assert "model" in sig.parameters
        assert sig.parameters["model"].default is None

    def test_explicit_model_threads_to_eval_payload(self, local_model_fixture, monkeypatch):
        captured = {}

        class FakeResp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": "eval ok"}}

        def fake_post(url, json=None, timeout=None, **kw):
            captured["json"] = json
            return FakeResp()

        monkeypatch.setattr("autonomous.ai.models.local_model._HTTP.post", fake_post)

        local_model_fixture._evaluate_response(
            "instr", "content", "goal", model="critic-override"
        )

        assert captured["json"]["model"] == "critic-override"


# ---------------------------------------------------------------------------
# E — gemini: effective_model threads through .generate_content(model=...)
# ---------------------------------------------------------------------------


def _bare_gemini(monkeypatch, captured):
    from autonomous.ai.models.gemini import GeminiAIModel

    m = GeminiAIModel.__new__(GeminiAIModel)
    object.__setattr__(m, "_data", {"instructions": "Be helpful."})
    object.__setattr__(m, "_dynamic_fields", {})
    object.__setattr__(m, "_changed_fields", [])
    object.__setattr__(m, "_initialised", True)
    object.__setattr__(m, "_created", False)
    m._text_model = "default-gemini-text"
    m._json_model = "default-gemini-json"
    m._summary_model = "default-gemini-summary"

    class FakeResp:
        text = "ok"

    class FakeModels:
        def generate_content(self, model=None, **kw):
            captured.setdefault("calls", []).append({"model": model, "kw": kw})
            return FakeResp()

    class FakeClient:
        def __init__(self):
            self.models = FakeModels()

    # `client` is a @property fronting `_client`; setting `_client`
    # bypasses the property setter (it has none) while keeping the
    # read path intact.
    object.__setattr__(m, "_client", FakeClient())
    return m


class TestGeminiEffectiveModelThreading:
    def test_generate_text_per_call_model(self, monkeypatch):
        captured = {}
        m = _bare_gemini(monkeypatch, captured)
        from autonomous.ai.models.gemini import GeminiAIModel

        GeminiAIModel.generate_text(m, "prompt", model="text-override")

        assert captured["calls"][0]["model"] == "text-override"

    def test_generate_text_default_uses_self_text_model(self, monkeypatch):
        captured = {}
        m = _bare_gemini(monkeypatch, captured)
        from autonomous.ai.models.gemini import GeminiAIModel

        GeminiAIModel.generate_text(m, "prompt")

        assert captured["calls"][0]["model"] == "default-gemini-text"

    def test_summarize_text_per_call_model(self, monkeypatch):
        captured = {}
        m = _bare_gemini(monkeypatch, captured)
        from autonomous.ai.models.gemini import GeminiAIModel

        GeminiAIModel.summarize_text(m, "long text", model="sum-override")

        assert captured["calls"]
        assert captured["calls"][0]["model"] == "sum-override"

    def test_summarize_text_default_uses_self_summary_model(self, monkeypatch):
        captured = {}
        m = _bare_gemini(monkeypatch, captured)
        from autonomous.ai.models.gemini import GeminiAIModel

        GeminiAIModel.summarize_text(m, "long text")

        assert captured["calls"]
        assert captured["calls"][0]["model"] == "default-gemini-summary"


# ---------------------------------------------------------------------------
# F — Migration documentation pin
# ---------------------------------------------------------------------------


class TestMigrationsDocumentationPin:
    """``MIGRATIONS.md`` carries the consumer-visible entry for #173."""

    def test_migrations_md_contains_per_call_model_entry(self):
        repo_root = Path(__file__).resolve().parents[2]
        migrations = (repo_root / "MIGRATIONS.md").read_text()
        # Section heading is the load-bearing contract; entries below it
        # are content that could legitimately rephrase.
        assert "Per-call `model=` override" in migrations
        assert "#173" in migrations
