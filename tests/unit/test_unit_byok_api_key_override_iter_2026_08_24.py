"""Per-call ``api_key=`` override plumbing — BYOK (#227).

A multi-tenant consumer must be able to generate on an end user's own
provider key without mutating process-global state. The pieces pinned
here:

- the ContextVar primitive itself (bind / resolve / unwind / isolation);
- **per-provider scoping** — the load-bearing safety property. A key
  bound for FLUX must never reach Gemini on the fallback leg;
- each adapter actually reading through the resolver;
- the ``api_key=`` kwarg on every agent entry point reaching the adapter.
"""

import os
import threading

import pytest

from autonomous.ai._credentials import (
    active_override_vars,
    api_key_override,
    client_key_scope,
    resolve_api_key,
)


class TestOverridePrimitive:
    def test_override_wins_over_env(self, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "env-key")
        with api_key_override({"FAL_KEY": "user-key"}):
            assert resolve_api_key("FAL_KEY") == "user-key"

    def test_env_used_when_unbound(self, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "env-key")
        assert resolve_api_key("FAL_KEY") == "env-key"

    def test_binding_unwinds_even_on_exception(self, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "env-key")
        with pytest.raises(RuntimeError):
            with api_key_override({"FAL_KEY": "user-key"}):
                raise RuntimeError("boom")
        assert resolve_api_key("FAL_KEY") == "env-key"
        assert active_override_vars() == []

    def test_none_and_empty_are_noops(self, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "env-key")
        # Callers pass a user-supplied api_key straight through; None must
        # not need a branch at every call site.
        with api_key_override(None):
            assert resolve_api_key("FAL_KEY") == "env-key"
        with api_key_override({"FAL_KEY": None}):
            assert resolve_api_key("FAL_KEY") == "env-key"

    def test_explicit_default_beats_env_but_loses_to_override(self, monkeypatch):
        # The openai_compat / litellm shape: a class-attr snapshot is the
        # default, so monkeypatching the class attr still retargets.
        monkeypatch.setenv("HPC_API_KEY", "env-key")
        assert resolve_api_key("HPC_API_KEY", "class-attr-key") == "class-attr-key"
        with api_key_override({"HPC_API_KEY": "user-key"}):
            assert resolve_api_key("HPC_API_KEY", "class-attr-key") == "user-key"

    def test_nested_scopes_merge_inner_wins(self, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "env-key")
        with api_key_override({"FAL_KEY": "outer", "GOOGLEAI_KEY": "goog"}):
            with api_key_override({"FAL_KEY": "inner"}):
                assert resolve_api_key("FAL_KEY") == "inner"
                assert resolve_api_key("GOOGLEAI_KEY") == "goog"
            assert resolve_api_key("FAL_KEY") == "outer"

    def test_active_override_vars_never_leaks_values(self):
        with api_key_override({"FAL_KEY": "super-secret"}):
            assert active_override_vars() == ["FAL_KEY"]
            assert "super-secret" not in str(active_override_vars())


class TestPerProviderScoping:
    """The safety property: a key only reaches the provider it is for."""

    def test_other_providers_are_not_overridden(self, monkeypatch):
        monkeypatch.setenv("GOOGLEAI_KEY", "platform-google-key")
        with api_key_override({"FAL_KEY": "user-fal-key"}):
            # ImageAgent's FLUX->Gemini fallback leg must NOT bill/authenticate
            # with the user's fal.ai credential.
            assert resolve_api_key("GOOGLEAI_KEY") == "platform-google-key"


class TestThreadIsolation:
    def test_binding_does_not_leak_to_another_thread(self, monkeypatch):
        # The RQ-worker failure mode the whole design exists to prevent.
        monkeypatch.setenv("FAL_KEY", "env-key")
        seen = {}

        def other_job():
            seen["key"] = resolve_api_key("FAL_KEY")

        with api_key_override({"FAL_KEY": "user-a-key"}):
            t = threading.Thread(target=other_job)
            t.start()
            t.join()

        assert seen["key"] == "env-key"


class TestAdaptersReadThroughResolver:
    def test_flux_require_api_key_honours_override(self, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "env-key")
        from autonomous.ai.models.flux import FluxAIModel
        model = FluxAIModel.__new__(FluxAIModel)
        assert FluxAIModel._require_api_key(model) == "env-key"
        with api_key_override({"FAL_KEY": "user-key"}):
            assert FluxAIModel._require_api_key(model) == "user-key"

    def test_flux_declares_its_credential_env_var(self):
        from autonomous.ai.models.flux import FluxAIModel
        assert FluxAIModel.API_KEY_ENV == "FAL_KEY"

    def test_every_adapter_declares_its_credential_env_var(self):
        # client_key_scope maps client -> credential via this attribute; an
        # adapter that forgets it silently ignores every override.
        from autonomous.ai.models.flux import FluxAIModel
        from autonomous.ai.models.gemini import GeminiAIModel
        from autonomous.ai.models.litellm import LiteLLMImageModel
        from autonomous.ai.models.local_model import LocalAIModel
        from autonomous.ai.models.openai_compat import OpenAIClient

        assert FluxAIModel.API_KEY_ENV == "FAL_KEY"
        assert GeminiAIModel.API_KEY_ENV == "GOOGLEAI_KEY"
        assert OpenAIClient.API_KEY_ENV == "HPC_API_KEY"
        assert LiteLLMImageModel.API_KEY_ENV == "LITELLM_API_KEY"
        assert LocalAIModel.API_KEY_ENV == "ORIN_VOICE_TOKEN"

    def test_openai_compat_headers_use_override(self, monkeypatch):
        from autonomous.ai.models.openai_compat import OpenAIClient
        model = OpenAIClient.__new__(OpenAIClient)
        monkeypatch.setattr(OpenAIClient, "_api_key", "class-attr-key")
        assert "class-attr-key" in OpenAIClient._headers(model)["Authorization"]
        with api_key_override({"HPC_API_KEY": "user-key"}):
            assert "user-key" in OpenAIClient._headers(model)["Authorization"]

    def test_gemini_builds_a_fresh_client_for_an_override(self, monkeypatch):
        # The memoized ``self._client`` must NOT be reused (it holds the
        # platform key) and the per-call client must NOT be memoized onto
        # the instance (it holds a user's secret).
        from autonomous.ai.models import gemini as gemini_mod

        built = []

        class _FakeClient:
            def __init__(self, api_key=None):
                built.append(api_key)

        monkeypatch.setattr(gemini_mod.genai, "Client", _FakeClient)
        monkeypatch.setenv("GOOGLEAI_KEY", "platform-key")
        model = gemini_mod.GeminiAIModel.__new__(gemini_mod.GeminiAIModel)
        model._client = None

        model.client
        assert built == ["platform-key"]
        memoized = model._client

        with api_key_override({"GOOGLEAI_KEY": "user-key"}):
            model.client
        assert built == ["platform-key", "user-key"]
        assert model._client is memoized


class TestAgentKwargReachesAdapter:
    """Each agent entry point accepts ``api_key=`` and binds it.

    The agent methods are exercised as plain functions on a shim object
    rather than on a real ``Document`` instance: ``AutoModel.__new__``
    without ``__init__`` leaves the mongoengine field descriptors without
    ``_initialised``, so even reading ``self.provider`` raises. The shim
    supplies exactly what the method bodies touch, so what is under test
    is the real body, not a reimplementation.
    """

    @staticmethod
    def _shim(agent_cls, method_name):
        seen = {}

        class _Client:
            API_KEY_ENV = "FAL_KEY"

            def _record(self, *a, **kw):
                seen["vars"] = active_override_vars()
                seen["key"] = resolve_api_key("FAL_KEY")
                # Valid JSON so JSONAgent's post-dispatch json.loads of a
                # string result succeeds; every other agent passes it through.
                return "{}"

            def __getattr__(self, name):
                return self._record

        class _Shim:
            provider = "flux"

            def get_client(self, *a, **kw):
                return _Client()

            def add_to_job_meta(self, *a, **kw):
                pass

        setattr(_Shim, method_name, getattr(agent_cls, method_name))
        return _Shim(), seen

    @pytest.mark.parametrize(
        "module,cls_name,method,args",
        [
            ("textagent", "TextAgent", "generate", ("hello",)),
            ("textagent", "TextAgent", "summarize_text", ("some text",)),
            ("jsonagent", "JSONAgent", "generate", ("hello",)),
            ("audioagent", "AudioAgent", "generate", ("hello",)),
            ("audioagent", "AudioAgent", "transcribe", (b"\x00",)),
            ("audioagent", "AudioAgent", "dramatize", ("a transcript",)),
        ],
    )
    def test_api_key_kwarg_is_bound_for_the_call(
        self, module, cls_name, method, args, monkeypatch
    ):
        monkeypatch.setenv("FAL_KEY", "env-key")
        mod = __import__(f"autonomous.ai.{module}", fromlist=[cls_name])
        agent, seen = self._shim(getattr(mod, cls_name), method)

        getattr(agent, method)(*args, api_key="user-key")

        assert seen["key"] == "user-key", f"{cls_name}.{method} dropped api_key"
        # And it must not still be bound after the call returns.
        assert active_override_vars() == []

    def test_api_key_defaults_to_none_and_uses_env(self, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "env-key")
        from autonomous.ai.textagent import TextAgent
        agent, seen = self._shim(TextAgent, "generate")
        agent.generate("hello")
        assert seen["key"] == "env-key"
        assert seen["vars"] == []

    def test_every_agent_entry_point_accepts_api_key(self):
        # Guards the surface itself: a new agent method that forgets the
        # kwarg is a silent BYOK hole, not a test failure elsewhere.
        import inspect

        from autonomous.ai.audioagent import AudioAgent
        from autonomous.ai.imageagent import ImageAgent
        from autonomous.ai.jsonagent import JSONAgent
        from autonomous.ai.textagent import TextAgent

        entry_points = [
            (TextAgent, "generate"),
            (TextAgent, "summarize_text"),
            (JSONAgent, "generate"),
            (AudioAgent, "generate"),
            (AudioAgent, "transcribe"),
            (AudioAgent, "dramatize"),
            (ImageAgent, "generate"),
            (ImageAgent, "upscale"),
        ]
        missing = [
            f"{c.__name__}.{m}"
            for c, m in entry_points
            if "api_key" not in inspect.signature(getattr(c, m)).parameters
        ]
        assert not missing, f"missing api_key kwarg: {missing}"


class TestCredentialScopeBindsOnlyOneProvider:
    """``client_key_scope`` binds the client's env var and no other.

    This is the mechanism test. Binding a bare scalar — "the current call
    uses key K" — would hand a user's ``FAL_KEY`` to Google the moment
    ``ImageAgent`` fell back to Gemini. Keying on the adapter's own
    ``API_KEY_ENV`` makes that structurally impossible rather than merely
    unlikely.
    """

    def test_only_the_clients_env_var_is_bound(self, monkeypatch):
        monkeypatch.setenv("GOOGLEAI_KEY", "platform-google-key")

        class _Flux:
            API_KEY_ENV = "FAL_KEY"

        with client_key_scope(_Flux(), "user-fal-key"):
            assert active_override_vars() == ["FAL_KEY"]
            assert resolve_api_key("GOOGLEAI_KEY") == "platform-google-key"

    def test_client_without_a_credential_is_a_noop(self):
        # mock_model has no credential at all; binding ``None`` as a key
        # would poison the dict and shadow a real lookup.
        with client_key_scope(object(), "user-key"):
            assert active_override_vars() == []


class TestImageAgentFallbackLegIsNotOverridden:
    """End-to-end: the fallback provider never sees the caller's key.

    ``ImageAgent.generate`` re-routes FLUX → Gemini when the primary call
    raises (e.g. a safety block, #226). Two independent things keep the
    caller's key off that leg — the binding is keyed to FLUX's env var
    (pinned above), *and* the ``with`` block closes before the ``except``
    branch runs. This test pins the observable guarantee, so a refactor
    that loses either one has to lose both silently to go unnoticed.
    """

    def test_fallback_provider_reads_its_own_credential(self, monkeypatch):
        from autonomous.ai.imageagent import ImageAgent

        monkeypatch.setenv("GOOGLEAI_KEY", "platform-google-key")
        seen = {}

        class _Flux:
            API_KEY_ENV = "FAL_KEY"

            def generate_image(self, *a, **kw):
                seen["flux"] = resolve_api_key("FAL_KEY")
                raise RuntimeError("safety block")

        class _Gemini:
            API_KEY_ENV = "GOOGLEAI_KEY"

            def generate_image(self, *a, **kw):
                seen["gemini"] = resolve_api_key("GOOGLEAI_KEY")
                return b"gemini-bytes"

        class _Shim:
            provider = "flux"
            generate = ImageAgent.generate
            _resolve_aspect_ratio = lambda self, r, q: r
            _route_provider = lambda self, r, **kw: "flux"
            _resolve_fallback = lambda self, fb: "gemini"
            _estimate_cost_usd = lambda self, p, s: 0.0

            def get_client(self, provider):
                return _Flux() if provider == "flux" else _Gemini()

            def add_to_job_meta(self, *a, **kw):
                pass

        monkeypatch.setattr(
            "autonomous.ai.imageagent.image_cache.get", lambda *a, **kw: None
        )
        monkeypatch.setattr(
            "autonomous.ai.imageagent.image_cache.put", lambda *a, **kw: None
        )

        _Shim().generate("a prompt", api_key="user-fal-key")

        assert seen["flux"] == "user-fal-key"
        assert seen["gemini"] == "platform-google-key", (
            "the caller's fal.ai key leaked onto the Gemini fallback leg"
        )


class TestWorkerThreadRebinding:
    """Gemini's orphan-cleanup pool re-binds the caller's key (#227).

    A ContextVar does not cross into a worker thread, so without a
    re-bind those cleanup deletes authenticate with the deployment key
    while the upload that created the files used the caller's — leaving
    orphans stranded in the caller's account.

    Pinned separately because the obvious implementation
    (``contextvars.copy_context()`` shared across the pool) raises at
    runtime: one Context cannot be entered by several threads at once.
    """

    def test_snapshot_rebinding_works_across_threads(self, monkeypatch):
        from concurrent.futures import ThreadPoolExecutor

        from autonomous.ai._credentials import current_overrides

        monkeypatch.setenv("GOOGLEAI_KEY", "platform-key")
        seen = []

        with api_key_override({"GOOGLEAI_KEY": "user-key"}):
            overrides = current_overrides()

            def _work(_):
                with api_key_override(overrides):
                    seen.append(resolve_api_key("GOOGLEAI_KEY"))

            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(_work, range(8)))

        assert seen == ["user-key"] * 8
