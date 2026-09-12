"""Independent coverage for PR #252 (closes #248): per-call sampling knobs
``frequency_penalty`` / ``presence_penalty`` / ``top_p`` / ``seed``.

Written from the PR diff alone (two-perspective rule).

Pinned, and why each matters:

- **Agents forward only what the caller SET.** ``None`` is "no override";
  a falsy-but-set value (``0``, ``0.0``) is a real override and must reach
  the adapter — the classic ``if knob:`` regression.
- **``openai_compat``** carries the knobs on the primary ``_chat`` leg AND
  on both strict→loose fallback legs (HTTP-4xx and parse-failure-200);
  unset knobs never reach the payload.
- **``gemini``** honors ``top_p`` / ``seed`` and DROPS the penalties with
  a log line, once per distinct dropped set (the 2.5 models 400 on them).
- **``local``** merges into Ollama ``options``; a set ``top_p`` overrides
  the hardcoded 0.95; a set ``seed`` steps 42 → 43 → 44 across the JSON
  parse-failure retries but NOT across a transport failure (nothing was
  sampled); a non-int seed is left alone; an unset seed is never sent
  and never stepped.
- **Every registry adapter binds all four** on ``generate_text`` /
  ``generate_json`` (a per-call ``provider=`` switch can't TypeError), and
  the image-only adapters still raise the typed ``NotSupportedByProvider``.
- ``sampling_overrides`` is the single None-dropping site.

The committed drift guard for ``generate_text`` (outside
``AIModelProtocol``) is ``AGENT_CALL_KWARGS`` in
``test_unit_adapter_signature_parity_iter_2026_08_25.py``, extended in
this bundle with the four names.
"""

import inspect
from unittest.mock import MagicMock, patch

import pytest
import requests

from autonomous.ai.baseagent import BaseAgent
from autonomous.ai.jsonagent import JSONAgent
from autonomous.ai.models import gemini as gemini_module
from autonomous.ai.models.gemini import GeminiAIModel
from autonomous.ai.models.local_model import LocalAIModel
from autonomous.ai.models.mock_model import MockAIModel
from autonomous.ai.models.openai_compat import OpenAIClient
from autonomous.ai.protocol import NotSupportedByProvider, sampling_overrides
from autonomous.ai.textagent import TextAgent

KNOBS = {
    "frequency_penalty": 0.5,
    "presence_penalty": 0.25,
    "top_p": 0.9,
    "seed": 42,
}
KNOB_NAMES = tuple(KNOBS)
PENALTIES = {"frequency_penalty", "presence_penalty"}


def _bare(cls, **attrs):
    """An adapter / agent instance without AutoModel construction."""
    inst = cls.__new__(cls)
    object.__setattr__(
        inst,
        "_data",
        {
            "instructions": "test instructions",
            "name": "t",
            "provider": "mock",
            "description": "d",
        },
    )
    object.__setattr__(inst, "_dynamic_fields", {})
    object.__setattr__(inst, "_changed_fields", [])
    object.__setattr__(inst, "_initialised", True)
    object.__setattr__(inst, "_created", False)
    for key, val in attrs.items():
        object.__setattr__(inst, key, val)
    return inst


def _knobs_in(mapping):
    return {k: mapping[k] for k in KNOB_NAMES if k in mapping}


# ---------------------------------------------------------------------------
# The helper
# ---------------------------------------------------------------------------


class TestSamplingOverridesHelper:
    def test_no_args_is_empty(self):
        assert sampling_overrides() == {}

    def test_nones_are_dropped_and_zeros_are_kept(self):
        assert sampling_overrides(0.0, None, None, 0) == {
            "frequency_penalty": 0.0,
            "seed": 0,
        }

    def test_uses_the_openai_names(self):
        assert sampling_overrides(**KNOBS) == KNOBS


# ---------------------------------------------------------------------------
# Agents: forward only what was set
# ---------------------------------------------------------------------------

AGENTS = [(TextAgent, "generate_text"), (JSONAgent, "generate_json")]


def _agent_sends(agent_cls, client_method, **kwargs):
    agent = _bare(agent_cls)
    client = MagicMock()
    getattr(client, client_method).return_value = (
        {"k": "v"} if client_method == "generate_json" else "text"
    )
    with patch.object(agent, "get_client", return_value=client), patch.object(
        agent, "add_to_job_meta"
    ):
        agent.generate("hello", **kwargs)
    return getattr(client, client_method).call_args.kwargs


class TestAgentsForwardOnlySetKnobs:
    @pytest.mark.parametrize("agent_cls,client_method", AGENTS)
    def test_all_four_forwarded_when_set(self, agent_cls, client_method):
        assert _knobs_in(_agent_sends(agent_cls, client_method, **KNOBS)) == KNOBS

    @pytest.mark.parametrize("agent_cls,client_method", AGENTS)
    def test_none_forwarded_when_unset(self, agent_cls, client_method):
        assert _knobs_in(_agent_sends(agent_cls, client_method)) == {}

    @pytest.mark.parametrize("agent_cls,client_method", AGENTS)
    def test_partial_set_forwards_only_that_knob(self, agent_cls, client_method):
        assert _knobs_in(_agent_sends(agent_cls, client_method, seed=7)) == {"seed": 7}

    @pytest.mark.parametrize("agent_cls,client_method", AGENTS)
    def test_falsy_but_set_values_are_forwarded(self, agent_cls, client_method):
        # 0 / 0.0 are real overrides ("no penalty", "seed 0"); only None
        # means "unset".
        zeros = {"frequency_penalty": 0.0, "presence_penalty": 0.0, "top_p": 0.0, "seed": 0}
        assert _knobs_in(_agent_sends(agent_cls, client_method, **zeros)) == zeros


# ---------------------------------------------------------------------------
# openai_compat: every _chat leg
# ---------------------------------------------------------------------------


def _openai():
    return _bare(
        OpenAIClient,
        _base_url="http://mock-hpc/api",
        _api_key="test-key",
        _json_model="knobs-json-model",
        _text_model="knobs-text-model",
        _timeout=1,
        _retry_attempts=1,
        _retry_backoff=0,
    )


def _chat_ok(content):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"choices": [{"message": {"content": content}}]}
    response.raise_for_status.return_value = None
    return response


def _strict_unsupported_400():
    response = MagicMock()
    response.status_code = 400
    response.text = "response_format is not supported by this endpoint"
    return requests.HTTPError("400 Bad Request", response=response)


_OPENAI_POST = "autonomous.ai.models.openai_compat._HTTP.post"


class TestOpenAICompatPayload:
    @pytest.fixture(autouse=True)
    def _silence_autotasks(self):
        with patch("autonomous.ai.models.openai_compat.AutoTasks") as tasks:
            tasks.return_value.get_current_task.return_value = None
            yield

    def test_generate_text_payload_carries_set_knobs(self):
        with patch(_OPENAI_POST, return_value=_chat_ok("hi")) as post:
            _openai().generate_text("hello", **KNOBS)
        assert _knobs_in(post.call_args.kwargs["json"]) == KNOBS

    def test_generate_text_payload_omits_unset_knobs(self):
        with patch(_OPENAI_POST, return_value=_chat_ok("hi")) as post:
            _openai().generate_text("hello", seed=3)
        assert _knobs_in(post.call_args.kwargs["json"]) == {"seed": 3}

    @pytest.mark.parametrize("json_schema", [{"type": "object"}, None])
    def test_generate_json_primary_leg_carries_knobs(self, json_schema):
        with patch(_OPENAI_POST, return_value=_chat_ok('{"k": "v"}')) as post:
            _openai().generate_json("x", json_schema=json_schema, **KNOBS)
        assert _knobs_in(post.call_args.kwargs["json"]) == KNOBS

    def test_generate_json_omits_unset_knobs(self):
        with patch(_OPENAI_POST, return_value=_chat_ok('{"k": "v"}')) as post:
            _openai().generate_json("x")
        assert _knobs_in(post.call_args.kwargs["json"]) == {}

    def test_http_fallback_leg_keeps_the_knobs(self):
        with patch(
            _OPENAI_POST, side_effect=[_strict_unsupported_400(), _chat_ok('{"k": "v"}')]
        ) as post:
            result = _openai().generate_json(
                "x", json_schema={"type": "object"}, model="knobs-http-fallback", **KNOBS
            )
        assert result == {"k": "v"}
        assert post.call_count == 2
        strict_body, loose_body = (c.kwargs["json"] for c in post.call_args_list)
        assert strict_body["response_format"]["type"] == "json_schema"
        assert loose_body["response_format"] == {"type": "json_object"}
        assert _knobs_in(strict_body) == KNOBS
        assert _knobs_in(loose_body) == KNOBS

    def test_parse_failure_fallback_leg_keeps_the_knobs(self):
        with patch(
            _OPENAI_POST,
            side_effect=[_chat_ok("definitely not json"), _chat_ok('{"k": "v"}')],
        ) as post:
            result = _openai().generate_json(
                "x", json_schema={"type": "object"}, model="knobs-parse-fallback", **KNOBS
            )
        assert result == {"k": "v"}
        assert post.call_count == 2
        strict_body, loose_body = (c.kwargs["json"] for c in post.call_args_list)
        assert strict_body["response_format"]["type"] == "json_schema"
        assert loose_body["response_format"] == {"type": "json_object"}
        assert _knobs_in(strict_body) == KNOBS
        assert _knobs_in(loose_body) == KNOBS


# ---------------------------------------------------------------------------
# gemini: top_p / seed in, penalties dropped with a log line
# ---------------------------------------------------------------------------


def _gemini():
    return _bare(
        GeminiAIModel,
        _client=MagicMock(),
        _text_model="gemini-test",
        _json_model="gemini-test",
    )


class TestGeminiConfig:
    @pytest.fixture(autouse=True)
    def _fresh_warned_set(self):
        # The drop warning fires once per distinct set per process; start
        # each test from a clean slate so ordering can't hide it.
        with patch.object(gemini_module, "_DROPPED_KNOBS_WARNED", set()):
            yield

    def _text_config(self, **kwargs):
        model = _gemini()
        response = MagicMock()
        response.text = "hello"
        model._client.models.generate_content.return_value = response
        with patch("autonomous.ai.models.gemini.log") as log:
            model.generate_text("hi", **kwargs)
        config = model._client.models.generate_content.call_args.kwargs["config"]
        return config, log

    def test_top_p_and_seed_reach_the_config(self):
        config, _ = self._text_config(top_p=0.9, seed=42)
        assert config.top_p == pytest.approx(0.9)
        assert config.seed == 42

    def test_penalties_are_dropped_with_a_log_line(self):
        config, log = self._text_config(**KNOBS)
        assert config.top_p == pytest.approx(0.9)
        assert config.seed == 42
        assert config.frequency_penalty is None
        assert config.presence_penalty is None
        logged = " ".join(str(call) for call in log.call_args_list)
        assert "frequency_penalty" in logged
        assert "presence_penalty" in logged

    def test_no_drop_log_when_penalties_unset(self):
        _, log = self._text_config(top_p=0.5)
        assert not any("ignoring" in str(call) for call in log.call_args_list)

    def test_drop_log_fires_once_per_distinct_dropped_set(self):
        model = _gemini()
        response = MagicMock()
        response.text = "hello"
        model._client.models.generate_content.return_value = response
        with patch("autonomous.ai.models.gemini.log") as log:
            model.generate_text("hi", **KNOBS)
            model.generate_text("hi", **KNOBS)
            model.generate_text("hi", frequency_penalty=0.5)
        drops = [c for c in log.call_args_list if "ignoring" in str(c)]
        assert len(drops) == 2
        assert "presence_penalty" in str(drops[0])
        assert "presence_penalty" not in str(drops[1])

    def test_unset_knobs_leave_the_config_defaults(self):
        config, _ = self._text_config()
        assert config.top_p is None
        assert config.seed is None

    def test_generate_json_config_gets_top_p_and_seed_not_penalties(self):
        model = _gemini()
        response = MagicMock()
        response.candidates[0].content.parts[0].function_call.name = "response"
        response.candidates[0].content.parts[0].function_call.args = {"k": "v"}
        model._client.models.generate_content.return_value = response
        with patch("autonomous.ai.models.gemini.log"):
            result = model.generate_json(
                "hi", json_schema={"type": "object", "properties": {}}, **KNOBS
            )
        assert result == {"k": "v"}
        config = model._client.models.generate_content.call_args.kwargs["config"]
        assert config.top_p == pytest.approx(0.9)
        assert config.seed == 42
        assert config.frequency_penalty is None
        assert config.presence_penalty is None


# ---------------------------------------------------------------------------
# local: Ollama options + seed stepping per JSON retry
# ---------------------------------------------------------------------------


def _local():
    return _bare(
        LocalAIModel,
        _ollama_url="http://ollama-test",
        _text_model="test-model",
        _context_limit=4096,
        _json_timeout=10,
        _text_timeout=10,
        _retry_sleep=0,
    )


def _ollama_ok(content):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"message": {"content": content}}
    response.raise_for_status.return_value = None
    return response


_LOCAL_POST = "autonomous.ai.models.local_model._HTTP.post"


class TestLocalOptions:
    @pytest.fixture(autouse=True)
    def _hermetic(self, monkeypatch):
        # flush_memory does its own POST on every retry; keep it out of
        # the call log.
        monkeypatch.setattr(LocalAIModel, "flush_memory", lambda self, model: None)
        with patch("autonomous.ai.models.local_model.AutoTasks") as tasks:
            tasks.return_value.get_current_task.return_value = None
            yield

    def test_generate_json_options_carry_set_knobs_and_top_p_overrides_default(self):
        with patch(_LOCAL_POST, return_value=_ollama_ok('{"ok": 1}')) as post:
            _local().generate_json("x", **KNOBS)
        options = post.call_args.kwargs["json"]["options"]
        assert _knobs_in(options) == KNOBS
        assert options["top_p"] == pytest.approx(0.9)

    def test_generate_json_unset_knobs_keep_the_defaults(self):
        with patch(_LOCAL_POST, return_value=_ollama_ok('{"ok": 1}')) as post:
            _local().generate_json("x")
        options = post.call_args.kwargs["json"]["options"]
        assert options["top_p"] == pytest.approx(0.95)
        assert _knobs_in(options) == {"top_p": pytest.approx(0.95)}

    def test_generate_text_options_carry_set_knobs(self):
        with patch(_LOCAL_POST, return_value=_ollama_ok("hi")) as post:
            _local().generate_text("x", **KNOBS)
        options = post.call_args.kwargs["json"]["options"]
        assert _knobs_in(options) == KNOBS

    def test_generate_text_unset_knobs_keep_the_defaults(self):
        with patch(_LOCAL_POST, return_value=_ollama_ok("hi")) as post:
            _local().generate_text("x")
        options = post.call_args.kwargs["json"]["options"]
        assert _knobs_in(options) == {"top_p": pytest.approx(0.95)}

    @staticmethod
    def _retrying_post(seeds, outcomes=("not json", "still not json", '{"ok": 1}')):
        # The adapter mutates ONE payload dict across retries, so snapshot
        # the seed at call time rather than reading call_args afterwards.
        # An outcome that is an exception is raised in place of a response.
        outcomes = iter(outcomes)

        def post(_url, json=None, **_):
            seeds.append(json["options"].get("seed"))
            outcome = next(outcomes)
            if isinstance(outcome, BaseException):
                raise outcome
            return _ollama_ok(outcome)

        return post

    def test_set_seed_steps_by_one_per_json_retry(self):
        seeds = []
        with patch(_LOCAL_POST, side_effect=self._retrying_post(seeds)):
            assert _local().generate_json("x", seed=42) == {"ok": 1}
        assert seeds == [42, 43, 44]

    def test_unset_seed_is_never_sent_nor_stepped(self):
        seeds = []
        with patch(_LOCAL_POST, side_effect=self._retrying_post(seeds)):
            assert _local().generate_json("x") == {"ok": 1}
        assert seeds == [None, None, None]

    def test_transport_failure_does_not_step_the_seed(self):
        # Nothing was sampled on a connection error, so the SAME seed is
        # the reproducible retry; only a real parse failure steps it.
        seeds = []
        outcomes = (requests.ConnectionError("blip"), "not json", '{"ok": 1}')
        with patch(_LOCAL_POST, side_effect=self._retrying_post(seeds, outcomes)):
            assert _local().generate_json("x", seed=42) == {"ok": 1}
        assert seeds == [42, 42, 43]

    def test_non_int_seed_is_left_alone(self):
        seeds = []
        with patch(_LOCAL_POST, side_effect=self._retrying_post(seeds)):
            assert _local().generate_json("x", seed=4.5) == {"ok": 1}
        assert seeds == [4.5, 4.5, 4.5]


# ---------------------------------------------------------------------------
# Registry-wide acceptance
# ---------------------------------------------------------------------------


class TestEveryAdapterAcceptsTheKnobs:
    @pytest.mark.parametrize("method", ["generate_text", "generate_json"])
    @pytest.mark.parametrize("provider", sorted(BaseAgent.MODEL_REGISTRY))
    def test_signature_binds_all_four(self, provider, method):
        fn = getattr(BaseAgent.MODEL_REGISTRY[provider], method, None)
        if fn is None:
            pytest.skip(f"{provider} has no {method}")
        # bind() raises TypeError exactly when a real call would.
        inspect.signature(fn).bind(None, "message", **KNOBS)

    def test_mock_accepts_and_ignores(self):
        model = _bare(MockAIModel)
        assert isinstance(model.generate_text("p", **KNOBS), str)
        assert isinstance(model.generate_json("p", **KNOBS), dict)

    @pytest.mark.parametrize("provider", ["flux", "litellm"])
    def test_image_only_adapters_still_raise_the_typed_error(self, provider):
        cls = BaseAgent.MODEL_REGISTRY[provider]
        with pytest.raises(NotSupportedByProvider):
            cls.generate_json(cls.__new__(cls), "p", **KNOBS)
