"""Independent coverage for the FLUX-routing bundle (PR #8).

Written without consulting dev's ``tests/_dev_local/`` (gitignored
anyway) or dev's committed ``test_unit_flux.py`` /
``test_unit_imageagent_routing.py``. These tests target the behavior
surface from the source diff alone — the second perspective in the
two-perspective testing design described in CLAUDE.md.

Five concerns are covered:

1. ``FluxAIModel`` — adapter contract: aspect-ratio mapping table,
   FAL_KEY env contract, ``files=`` rejection, upscale no-op,
   clean import without FAL_KEY.
2. ``ImageAgent._routing_enabled`` — truth-table on
   ``IMAGE_PROVIDER_ROUTING`` env values.
3. ``ImageAgent._aspect_to_size_token`` — size-class derivation that
   feeds the cost table.
4. ``ImageAgent._route_provider`` — routing-off passthrough vs
   routing-on aspect-ratio dispatch.
5. ``ImageAgent._estimate_cost_usd`` — exact lookup, wildcard
   fallback, and unknown-tuple-returns-zero (telemetry must not
   raise on the image-gen hot path).
6. ``ImageAgent._resolve_fallback`` — ``_UNSET`` sentinel resolution
   distinguishes "caller did not pass" from "caller passed None".
7. ``BaseAgent.MODEL_REGISTRY`` / ``BaseAgent.client`` choices —
   ``"flux"`` is registered and FluxAIModel is an accepted
   ReferenceAttr choice.
8. ``MockAIModel.generate_image`` / ``upscale_image`` — absorb the
   new ``fallback_provider`` / ``route`` kwargs without TypeError,
   so the mock provider stays valid under the post-PR ImageAgent
   call signatures.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from autonomous.ai.imageagent import (
    ImageAgent,
    _COST_USD,
    _aspect_to_size_token,
    _routing_enabled,
)


# ---------------------------------------------------------------------------
# _FakeImageAgent — borrows ImageAgent methods without MongoEngine machinery
# ---------------------------------------------------------------------------


class _FakeImageAgent:
    """See test_unit_image_perf_iter_2026_05_23.py for the rationale.

    The vendored mongoengine fork's ``StringAttr`` descriptor protocol
    requires a long tail of state on instances; bypassing
    ``AutoModel.__init__`` via ``__new__`` doesn't work. Borrow the
    bound methods onto a plain class instead so the production code
    runs unchanged.
    """

    MODEL_REGISTRY: dict = {}

    _resolve_aspect_ratio = ImageAgent._resolve_aspect_ratio
    _route_provider = ImageAgent._route_provider
    _estimate_cost_usd = ImageAgent._estimate_cost_usd
    _resolve_fallback = ImageAgent._resolve_fallback

    def __init__(self, provider: str = "local", fallback_provider=None):
        self.provider = provider
        self.fallback_provider = fallback_provider
        self.name = "test-agent"
        self.instructions = "test"
        self.description = "test"


# ---------------------------------------------------------------------------
# FluxAIModel — aspect-ratio config + FAL_KEY contract + files= rejection
# ---------------------------------------------------------------------------


class TestFluxModuleImport:
    def test_module_imports_without_fal_key(self):
        """Importing the module must NOT touch FAL_KEY — otherwise
        ``BaseAgent`` (which always imports FluxAIModel at module
        load) would break every deployment that doesn't use FLUX.

        Subprocess isolation: a within-process ``importlib.reload``
        would mutate ``sys.modules`` for everyone, breaking the
        ``BaseAgent.MODEL_REGISTRY['flux'] is FluxAIModel`` identity
        contract that other tests in this file pin. The subprocess
        gets a fresh interpreter, FAL_KEY scrubbed from env, and is
        the only safe way to validate the import-time contract.
        """
        import os
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[2]
        # Mirror tests/conftest.py's sys.path injection inside the
        # subprocess. PYTHONPATH is the env-var equivalent of the
        # sys.path.insert in conftest.py.
        env = {
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(repo_root / "src"),
            "HOME": os.environ.get("HOME", "/tmp"),
        }
        result = subprocess.run(
            [sys.executable, "-c", "import autonomous.ai.models.flux as m; "
             "assert hasattr(m, 'FluxAIModel'); print('ok')"],
            env=env,  # FAL_KEY scrubbed by omission.
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Importing autonomous.ai.models.flux without FAL_KEY failed: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "ok" in result.stdout


class TestFluxAspectRatioConfig:
    """The ``_get_image_config`` mapping must mirror Gemini's external
    vocabulary (Portrait/Landscape/2K/2KPortrait/4K/Map/4KPortrait)
    plus the raw aspect-ratio passthrough set ({1:1, 3:4, 4:3, 9:16,
    16:9}). Pinning the exact output pairs prevents silent drift in
    a deployment that overrides FLUX_IMAGE_MODEL but not the
    aspect-ratio contract."""

    @pytest.fixture
    def flux(self):
        from autonomous.ai.models.flux import FluxAIModel
        # Bypass AutoModel init for a pure-function table-test.
        inst = FluxAIModel.__new__(FluxAIModel)
        return inst

    @pytest.mark.parametrize(
        "input_ratio,expected_ratio,expected_size",
        [
            ("Portrait", "3:4", "square_hd"),
            ("Landscape", "16:9", "square_hd"),
            ("2K", "16:9", "landscape_4_3"),
            ("2KPortrait", "3:4", "portrait_4_3"),
            ("4K", "16:9", "landscape_16_9"),
            ("Map", "16:9", "landscape_16_9"),  # Map collapses to 4K size
            ("4KPortrait", "3:4", "portrait_16_9"),
        ],
    )
    def test_named_tiers_map_to_expected_pairs(
        self, flux, input_ratio, expected_ratio, expected_size
    ):
        ratio, size = flux._get_image_config(input_ratio)
        assert (ratio, size) == (expected_ratio, expected_size)

    @pytest.mark.parametrize("raw", ["1:1", "3:4", "4:3", "9:16", "16:9"])
    def test_raw_aspect_ratios_pass_through_with_default_size(self, flux, raw):
        ratio, size = flux._get_image_config(raw)
        assert ratio == raw
        # The default size_hd fallback applies when only ratio is given.
        assert size == "square_hd"

    def test_unknown_input_falls_back_to_default_pair(self, flux):
        """Unknown aspect_ratio must fall through to the safe default
        (3:4, square_hd) rather than raising — image-gen calls must
        never break on a stray new aspect token from a consumer."""
        ratio, size = flux._get_image_config("WhateverFutureToken")
        assert (ratio, size) == ("3:4", "square_hd")


class TestFluxApiKeyContract:
    @pytest.fixture
    def flux(self):
        from autonomous.ai.models.flux import FluxAIModel
        return FluxAIModel.__new__(FluxAIModel)

    def test_missing_fal_key_raises_runtime_error_with_pointer(
        self, flux, monkeypatch
    ):
        monkeypatch.delenv("FAL_KEY", raising=False)
        with pytest.raises(RuntimeError, match="FAL_KEY"):
            flux._require_api_key()

    def test_whitespace_only_fal_key_treated_as_missing(self, flux, monkeypatch):
        """A FAL_KEY="" or "   " is functionally equivalent to unset —
        the adapter should reject early rather than send a 401-bound
        request to fal.ai."""
        monkeypatch.setenv("FAL_KEY", "   ")
        with pytest.raises(RuntimeError, match="FAL_KEY"):
            flux._require_api_key()

    def test_valid_fal_key_returns_stripped_value(self, flux, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "fal-xyz-123")
        assert flux._require_api_key() == "fal-xyz-123"


class TestFluxFilesRejection:
    """v1 FLUX scope is text-to-image only. ``files=`` must raise
    NotImplementedError with a pointer to the spec doc so consumers
    aren't left guessing the migration path."""

    @pytest.fixture
    def flux(self):
        from autonomous.ai.models.flux import FluxAIModel
        return FluxAIModel.__new__(FluxAIModel)

    def test_files_non_empty_list_raises_not_implemented(self, flux):
        with pytest.raises(NotImplementedError, match="img2img"):
            flux.generate_image(prompt="x", files=[b"some-bytes"])

    def test_files_bytes_raises_not_implemented(self, flux):
        """Non-list truthy ``files`` value (single bytes) must also reject."""
        with pytest.raises(NotImplementedError):
            flux.generate_image(prompt="x", files=b"raw-bytes")

    def test_files_none_does_not_short_circuit(self, flux, monkeypatch):
        """With files=None the NotImplementedError must NOT fire —
        the call should proceed to the API-key check and fail there."""
        monkeypatch.delenv("FAL_KEY", raising=False)
        with pytest.raises(RuntimeError, match="FAL_KEY"):
            flux.generate_image(prompt="x", files=None)

    def test_files_empty_list_does_not_short_circuit(self, flux, monkeypatch):
        """An empty list is falsy — must reach the API-key check, not
        the NotImplementedError branch."""
        monkeypatch.delenv("FAL_KEY", raising=False)
        with pytest.raises(RuntimeError, match="FAL_KEY"):
            flux.generate_image(prompt="x", files=[])


class TestFluxUpscaleNoOp:
    def test_upscale_image_returns_input_reference_unchanged(self):
        from autonomous.ai.models.flux import FluxAIModel
        flux = FluxAIModel.__new__(FluxAIModel)
        sentinel = b"original-image-bytes-do-not-modify"
        result = flux.upscale_image(
            prompt="x", image_content=sentinel, aspect_ratio="2KPortrait"
        )
        # ``is`` identity — ImageAgent.upscale relies on this for its
        # ``upscale_supported=False`` detection. A copy would break it.
        assert result is sentinel

    def test_upscale_image_none_content_returns_none(self):
        from autonomous.ai.models.flux import FluxAIModel
        flux = FluxAIModel.__new__(FluxAIModel)
        assert flux.upscale_image(prompt="x", image_content=None) is None


# ---------------------------------------------------------------------------
# ImageAgent._routing_enabled — IMAGE_PROVIDER_ROUTING env truth table
# ---------------------------------------------------------------------------


class TestRoutingEnabled:
    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "True", "yes", "YES"])
    def test_truthy_values_enable_routing(self, val, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", val)
        assert _routing_enabled() is True

    @pytest.mark.parametrize(
        "val", ["", "0", "no", "false", "off", "False", "anything-else"]
    )
    def test_falsy_values_disable_routing(self, val, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", val)
        assert _routing_enabled() is False

    def test_unset_disables_routing(self, monkeypatch):
        monkeypatch.delenv("IMAGE_PROVIDER_ROUTING", raising=False)
        assert _routing_enabled() is False


# ---------------------------------------------------------------------------
# ImageAgent._aspect_to_size_token — size-class derivation for cost lookup
# ---------------------------------------------------------------------------


class TestAspectToSizeToken:
    @pytest.mark.parametrize(
        "ratio,expected",
        [
            ("2K", "2K"),
            ("2KPortrait", "2K"),
            ("4K", "4K"),
            ("4KPortrait", "4K"),
            ("Map", "4K"),  # Map bills at the 4K tier
            ("Landscape", "1K"),
        ],
    )
    def test_named_tiers_map_to_expected_size(self, ratio, expected):
        assert _aspect_to_size_token(ratio) == expected

    @pytest.mark.parametrize("ratio", ["Portrait", "1:1", "16:9", "3:4", "4:3"])
    def test_portrait_and_raw_aspect_default_to_cheapest(self, ratio):
        """Per docstring, Portrait and raw aspect ratios bill at the
        provider's cheapest tier (0.5K). The cost-table indirection
        is what makes this load-bearing."""
        assert _aspect_to_size_token(ratio) == "0.5K"

    def test_unknown_aspect_defaults_to_cheapest(self):
        """Forward-looking — a new aspect token added by some consumer
        must not crash the cost lookup."""
        assert _aspect_to_size_token("UnknownFutureRatio") == "0.5K"


# ---------------------------------------------------------------------------
# ImageAgent._route_provider — routing on/off + tier dispatch
# ---------------------------------------------------------------------------


class TestRouteProvider:
    def test_routing_off_returns_self_provider_for_every_ratio(self, monkeypatch):
        """Default behavior — IMAGE_PROVIDER_ROUTING unset means every
        call goes to ``self.provider``, regardless of aspect_ratio.
        This is the no-op-by-default guarantee."""
        monkeypatch.delenv("IMAGE_PROVIDER_ROUTING", raising=False)
        agent = _FakeImageAgent(provider="local")
        for r in [
            "Portrait", "Landscape", "2K", "2KPortrait", "4K",
            "4KPortrait", "Map", "1:1", "16:9",
        ]:
            assert agent._route_provider(r) == "local"

    @pytest.mark.parametrize("ratio", ["4K", "4KPortrait", "Map"])
    def test_routing_on_high_resolution_stays_on_gemini(self, ratio, monkeypatch):
        """When routing is enabled, the 4K-tier and Map calls stay on
        Gemini regardless of ``self.provider``. FLUX doesn't support
        4K natively in the current spec."""
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        agent = _FakeImageAgent(provider="local")
        assert agent._route_provider(ratio) == "gemini"

    @pytest.mark.parametrize(
        "ratio", ["Portrait", "Landscape", "2K", "2KPortrait", "1:1", "16:9"]
    )
    def test_routing_on_default_route_is_flux(self, ratio, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        agent = _FakeImageAgent(provider="local")
        assert agent._route_provider(ratio) == "flux"

    def test_routing_on_overrides_self_provider(self, monkeypatch):
        """The routing layer doesn't read ``self.provider`` when on —
        a Gemini-configured agent still routes 2K to FLUX."""
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        agent = _FakeImageAgent(provider="gemini")
        assert agent._route_provider("2K") == "flux"
        assert agent._route_provider("4K") == "gemini"


# ---------------------------------------------------------------------------
# ImageAgent._estimate_cost_usd — lookup + wildcard + unknown=0.0
# ---------------------------------------------------------------------------


class TestEstimateCostUsd:
    def test_gemini_size_specific_costs_match_table(self):
        agent = _FakeImageAgent()
        for size in ("0.5K", "1K", "2K", "4K"):
            expected = _COST_USD[("gemini", size)]
            assert agent._estimate_cost_usd("gemini", size) == expected

    def test_flux_uses_wildcard(self):
        """FLUX is a flat-rate provider — any size key resolves via
        the ``("flux", "*")`` wildcard."""
        agent = _FakeImageAgent()
        for size in ("0.5K", "1K", "2K", "4K", "anything-future"):
            assert agent._estimate_cost_usd("flux", size) == 0.040

    def test_local_provider_costs_zero(self):
        """Local provider runs on operator hardware — modeled as $0."""
        agent = _FakeImageAgent()
        for size in ("0.5K", "1K", "2K", "4K"):
            assert agent._estimate_cost_usd("local", size) == 0.0

    def test_unknown_provider_returns_zero(self):
        """Telemetry must never raise on the image-gen hot path. An
        unknown provider returns 0.0 rather than KeyError — this is
        the silent-degradation contract documented in the source."""
        agent = _FakeImageAgent()
        assert agent._estimate_cost_usd("not-a-provider", "2K") == 0.0

    def test_gemini_unknown_size_returns_zero(self):
        """No (gemini, *) wildcard exists, so an unknown size for
        gemini returns 0.0 instead of falling through to FLUX's rate."""
        agent = _FakeImageAgent()
        assert agent._estimate_cost_usd("gemini", "Z9K") == 0.0


# ---------------------------------------------------------------------------
# ImageAgent._resolve_fallback — _UNSET sentinel semantics
# ---------------------------------------------------------------------------


class TestResolveFallback:
    def test_unset_resolves_to_self_fallback(self):
        from autonomous.ai.imageagent import _UNSET
        agent = _FakeImageAgent(provider="gemini", fallback_provider="local")
        assert agent._resolve_fallback(_UNSET) == "local"

    def test_unset_with_no_self_fallback_returns_none(self):
        from autonomous.ai.imageagent import _UNSET
        agent = _FakeImageAgent(provider="gemini", fallback_provider=None)
        assert agent._resolve_fallback(_UNSET) is None

    def test_explicit_none_disables_fallback(self):
        """Passing None explicitly overrides ``self.fallback_provider``
        — the _UNSET sentinel exists specifically to distinguish
        "default" from "disable" since both can read as None."""
        agent = _FakeImageAgent(provider="gemini", fallback_provider="local")
        assert agent._resolve_fallback(None) is None

    def test_explicit_string_overrides_self_fallback(self):
        agent = _FakeImageAgent(provider="gemini", fallback_provider="local")
        assert agent._resolve_fallback("flux") == "flux"


# ---------------------------------------------------------------------------
# BaseAgent — FLUX registry + client choices
# ---------------------------------------------------------------------------


class TestBaseAgentRegistry:
    def test_flux_is_in_model_registry(self):
        from autonomous.ai.baseagent import BaseAgent
        from autonomous.ai.models.flux import FluxAIModel
        assert BaseAgent.MODEL_REGISTRY["flux"] is FluxAIModel

    def test_flux_is_an_accepted_client_choice(self):
        """The vendored ReferenceAttr enforces ``choices=[...]`` at
        save-time. If FluxAIModel isn't in the list, saving an agent
        with a FluxAIModel client would raise a ValidationError.

        The vendored mongoengine fork stores ``choices`` as class
        names (strings), not class objects — that's an implementation
        detail of the ReferenceAttr descriptor. Pin by name string.
        """
        from autonomous.ai.baseagent import BaseAgent
        choices = BaseAgent.client.choices
        assert "FluxAIModel" in choices

    def test_other_providers_still_registered(self):
        """Adding flux must not have displaced any existing provider."""
        from autonomous.ai.baseagent import BaseAgent
        for name in ("local", "gemini", "openai", "mock"):
            assert name in BaseAgent.MODEL_REGISTRY


# ---------------------------------------------------------------------------
# MockAIModel — absorbs new kwargs without TypeError
# ---------------------------------------------------------------------------


class TestMockAbsorbsNewKwargs:
    @pytest.fixture
    def mock(self):
        from autonomous.ai.models.mock_model import MockAIModel
        return MockAIModel.__new__(MockAIModel)

    def test_generate_image_accepts_fallback_provider_kwarg(self, mock):
        """The new ImageAgent.generate signature forwards
        ``fallback_provider`` to the provider — the mock must absorb
        it rather than raise TypeError."""
        # Should not raise — return value is the mock image bytes.
        out = mock.generate_image(
            prompt="x", fallback_provider="local"
        )
        assert isinstance(out, bytes) and len(out) > 0

    def test_generate_image_accepts_route_kwarg(self, mock):
        out = mock.generate_image(prompt="x", route=False)
        assert isinstance(out, bytes)

    def test_generate_image_accepts_arbitrary_future_kwarg(self, mock):
        """**kwargs absorb is what makes the mock forward-compatible
        with future provider-level kwargs added by ImageAgent."""
        out = mock.generate_image(prompt="x", some_future_thing=42)
        assert isinstance(out, bytes)

    def test_upscale_image_accepts_new_kwargs(self, mock):
        out = mock.upscale_image(
            prompt="x",
            image_content=b"in",
            fallback_provider="local",
            route=True,
            extra=None,
        )
        assert isinstance(out, bytes)
