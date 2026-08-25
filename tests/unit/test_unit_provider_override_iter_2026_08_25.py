"""Per-call ``provider=`` override on agent entry points (#239).

Independent coverage written from the PR #240 diff.

Unlike the #227 BYOK tests — which graft agent methods onto a hand-built
shim — these drive **real agent objects against the real
``MODEL_REGISTRY``**, stubbing only ``AutoTasks`` (whose
``get_current_task`` would open a Redis connection from
``add_to_job_meta``). Constructing an ``AutoModel`` does not touch Mongo,
so a real ``TextAgent`` is hermetic; that makes the assertions below
statements about shipped behavior rather than about a test double.

The properties under test:

- an override actually changes which adapter serves the call;
- it leaves NO trace: ``agent.client`` unmutated, nothing saved;
- ``None`` / ``""`` are byte-for-byte the previous env-derived path;
- an unknown name raises, and the message is actionable;
- ``provider`` composes with ``api_key`` — the key binds to the
  OVERRIDE provider's credential, not the deployment provider's.
"""

import inspect
from unittest.mock import patch

import pytest

import autonomous.ai.baseagent as baseagent_module
from autonomous.ai._credentials import active_override_vars, resolve_api_key
from autonomous.ai._routing import resolve_client
from autonomous.ai.audioagent import AudioAgent
from autonomous.ai.baseagent import BaseAgent
from autonomous.ai.jsonagent import JSONAgent
from autonomous.ai.models.gemini import GeminiAIModel
from autonomous.ai.models.local_model import LocalAIModel
from autonomous.ai.models.mock_model import MockAIModel
from autonomous.ai.textagent import TextAgent

TEXT_JSON_ENTRY_POINTS = [
    (TextAgent, "generate", ("hello",)),
    (TextAgent, "summarize_text", ("some text",)),
    (JSONAgent, "generate", ("hello",)),
]

ALL_ENTRY_POINTS = TEXT_JSON_ENTRY_POINTS + [
    (AudioAgent, "generate", ("hello",)),
    (AudioAgent, "transcribe", (b"\x00",)),
    (AudioAgent, "dramatize", ("a transcript",)),
]


@pytest.fixture(autouse=True)
def _no_redis():
    """``add_to_job_meta`` reaches Redis through AutoTasks. Stub it."""
    with patch.object(baseagent_module, "AutoTasks") as tasks:
        tasks.return_value.get_current_task.return_value = None
        yield tasks


def _agent(cls):
    return cls(name="t", instructions="i", description="d")


class TestOverrideChangesTheServingAdapter:
    def test_mock_provider_serves_a_text_call(self):
        agent = _agent(TextAgent)
        assert agent.provider == "local"
        result = agent.generate("hello", provider="mock")
        # MockAIModel's canned lorem-ipsum body — proof the call was
        # served by the OVERRIDE adapter, not the agent's own "local".
        assert "Lorem ipsum" in result

    def test_json_call_is_served_by_the_override(self):
        agent = _agent(JSONAgent)
        result = agent.generate("hello", provider="mock")
        assert isinstance(result, dict)

    @pytest.mark.parametrize("cls,method,args", ALL_ENTRY_POINTS)
    def test_env_var_is_not_consulted_when_overridden(
        self, cls, method, args, monkeypatch
    ):
        # Every role env var set to a DIFFERENT provider. If any entry
        # point still read its env var, dispatch would land on gemini
        # (which would try to build a real SDK client).
        for var in (
            "TEXT_AI_AGENT",
            "SUMMARY_AI_AGENT",
            "JSON_AI_AGENT",
            "TTS_AI_AGENT",
            "TRANSCRIBE_AI_AGENT",
        ):
            monkeypatch.setenv(var, "gemini")
        agent = _agent(cls)
        seen = {}

        class _Probe(MockAIModel):
            def __getattribute__(self, name):
                if name.startswith("generate") or name == "summarize_text":
                    seen["called"] = name
                return super().__getattribute__(name)

        monkeypatch.setitem(cls.MODEL_REGISTRY, "probe", _Probe)
        getattr(agent, method)(*args, provider="probe")
        assert seen.get("called"), f"{cls.__name__}.{method} did not dispatch"


class TestOverrideLeavesNoTrace:
    """The load-bearing property. Agent docs are shared across concurrent
    RQ jobs, so a per-call override that mutated or persisted the agent
    would hand one user's provider to the next user's job."""

    @pytest.mark.parametrize("cls,method,args", ALL_ENTRY_POINTS)
    def test_agent_client_is_not_mutated(self, cls, method, args):
        agent = _agent(cls)
        assert agent.client is None
        getattr(agent, method)(*args, provider="mock")
        assert agent.client is None, "override leaked onto the agent"

    @pytest.mark.parametrize("cls,method,args", ALL_ENTRY_POINTS)
    def test_nothing_is_saved(self, cls, method, args):
        agent = _agent(cls)
        with patch.object(type(agent), "save") as agent_save, patch.object(
            MockAIModel, "save"
        ) as client_save:
            getattr(agent, method)(*args, provider="mock")
        assert not agent_save.called, "override saved the agent"
        assert not client_save.called, "override persisted a client doc"

    def test_agent_provider_field_is_unchanged(self):
        agent = _agent(TextAgent)
        agent.generate("hello", provider="mock")
        assert agent.provider == "local"

    def test_two_overrides_in_a_row_do_not_bleed(self):
        # Sequential calls with different providers must be independent —
        # the concurrent-worker hazard in miniature.
        agent = _agent(TextAgent)
        first = resolve_client(agent, "mock", "TEXT_AI_AGENT")
        second = resolve_client(agent, "local", "TEXT_AI_AGENT")
        assert isinstance(first, MockAIModel)
        assert isinstance(second, LocalAIModel)
        assert first is not second
        assert agent.client is None


class TestDefaultPathIsUnchanged:
    @pytest.mark.parametrize("unset", [None, ""])
    @pytest.mark.parametrize("cls,method,args", ALL_ENTRY_POINTS)
    def test_no_override_uses_get_client_with_the_env_provider(
        self, cls, method, args, unset, monkeypatch
    ):
        monkeypatch.setenv("TEXT_AI_AGENT", "mock")
        monkeypatch.setenv("SUMMARY_AI_AGENT", "mock")
        monkeypatch.setenv("JSON_AI_AGENT", "mock")
        monkeypatch.setenv("TTS_AI_AGENT", "mock")
        monkeypatch.setenv("TRANSCRIBE_AI_AGENT", "mock")
        agent = _agent(cls)
        seen = {}

        def _fake_get_client(self, provider=None, **kw):
            seen["provider"] = provider
            return MockAIModel(name="m", instructions="i", description="d")

        monkeypatch.setattr(BaseAgent, "get_client", _fake_get_client)
        getattr(agent, method)(*args, provider=unset)
        # Resolved through get_client — the persisted, env-derived path.
        assert seen["provider"] == "mock"

    def test_agent_provider_field_is_the_fallback_when_env_is_absent(
        self, monkeypatch
    ):
        for var in ("TEXT_AI_AGENT", "SUMMARY_AI_AGENT"):
            monkeypatch.delenv(var, raising=False)
        agent = _agent(TextAgent)
        agent.provider = "mock"
        seen = {}

        def _fake_get_client(self, provider=None, **kw):
            seen["provider"] = provider
            return MockAIModel(name="m", instructions="i", description="d")

        monkeypatch.setattr(BaseAgent, "get_client", _fake_get_client)
        agent.generate("hello")
        assert seen["provider"] == "mock"


class TestUnknownProviderRaises:
    @pytest.mark.parametrize("cls,method,args", ALL_ENTRY_POINTS)
    def test_raises_value_error(self, cls, method, args):
        agent = _agent(cls)
        with pytest.raises(ValueError):
            getattr(agent, method)(*args, provider="anthropc")

    def test_message_names_the_bad_value_and_the_valid_ones(self):
        agent = _agent(TextAgent)
        with pytest.raises(ValueError) as exc:
            agent.generate("hello", provider="anthropc")
        msg = str(exc.value)
        assert "anthropc" in msg, "the rejected name must be echoed back"
        # An error a consumer can act on lists what IS accepted.
        for known in ("gemini", "local", "mock", "openai"):
            assert known in msg, f"valid provider {known!r} missing from {msg!r}"

    def test_it_does_not_silently_fall_back_to_local(self):
        # get_client's MODEL_REGISTRY.get(..., LocalAIModel) behavior is
        # exactly what the per-call kwarg must NOT inherit: a consumer
        # forwarding an end user's choice needs the rejection.
        agent = _agent(TextAgent)
        with pytest.raises(ValueError):
            resolve_client(agent, "nonesuch", "TEXT_AI_AGENT")

    def test_env_derived_path_keeps_its_silent_fallback(self, monkeypatch):
        # Deliberately asymmetric — pinned so a future "make it strict
        # everywhere" change is a conscious decision, not a surprise.
        # ``get_client``'s slow path SAVES (agent + client), so the saves
        # are stubbed: this is a unit test and there is no Mongo.
        monkeypatch.setenv("TEXT_AI_AGENT", "nonesuch")
        agent = _agent(TextAgent)
        monkeypatch.setattr(TextAgent, "save", lambda self, *a, **kw: None)
        monkeypatch.setattr(LocalAIModel, "save", lambda self, *a, **kw: None)
        client = resolve_client(agent, None, "TEXT_AI_AGENT")
        assert isinstance(client, LocalAIModel)


class TestComposesWithApiKey:
    """The reason #239 exists: this user's provider, this user's key."""

    @pytest.mark.parametrize("cls,method,args", ALL_ENTRY_POINTS)
    def test_key_binds_to_the_override_providers_credential(
        self, cls, method, args, monkeypatch
    ):
        monkeypatch.setenv("FAL_KEY", "deployment-fal")
        monkeypatch.setenv("GOOGLEAI_KEY", "deployment-google")
        seen = {}

        class _Probe(MockAIModel):
            API_KEY_ENV = "GOOGLEAI_KEY"

            def __getattribute__(self, name):
                if name.startswith("generate") or name == "summarize_text":
                    seen["google"] = resolve_api_key("GOOGLEAI_KEY")
                    seen["fal"] = resolve_api_key("FAL_KEY")
                return super().__getattribute__(name)

        monkeypatch.setitem(cls.MODEL_REGISTRY, "probe", _Probe)
        agent = _agent(cls)
        getattr(agent, method)(*args, provider="probe", api_key="user-key")

        assert seen["google"] == "user-key", "key did not reach the override"
        # A key issued for one provider must not reach another.
        assert seen["fal"] == "deployment-fal"
        # And the binding unwinds.
        assert active_override_vars() == []


class TestPublicSurface:
    @pytest.mark.parametrize("cls,method,args", ALL_ENTRY_POINTS)
    def test_entry_point_accepts_provider_defaulting_to_none(
        self, cls, method, args
    ):
        param = inspect.signature(getattr(cls, method)).parameters.get("provider")
        assert param is not None, f"{cls.__name__}.{method} lacks provider="
        assert param.default is None

    def test_existing_positional_calls_still_map_to_the_same_params(
        self, monkeypatch
    ):
        # Backward compatibility: provider was APPENDED, so a pre-#239
        # positional call must still land on the SAME parameters — a
        # reordered signature would silently pass "uri" as context.
        seen = {}

        class _Recorder(MockAIModel):
            def generate_text(self, message, additional_instructions="", **kw):
                seen.update(kw)
                seen["message"] = message
                seen["additional_instructions"] = additional_instructions
                return "ok"

        monkeypatch.setattr(
            BaseAgent,
            "get_client",
            lambda self, provider=None, **kw: _Recorder(
                name="m", instructions="i", description="d"
            ),
        )
        agent = _agent(TextAgent)
        agent.generate("msg", "extra instructions", "uri", "context")

        assert seen["message"] == "msg"
        assert seen["additional_instructions"] == "extra instructions"
        assert seen["uri"] == "uri"
        assert seen["context"] == "context"

    def test_image_agent_is_untouched(self):
        # #239 is explicitly text/JSON/audio — ImageAgent already routes
        # per call via route=/fallback_provider=. If someone adds
        # provider= there later it should be a deliberate change with its
        # own MIGRATIONS note, not a silent drift from this one.
        from autonomous.ai.imageagent import ImageAgent

        params = inspect.signature(ImageAgent.generate).parameters
        assert "route" in params and "fallback_provider" in params


class TestGeminiTransientClientLeavesNoDoc:
    """``_add_files`` ended in an unconditional ``self.save()``. On a
    transient override client that INSERTS one unreferenced doc per call
    carrying ``context`` — invisible until the collection is huge."""

    @staticmethod
    def _stub_sdk(monkeypatch):
        from types import SimpleNamespace

        handle = SimpleNamespace(name="f1", state=SimpleNamespace(name="ACTIVE"))
        files = SimpleNamespace(
            delete=lambda **kw: None,
            upload=lambda **kw: handle,
            get=lambda **kw: handle,
            list=lambda: [handle],
        )
        monkeypatch.setattr(
            GeminiAIModel,
            "client",
            property(lambda self: SimpleNamespace(files=files)),
        )
        saves = []
        monkeypatch.setattr(
            GeminiAIModel, "save", lambda self, *a, **kw: saves.append(1)
        )
        return saves

    def test_unsaved_client_does_not_insert(self, monkeypatch):
        saves = self._stub_sdk(monkeypatch)
        model = GeminiAIModel(name="x", instructions="i", description="d")
        assert model.pk is None
        model._add_files([{"name": "context-None", "file": b"{}"}])
        assert saves == [], "a transient client inserted a document"
        # The in-memory bookkeeping still runs; only the write is skipped.
        assert model.file_refs == ["f1"]

    def test_persisted_client_still_saves(self, monkeypatch):
        from bson import ObjectId

        saves = self._stub_sdk(monkeypatch)
        model = GeminiAIModel(name="x", instructions="i", description="d")
        model.pk = ObjectId()
        model._add_files([{"name": "context-1", "file": b"{}"}])
        assert saves == [1], "the guard suppressed a real client's save"
