"""Independent second-perspective coverage for PR #163's three audit
follow-ups — TextAgent system_prompt= (#140), image-config dedup (#149),
and QuerySet.snapshot() removal (#154).

These tests are written from a fresh read of the PR diff with no peek
at the dev-agent's ephemerals in tests/_dev_local/. Per CLAUDE.md
"Two-perspective testing", they intentionally hit the **shared / new
surfaces** that the existing in-tree tests do not cover:

* `_image_utils.resolve_image_config` — the new canonical vocabulary
  module (existing test_unit_flux.py::TestGetImageConfig already pins
  flux's per-provider wire shape, which is the dev-side regression
  check; this file pins the shared vocabulary directly so a refactor
  that re-inlines the parse per-provider has to confront the contract).
* `gemini._GEMINI_SIZE_BY_TIER` + the 4K-clamp breadcrumb — issues #29
  and #30; no existing test exercises gemini's _get_image_config.
* `system_prompt=` semantics on all four `generate_text` adapters —
  pre-#140 the only system_prompt coverage was on generate_json
  (test_unit_gemini_translation_iter_2026_06_14.py + json_schema
  structured-outputs); generate_text was completely uncovered.
  CRITICAL: pins the documented asymmetry — openai_compat/gemini
  REPLACE the persona, local_model PREPENDS without using the persona
  at all (MIGRATIONS.md #140). A future "harmonize the inconsistency"
  PR has to confront these explicit pins.
* `QuerySet.snapshot()` AttributeError and `_snapshot` instance-state
  absence — issue #154; no existing snapshot tests on QuerySet.

All tests are hermetic — no Mongo, no Redis, no Ollama, no Gemini,
no Flux. Adapters are exercised either by stubbing the SDK client
(gemini) or by monkeypatching the HttpClient.post used by
openai_compat/local_model — never via network."""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# A) `_image_utils.resolve_image_config` — canonical vocabulary contract
# ---------------------------------------------------------------------------


class TestResolveImageConfigTable:
    """Pin the full canonical vocabulary table. The shared module's
    public contract is `aspect_ratio_input → (ratio, tier)`. Each
    adapter then translates the tier to its wire shape. A regression
    here propagates silently into Flux's `_FLUX_SIZE_BY_RATIO_TIER.get`
    and Gemini's `_GEMINI_SIZE_BY_TIER.get` — both `.get` calls fall
    back on miss, so a wrong tier produces a default size rather than
    a crash."""

    @pytest.mark.parametrize(
        "input_key,expected",
        [
            ("Portrait",   ("3:4",  "low")),
            ("Landscape",  ("16:9", "low")),
            ("2K",         ("16:9", "2K")),
            ("2KPortrait", ("3:4",  "2K")),
            ("4K",         ("16:9", "4K")),
            ("Map",        ("16:9", "4K")),
            ("4KPortrait", ("3:4",  "4K")),
        ],
    )
    def test_named_keys_resolve_to_documented_pair(self, input_key, expected):
        from autonomous.ai._image_utils import resolve_image_config
        assert resolve_image_config(input_key) == expected

    @pytest.mark.parametrize(
        "bare_ratio", ["1:1", "3:4", "4:3", "9:16", "16:9"]
    )
    def test_bare_ratios_pass_through_with_low_tier(self, bare_ratio):
        """Bare ratio inputs ride through as-is with tier="low". The
        pre-#149 Flux/Gemini default fallback for bare ratios was
        "square_hd"/"0.5K" — neither of which is in the canonical
        vocabulary. The translation now happens at the adapter, so
        bare-ratio callers see provider-specific defaults via the
        size-table .get(...) fallback."""
        from autonomous.ai._image_utils import resolve_image_config
        assert resolve_image_config(bare_ratio) == (bare_ratio, "low")

    @pytest.mark.parametrize(
        "unknown",
        ["", "Banana", "1080p", "2x2", "Portrait ", "portrait"],
    )
    def test_unknown_input_falls_back_to_3by4_low(self, unknown):
        """Default fallback per the module docstring is `("3:4", "low")`
        — matches the pre-#149 inline Flux and Gemini defaults. Pins
        case-sensitivity (`"portrait"` lowercase is NOT a hit) and
        whitespace-sensitivity (`"Portrait "` with a trailing space
        is NOT a hit) so a refactor that adds `.strip().title()` has
        to confront the existing contract."""
        from autonomous.ai._image_utils import resolve_image_config
        assert resolve_image_config(unknown) == ("3:4", "low")

    def test_returns_a_2_tuple_not_a_list_or_dict(self):
        """Adapter dispatch unpacks the result as `ratio, tier = ...`.
        A regression that returned a 3-tuple or a dict would crash on
        unpack — but a list would silently pass. Pin tuple identity
        so callers can rely on hashability + immutability."""
        from autonomous.ai._image_utils import resolve_image_config
        result = resolve_image_config("Portrait")
        assert isinstance(result, tuple) and len(result) == 2

    def test_each_table_value_uses_one_of_the_three_tiers(self):
        """Tier vocabulary closure: every value in the table maps to
        one of "low" / "2K" / "4K". A new entry that introduces a
        fourth tier (e.g. "8K") would silently fall through both
        adapters' `.get(...)` calls to the default size. Pin the
        closure so the introduction of a new tier forces an update
        to both `_FLUX_SIZE_BY_RATIO_TIER` and `_GEMINI_SIZE_BY_TIER`."""
        from autonomous.ai import _image_utils
        valid_tiers = {"low", "2K", "4K"}
        for key, (_ratio, tier) in _image_utils._TABLE.items():
            assert tier in valid_tiers, (
                f"key {key!r} maps to unknown tier {tier!r}; "
                "Flux and Gemini size tables would silently fall back"
            )


# ---------------------------------------------------------------------------
# B) Gemini wire-shape + 4K-clamp breadcrumb (#29, #30)
# ---------------------------------------------------------------------------


def _gemini_bare():
    """Plain-class stub with class-level attrs shadowing GeminiAIModel's
    StringAttr fields, then `_get_image_config` bound as a class
    attribute. Mirrors the pattern at
    test_unit_gemini_translation_iter_2026_06_14.py:62 — avoids the
    descriptor protocol that needs `_initialised` set in __init__."""
    from autonomous.ai.models.gemini import GeminiAIModel

    class _Stub:
        _image_model = "gemini-test-image-model"
        _get_image_config = GeminiAIModel._get_image_config
        _GEMINI_SIZE_BY_TIER = GeminiAIModel._GEMINI_SIZE_BY_TIER

    return _Stub()


class TestGeminiGetImageConfig:
    """Pin gemini's _get_image_config end-to-end (no existing test
    covers this method). Critical: the "low" tier maps to "1K" — the
    pre-#149 inline code mapped to "0.5K" which Gemini's API
    rejects (issue #29). Bare-ratio inputs MUST inherit "1K", not the
    invalid old default."""

    @pytest.mark.parametrize(
        "input_key,expected",
        [
            ("Portrait",   ("3:4",  "1K")),
            ("Landscape",  ("16:9", "1K")),
            ("2K",         ("16:9", "2K")),
            ("2KPortrait", ("3:4",  "2K")),
            ("4K",         ("16:9", "2K")),   # clamp per #30
            ("Map",        ("16:9", "2K")),   # clamp per #30
            ("4KPortrait", ("3:4",  "2K")),   # clamp per #30
            ("1:1",        ("1:1",  "1K")),   # bare ratio → "1K" not "0.5K" (#29)
            ("3:4",        ("3:4",  "1K")),
            ("4:3",        ("4:3",  "1K")),
            ("9:16",       ("9:16", "1K")),
            ("16:9",       ("16:9", "1K")),
            ("Unknown",    ("3:4",  "1K")),   # default fallback
        ],
    )
    def test_input_resolves_to_documented_wire_shape(self, input_key, expected):
        gem = _gemini_bare()
        assert gem._get_image_config(input_key) == expected

    def test_low_tier_never_emits_the_invalid_half_K(self):
        """Issue #29 regression guard. The pre-#149 inline code had
        ``size = "0.5K"`` as the default and for bare-ratio inputs,
        which Gemini's API rejects with 400 INVALID_ARGUMENT. Pin
        that no path through the new dispatch can emit "0.5K"."""
        gem = _gemini_bare()
        for key in ["Portrait", "Landscape", "1:1", "3:4", "16:9",
                    "Unknown", "", "garbage"]:
            _ratio, size = gem._get_image_config(key)
            assert size != "0.5K", (
                f"input {key!r} produced invalid Gemini size 0.5K"
            )


class TestGeminiClampBreadcrumb:
    """Pin the 4K-clamp log breadcrumb (#30). The clamp itself is
    correct (returning *something* rather than 400-failing), but the
    silence was the bug — storyteller workers stored the WebP and had
    no way to know the resolution contract was downgraded. Mirrors
    imageagent's hybrid_upscale / provider_fallback_used breadcrumb
    pattern."""

    def _capture_log_calls(self, monkeypatch):
        """Replace autonomous.log with a recorder. log() in gemini.py
        is `from autonomous import log`, then called as `log(...)` —
        intercept at the gemini module's binding."""
        from autonomous.ai.models import gemini as gemini_mod
        calls = []
        monkeypatch.setattr(
            gemini_mod, "log", lambda *a, **kw: calls.append((a, kw))
        )
        return calls

    @pytest.mark.parametrize("input_key", ["4K", "Map", "4KPortrait"])
    def test_clamp_fires_log_for_each_4K_input(self, input_key, monkeypatch):
        calls = self._capture_log_calls(monkeypatch)
        gem = _gemini_bare()
        gem._get_image_config(input_key)

        # Exactly one log call from the clamp; pin the breadcrumb token.
        clamp_calls = [c for c in calls if "GEMINI-IMAGE-CLAMP" in str(c[0])]
        assert len(clamp_calls) == 1, (
            f"expected 1 clamp log for {input_key!r}, got {len(clamp_calls)}"
        )

    @pytest.mark.parametrize(
        "non_clamp_key",
        ["Portrait", "Landscape", "2K", "2KPortrait", "1:1", "3:4", "Unknown"],
    )
    def test_clamp_does_not_fire_for_non_4K_inputs(
        self, non_clamp_key, monkeypatch
    ):
        """Negative-space pin: a regression that widened the clamp
        branch to fire for 2K or low-tier inputs would be silent in
        production (log goes to file, no exception). Pin that ONLY
        4K-tier inputs trigger the breadcrumb."""
        calls = self._capture_log_calls(monkeypatch)
        gem = _gemini_bare()
        gem._get_image_config(non_clamp_key)

        clamp_calls = [c for c in calls if "GEMINI-IMAGE-CLAMP" in str(c[0])]
        assert clamp_calls == [], (
            f"input {non_clamp_key!r} unexpectedly fired clamp log"
        )

    def test_clamp_log_includes_input_key_and_model(self, monkeypatch):
        """Pin the breadcrumb payload so a refactor that drops the
        input key or model name (making the log line less actionable)
        has to update the test. The log line is the operator's only
        signal that a resolution contract was silently downgraded."""
        calls = self._capture_log_calls(monkeypatch)
        gem = _gemini_bare()
        gem._image_model = "gemini-3.1-flash-image-preview"
        gem._get_image_config("4KPortrait")

        clamp_text = str(calls[0][0])
        assert "4KPortrait" in clamp_text
        assert "gemini-3.1-flash-image-preview" in clamp_text
        assert "2K" in clamp_text   # the target the clamp landed on


# ---------------------------------------------------------------------------
# C) `TextAgent.generate` forwards `system_prompt=` to adapter (#140)
# ---------------------------------------------------------------------------


class _FakeAdapter:
    """Records every call to generate_text. Returns a sentinel string."""

    def __init__(self):
        self.calls = []

    def generate_text(self, message, additional_instructions="", **kwargs):
        self.calls.append({
            "message": message,
            "additional_instructions": additional_instructions,
            **kwargs,
        })
        return "FAKE_RESULT"


def _textagent_bare(adapter):
    """Bind the REAL `TextAgent.generate` function to a plain-class
    stub. Sidesteps the StringAttr descriptor protocol — calling
    `TextAgent.__new__(TextAgent)` produces an instance without
    `_initialised`, which the descriptor's __set__ trips over on the
    first field assignment. By binding `TextAgent.generate` to a
    POJO that exposes `provider`/`get_client`/`add_to_job_meta` as
    plain class attributes, we exercise the genuine dispatch body
    (not a copy) without touching the Document machinery."""
    from autonomous.ai.textagent import TextAgent

    class _Stub:
        provider = "fake-provider"

        def get_client(self, _name):
            return adapter

        def add_to_job_meta(self, *a, **kw):
            pass

    stub = _Stub()
    # Bind `TextAgent.generate` (the unbound function) to the stub.
    stub.generate = TextAgent.generate.__get__(stub, _Stub)
    return stub


class TestTextAgentGenerateForwarding:
    """Pin TextAgent.generate's wire shape — every kwarg the user
    passes lands on the adapter unchanged. Bug shape: the dispatcher
    silently dropping a kwarg looks fine in unit tests but breaks
    consumers whose per-call persona override doesn't take effect."""

    def test_explicit_system_prompt_forwards_unchanged(self, monkeypatch):
        monkeypatch.delenv("TEXT_AI_AGENT", raising=False)
        adapter = _FakeAdapter()
        agent = _textagent_bare(adapter)

        agent.generate("hello", system_prompt="be terse")

        assert len(adapter.calls) == 1
        assert adapter.calls[0]["system_prompt"] == "be terse"

    def test_default_system_prompt_is_none(self, monkeypatch):
        """Pre-#140 wire-shape preservation: when the caller omits
        system_prompt, the adapter sees system_prompt=None.
        Adapter-side `system_prompt or self.instructions` then falls
        through to the persisted persona — i.e. the pre-#140 default
        is preserved."""
        monkeypatch.delenv("TEXT_AI_AGENT", raising=False)
        adapter = _FakeAdapter()
        agent = _textagent_bare(adapter)

        agent.generate("hello")

        assert adapter.calls[0]["system_prompt"] is None

    def test_temperature_remains_conditional_not_forwarded_as_none(
        self, monkeypatch
    ):
        """Pin the documented heterogeneous-default asymmetry in
        textagent.py: temperature is conditionally added because
        local/openai_compat default to 0.7 but gemini/mock default to
        None — forwarding an explicit None would override the
        adapter's own default. This is a deliberate departure from
        system_prompt's uniform forwarding."""
        monkeypatch.delenv("TEXT_AI_AGENT", raising=False)
        adapter = _FakeAdapter()
        agent = _textagent_bare(adapter)

        agent.generate("hello")  # no temperature

        assert "temperature" not in adapter.calls[0], (
            "temperature default-None must NOT be forwarded; adapters "
            "have heterogeneous defaults (textagent.py comment)"
        )

    def test_explicit_temperature_forwards(self, monkeypatch):
        monkeypatch.delenv("TEXT_AI_AGENT", raising=False)
        adapter = _FakeAdapter()
        agent = _textagent_bare(adapter)

        agent.generate("hello", temperature=0.2)

        assert adapter.calls[0]["temperature"] == 0.2

    def test_generate_signature_accepts_system_prompt(self):
        """If a refactor removes the kwarg from TextAgent.generate but
        leaves the forwarding in the body, the call-site signature
        check breaks lint-mode tools and SDK consumers. Pin via
        inspect.signature so the contract is enforced at the
        signature surface, not just the body."""
        from autonomous.ai.textagent import TextAgent
        sig = inspect.signature(TextAgent.generate)
        assert "system_prompt" in sig.parameters
        assert sig.parameters["system_prompt"].default is None


# ---------------------------------------------------------------------------
# D) `openai_compat.generate_text` — system_prompt REPLACES persona (#140)
# ---------------------------------------------------------------------------


def _openai_compat_bare(instructions="default persona"):
    """Plain-class stub binding OpenAIClient.generate_text. See the
    _gemini_bare() note on why we sidestep the descriptor protocol."""
    from autonomous.ai.models.openai_compat import OpenAIClient

    class _Stub:
        pass

    stub = _Stub()
    stub.instructions = instructions
    stub._text_model = "test-model"
    # Bind the unbound function as an attribute so the test can call
    # adapter.generate_text(...) directly. _chat will be monkeypatched
    # per test.
    stub.generate_text = OpenAIClient.generate_text.__get__(stub, _Stub)
    return stub


class _ChatCapture:
    """Records the (model, system, user, temperature) the adapter
    constructs before forwarding to HTTP."""

    def __init__(self):
        self.calls = []

    def __call__(self, model, system, user, temperature=0.7):
        self.calls.append({
            "model": model, "system": system, "user": user,
            "temperature": temperature,
        })
        return "RESPONSE_TEXT"


class TestOpenAICompatGenerateTextSystemPromptReplace:
    """openai_compat is the reference REPLACE-semantic adapter for
    generate_text. The docstring at openai_compat.py:413 says
    `system = system_prompt or self.instructions`. Pin all four corner
    cases (no overrides, system_prompt only, additional only, both)
    so a refactor preserving any one accidentally can't drop another."""

    def _stub_chat(self, monkeypatch, adapter):
        capture = _ChatCapture()
        # raising=False because the plain-class stub has no `_chat`
        # attribute until we install one here.
        monkeypatch.setattr(adapter, "_chat", capture, raising=False)
        return capture

    def test_bare_call_uses_persisted_instructions(self, monkeypatch):
        adapter = _openai_compat_bare(instructions="PERSONA")
        chat = self._stub_chat(monkeypatch, adapter)

        adapter.generate_text("hello")

        assert chat.calls[0]["system"] == "PERSONA"

    def test_system_prompt_replaces_persisted_instructions(self, monkeypatch):
        adapter = _openai_compat_bare(instructions="PERSONA")
        chat = self._stub_chat(monkeypatch, adapter)

        adapter.generate_text("hello", system_prompt="OVERRIDE")

        # Critical: the persona is REPLACED, not appended.
        assert chat.calls[0]["system"] == "OVERRIDE"
        assert "PERSONA" not in chat.calls[0]["system"], (
            "system_prompt must REPLACE persona for #140 parity with "
            "JSONAgent.generate(system_prompt=)"
        )

    def test_additional_instructions_appends_to_persona(self, monkeypatch):
        adapter = _openai_compat_bare(instructions="PERSONA")
        chat = self._stub_chat(monkeypatch, adapter)

        adapter.generate_text("hello", additional_instructions="EXTRA")

        assert chat.calls[0]["system"] == "PERSONA\nEXTRA"

    def test_system_prompt_AND_additional_compose_in_documented_order(
        self, monkeypatch
    ):
        adapter = _openai_compat_bare(instructions="PERSONA")
        chat = self._stub_chat(monkeypatch, adapter)

        adapter.generate_text(
            "hello",
            system_prompt="OVERRIDE",
            additional_instructions="EXTRA",
        )

        # system_prompt replaces PERSONA; additional_instructions
        # appends as a task-level suffix below the override.
        assert chat.calls[0]["system"] == "OVERRIDE\nEXTRA"


# ---------------------------------------------------------------------------
# E) `gemini.generate_text` — system_prompt REPLACES persona (#140)
# ---------------------------------------------------------------------------


def _gemini_with_client(instructions="default persona"):
    """Plain-class stub binding GeminiAIModel.generate_text — same
    pattern as _openai_compat_bare. The client is a MagicMock whose
    `models.generate_content` returns a sentinel-text response so
    the method body completes."""
    from autonomous.ai.models.gemini import GeminiAIModel

    class _Stub:
        pass

    stub = _Stub()
    stub.instructions = instructions
    stub._text_model = "gemini-test-text-model"
    stub._image_model = "gemini-test-image-model"
    stub.client = MagicMock()
    response = MagicMock()
    response.text = "RESPONSE_TEXT"
    stub.client.models.generate_content.return_value = response
    stub.generate_text = GeminiAIModel.generate_text.__get__(stub, _Stub)
    return stub


class TestGeminiGenerateTextSystemPromptReplace:
    """Gemini's generate_text shape (per gemini.py:471):
    `base_system = system_prompt or self.instructions`, then
    `system_instruction = f"{base_system}.{additional_instructions}"`.
    The dot-join is documented behavior — pin it so a refactor that
    swaps to a newline (matching openai_compat) has to confront the
    different join character."""

    def _captured_system_instruction(self, gem):
        """Pull system_instruction out of the captured config kwarg."""
        call = gem.client.models.generate_content.call_args
        config = call.kwargs.get("config")
        # config is a `types.GenerateContentConfig` constructed from
        # `config_kwargs`. We can read its attributes directly.
        return config.system_instruction

    def test_bare_call_uses_persona_plus_empty_additional(self):
        gem = _gemini_with_client(instructions="PERSONA")
        gem.generate_text("hello")
        # additional_instructions="" by default → "PERSONA."
        assert self._captured_system_instruction(gem) == "PERSONA."

    def test_system_prompt_replaces_persona(self):
        gem = _gemini_with_client(instructions="PERSONA")
        gem.generate_text("hello", system_prompt="OVERRIDE")
        assert self._captured_system_instruction(gem) == "OVERRIDE."

    def test_additional_instructions_dot_appends(self):
        """Pin the dot-separator. openai_compat uses "\\n"; gemini
        uses ".". A future "harmonize separators" PR would silently
        change the prompt shape if this isn't pinned."""
        gem = _gemini_with_client(instructions="PERSONA")
        gem.generate_text("hello", additional_instructions="EXTRA")
        assert self._captured_system_instruction(gem) == "PERSONA.EXTRA"

    def test_system_prompt_AND_additional_compose(self):
        gem = _gemini_with_client(instructions="PERSONA")
        gem.generate_text(
            "hello",
            system_prompt="OVERRIDE",
            additional_instructions="EXTRA",
        )
        assert self._captured_system_instruction(gem) == "OVERRIDE.EXTRA"


# ---------------------------------------------------------------------------
# F) `local_model.generate_text` — system_prompt PREPENDS (#140) — DOCUMENTED
#    ASYMMETRY with openai_compat/gemini. self.instructions is NEVER used.
# ---------------------------------------------------------------------------


def _local_model_bare(instructions="persona-that-should-be-ignored"):
    """Plain-class stub binding LocalAIModel.generate_text. Note:
    self.instructions is intentionally set to a sentinel so the
    persona-non-leakage test can verify local_model never reads it
    (the documented asymmetry vs openai_compat/gemini per #140)."""
    from autonomous.ai.models.local_model import LocalAIModel

    class _Stub:
        pass

    stub = _Stub()
    stub.instructions = instructions
    stub._text_model = "test-local-model"
    # Fields generate_text reads to build the Ollama payload + HTTP call.
    stub._context_limit = 4096
    stub._ollama_url = "http://test-ollama.invalid:11434"
    stub._text_timeout = 30
    stub.generate_text = LocalAIModel.generate_text.__get__(stub, _Stub)
    return stub


def _stub_local_http_post(monkeypatch):
    """Replace LocalAIModel's HTTP path so we can capture the payload."""
    from autonomous.ai.models import local_model as local_mod
    calls = []

    def _fake_post(self_or_url, *args, **kwargs):
        # HttpClient.post signature variants — accept everything,
        # record kwargs["json"] which is what local_model passes.
        if "json" in kwargs:
            calls.append(kwargs["json"])
        elif len(args) >= 1 and isinstance(args[0], dict):
            calls.append(args[0])
        # Minimal Ollama response shape for the happy path.
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "message": {"content": "RESPONSE_TEXT"},
            "done": True,
        }
        return resp

    monkeypatch.setattr(local_mod._HTTP, "post", _fake_post)
    return calls


class TestLocalModelGenerateTextSystemPromptPrepend:
    """local_model.generate_text is the documented OUTLIER (#140).
    Its system slot is `system_content = "\\n".join(filter(None,
    [system_prompt, additional_instructions]))`. self.instructions
    is NOT included. Pin all four corners + the persona-non-leakage
    pin so the asymmetry is explicit."""

    def test_bare_call_emits_empty_system_content(self, monkeypatch):
        calls = _stub_local_http_post(monkeypatch)
        adapter = _local_model_bare()
        adapter.generate_text("hello")

        system = calls[0]["messages"][0]["content"]
        assert system == "", (
            "local_model bare-call system slot must be empty string — "
            "self.instructions is intentionally NOT used here (#140)"
        )

    def test_self_instructions_does_not_leak_into_system_slot(
        self, monkeypatch
    ):
        """The critical pin documenting the asymmetry with
        openai_compat/gemini. Set self.instructions to a sentinel and
        verify NONE of it appears in the Ollama payload."""
        calls = _stub_local_http_post(monkeypatch)
        adapter = _local_model_bare(
            instructions="PERSONA_SENTINEL_DO_NOT_LEAK"
        )
        adapter.generate_text("hello", system_prompt="OVERRIDE")

        system = calls[0]["messages"][0]["content"]
        assert "PERSONA_SENTINEL_DO_NOT_LEAK" not in system, (
            "local_model must NOT read self.instructions — that is "
            "the documented asymmetry vs openai_compat/gemini (#140)"
        )

    def test_system_prompt_only(self, monkeypatch):
        calls = _stub_local_http_post(monkeypatch)
        adapter = _local_model_bare()
        adapter.generate_text("hello", system_prompt="OVERRIDE")

        assert calls[0]["messages"][0]["content"] == "OVERRIDE"

    def test_additional_instructions_only(self, monkeypatch):
        calls = _stub_local_http_post(monkeypatch)
        adapter = _local_model_bare()
        adapter.generate_text("hello", additional_instructions="EXTRA")

        assert calls[0]["messages"][0]["content"] == "EXTRA"

    def test_both_compose_with_newline_prepend(self, monkeypatch):
        """system_prompt PREPENDS to additional_instructions —
        opposite order from openai_compat (where system_prompt is
        BASE and additional is the suffix)."""
        calls = _stub_local_http_post(monkeypatch)
        adapter = _local_model_bare()
        adapter.generate_text(
            "hello",
            system_prompt="OVERRIDE",
            additional_instructions="EXTRA",
        )

        assert calls[0]["messages"][0]["content"] == "OVERRIDE\nEXTRA"


# ---------------------------------------------------------------------------
# G) `mock_model.generate_text` — accepts kwarg, ignores (#140)
# ---------------------------------------------------------------------------


class TestMockModelGenerateTextAcceptsSystemPrompt:
    """Mock adapter exists only for dispatch parity in tests. Pin
    that it accepts system_prompt= without TypeError — a regression
    that dropped the kwarg would break every test that uses
    ai_provider="mock" and passes system_prompt."""

    def test_accepts_kwarg_without_typeerror(self):
        from autonomous.ai.models.mock_model import MockAIModel

        class _Stub:
            pass

        stub = _Stub()
        # MockAIModel.generate_text doesn't touch self at all; binding
        # the unbound function to any object works.
        gen = MockAIModel.generate_text.__get__(stub, _Stub)
        # Must not raise.
        result = gen("hello", system_prompt="anything")
        assert isinstance(result, str)
        assert len(result) > 0   # mock returns Lorem ipsum-shaped text

    def test_signature_includes_system_prompt(self):
        from autonomous.ai.models.mock_model import MockAIModel
        sig = inspect.signature(MockAIModel.generate_text)
        assert "system_prompt" in sig.parameters


# ---------------------------------------------------------------------------
# H) `QuerySet.snapshot()` removed (#154)
# ---------------------------------------------------------------------------


class TestQuerySetSnapshotRemoval:
    """Pin the four removals: the method itself, the _snapshot init
    flag, the _clone_into copy_props entry, and the _cursor_args
    warning re-fire. Pre-#154 every queryset construction allocated
    self._snapshot=False even though it was unused under PyMongo 3+;
    every clone() copied the dead field; every _cursor_args access
    checked it; every .snapshot() call emitted a no-op
    DeprecationWarning."""

    def test_queryset_class_has_no_snapshot_attribute(self):
        from autonomous.db.queryset.base import BaseQuerySet
        assert not hasattr(BaseQuerySet, "snapshot"), (
            "QuerySet.snapshot() removed in #154; consumers should "
            "delete the call (no replacement; PyMongo 3+ ignored it)"
        )

    def test_baseQuerySet_init_does_not_allocate_snapshot_flag(self):
        """Pin via source inspection so we don't need a real DB.
        The previous __init__ had `self._snapshot = False`; #154
        drops it. Use `inspect.getsource` so the test is robust to
        whitespace changes."""
        from autonomous.db.queryset.base import BaseQuerySet
        source = inspect.getsource(BaseQuerySet.__init__)
        assert "_snapshot" not in source, (
            "_snapshot init flag must be removed (#154)"
        )

    def test_clone_into_copy_props_does_not_include_snapshot(self):
        """The copy_props tuple in _clone_into is the canonical list
        of fields that .clone() carries forward. _snapshot must NOT
        be in it; if it stayed there, every clone() would try to
        copy an attribute that no longer exists and raise
        AttributeError on real workloads."""
        from autonomous.db.queryset.base import BaseQuerySet
        source = inspect.getsource(BaseQuerySet._clone_into)
        # Specifically check the literal token doesn't appear in the
        # copy_props list. (It also must not appear in the source at
        # all, but if a comment ever mentions it, the broader
        # _snapshot assertion above suffices.)
        assert '"_snapshot"' not in source, (
            "_snapshot must not be in _clone_into copy_props (#154)"
        )

    def test_cursor_args_does_not_re_fire_snapshot_warning(self):
        """Pre-#154 _cursor_args contained a
        `warnings.warn("snapshot is not anymore available with
        PyMongo 3+", DeprecationWarning)` block guarded by
        self._snapshot. With _snapshot removed, that block is dead
        code; pin it's gone."""
        from autonomous.db.queryset.base import BaseQuerySet
        source = inspect.getsource(BaseQuerySet)
        # The block was the only mention of "snapshot" in the cursor
        # args path; the whole file should be snapshot-free after
        # #154 (verified by `grep -n snapshot` finding nothing).
        assert "snapshot" not in source.lower(), (
            "BaseQuerySet source still references snapshot; #154 "
            "intended a clean removal"
        )


# ---------------------------------------------------------------------------
# I) Version bump pin
# ---------------------------------------------------------------------------


class TestVersionBump:
    """PR #163 bumps __init__.py to 0.3.162 — matching the
    release.sh push that prod already shipped at the end of the
    prior cycle. The bump existing in dev means dev/test/main agree
    on the latest published version; a drift here would mean the
    next prod release.sh patch-bump would land on the wrong base."""

    def test_version_string_is_0_3_162(self):
        import autonomous
        assert autonomous.__version__ == "0.3.162"
