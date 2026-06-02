"""Coverage for the ImageAgent routing layer, cost-estimate telemetry,
and the new fallback_provider / route kwargs. Each TestX class targets
one concern so failures localize. All tests are hermetic — they exercise
ImageAgent methods on stub instances and mock the MODEL_REGISTRY entries
through monkeypatch."""

import pytest

from autonomous.ai.imageagent import ImageAgent, _COST_USD


def _agent():
    """Bare ImageAgent that bypasses AutoModel persistence but still
    supports StringAttr descriptor reads/writes.

    Initializes the two AutoModel internals StringAttr.__set__ and
    .__get__ assume exist: ``_data`` (the field-storage dict) and
    ``_initialised`` (the change-tracking flag — set False to skip
    the dirty-tracking branch that requires more Document setup).
    """
    agent = ImageAgent.__new__(ImageAgent)
    agent._data = {}
    agent._initialised = False
    # Pre-populate _data with field defaults so descriptor __get__ has
    # values to return; tests that call _set_provider() will overwrite.
    agent._data['provider'] = 'local'
    return agent


class TestEstimateCostUsd:
    def test_gemini_known_sizes(self):
        for size, expected in [
            ("0.5K", 0.012), ("1K", 0.039), ("2K", 0.078), ("4K", 0.155),
        ]:
            assert ImageAgent._estimate_cost_usd(_agent(), "gemini", size) == expected

    def test_flux_wildcard(self):
        assert ImageAgent._estimate_cost_usd(_agent(), "flux", "Portrait") == 0.040
        assert ImageAgent._estimate_cost_usd(_agent(), "flux", "4K") == 0.040

    def test_local_wildcard_zero(self):
        assert ImageAgent._estimate_cost_usd(_agent(), "local", "2K") == 0.0

    def test_unknown_provider_returns_zero(self):
        assert ImageAgent._estimate_cost_usd(_agent(), "mock", "2K") == 0.0

    def test_unknown_size_falls_through_to_wildcard(self):
        # gemini at an unmapped size falls through to ("gemini", "*") if
        # present; absent, returns 0.0. Today gemini has no "*" entry, so
        # this asserts the "graceful 0.0" tail.
        assert ImageAgent._estimate_cost_usd(_agent(), "gemini", "MysterySize") == 0.0


def test_cost_table_keys_are_complete():
    """The cost table covers every (provider, size) tuple the routing
    layer can dispatch. If a future change adds a new size, the table
    must be updated so cost telemetry doesn't silently zero out."""
    expected_gemini_sizes = {"0.5K", "1K", "2K", "4K"}
    assert {size for (p, size) in _COST_USD if p == "gemini"} == expected_gemini_sizes


class TestRouteProvider:
    """Routing matrix: every aspect_ratio × routing-on/off × self.provider
    combination must resolve correctly. Aspect-ratio names match the
    keys the existing _QUALITY_ASPECT_MAP can emit."""

    HIGH_TIER = {"4K", "4KPortrait", "Map"}
    LOW_AND_MID_TIER = {
        "Portrait", "Landscape", "2K", "2KPortrait",
        "1:1", "3:4", "4:3", "9:16", "16:9",
    }

    def _set_provider(self, agent, provider):
        """Set provider in _data so descriptor __get__ reads the new value."""
        agent._data["provider"] = provider

    def test_routing_off_passes_through(self, monkeypatch):
        monkeypatch.delenv("IMAGE_PROVIDER_ROUTING", raising=False)
        agent = _agent()
        self._set_provider(agent, "gemini")
        for ratio in self.HIGH_TIER | self.LOW_AND_MID_TIER:
            assert ImageAgent._route_provider(agent, ratio) == "gemini", ratio

    def test_routing_on_high_tier_to_gemini(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        agent = _agent()
        self._set_provider(agent, "flux")  # even if caller asked flux
        for ratio in self.HIGH_TIER:
            assert ImageAgent._route_provider(agent, ratio) == "gemini", ratio

    def test_routing_on_low_mid_tier_to_flux(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        agent = _agent()
        self._set_provider(agent, "gemini")  # even if caller asked gemini
        for ratio in self.LOW_AND_MID_TIER:
            assert ImageAgent._route_provider(agent, ratio) == "flux", ratio

    def test_routing_env_truthy_values(self, monkeypatch):
        agent = _agent()
        self._set_provider(agent, "gemini")
        for val in ("1", "true", "TRUE", "yes", "Yes"):
            monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", val)
            assert ImageAgent._route_provider(agent, "Portrait") == "flux", val

    def test_routing_env_falsy_values(self, monkeypatch):
        agent = _agent()
        self._set_provider(agent, "gemini")
        for val in ("0", "false", "no", "", "off"):
            monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", val)
            assert ImageAgent._route_provider(agent, "Portrait") == "gemini", val


class TestFallbackResolution:
    """The _UNSET sentinel distinguishes 'caller did not pass kwarg'
    from 'caller passed None to disable.' Instance default is used when
    the kwarg is _UNSET; explicit None disables fallback; explicit string
    selects that provider."""

    def test_unset_inherits_instance_default(self):
        from autonomous.ai.imageagent import ImageAgent, _UNSET
        agent = _agent()
        agent._data["fallback_provider"] = "gemini"
        assert ImageAgent._resolve_fallback(agent, _UNSET) == "gemini"

    def test_explicit_none_disables_fallback(self):
        from autonomous.ai.imageagent import ImageAgent
        agent = _agent()
        agent._data["fallback_provider"] = "gemini"
        assert ImageAgent._resolve_fallback(agent, None) is None

    def test_explicit_string_overrides_instance_default(self):
        from autonomous.ai.imageagent import ImageAgent
        agent = _agent()
        agent._data["fallback_provider"] = "gemini"
        assert ImageAgent._resolve_fallback(agent, "local") == "local"

    def test_unset_with_no_instance_default_returns_none(self):
        from autonomous.ai.imageagent import ImageAgent, _UNSET
        agent = _agent()
        # Don't set fallback_provider — should default to None via StringAttr(default=None)
        assert ImageAgent._resolve_fallback(agent, _UNSET) is None


class _StubProviderClient:
    """Records calls to generate_image; returns deterministic bytes."""

    def __init__(self, name, bytes_=b"img"):
        self.name = name
        self.bytes_ = bytes_
        self.calls = []

    def generate_image(self, prompt, negative_prompt="", aspect_ratio="",
                       files=None, style=None):
        self.calls.append({
            "prompt": prompt, "aspect_ratio": aspect_ratio,
            "negative_prompt": negative_prompt,
        })
        return self.bytes_

    def upscale_image(self, prompt, image_content=None,
                      aspect_ratio="", style=None):
        self.calls.append({"prompt": prompt, "upscale": True})
        return image_content


def _patched_agent(monkeypatch, clients_by_provider):
    """Build an ImageAgent that routes get_client to provided stubs and
    captures add_to_job_meta calls."""
    from autonomous.ai.imageagent import ImageAgent
    agent = _agent()
    agent._data["provider"] = "gemini"
    agent._data["fallback_provider"] = None
    agent._meta_log = []

    def fake_get_client(provider):
        return clients_by_provider[provider]
    agent.get_client = fake_get_client

    def fake_add_meta(k, v):
        agent._meta_log.append((k, v))
    agent.add_to_job_meta = fake_add_meta

    # Default: short-circuit the cache (treat as miss + no-op put).
    from autonomous.ai import image_cache
    monkeypatch.setattr(image_cache, "get", lambda _: None)
    monkeypatch.setattr(image_cache, "put", lambda *_a, **_k: None)
    return agent


class TestGenerateDispatch:
    def test_routing_off_uses_self_provider(self, monkeypatch):
        monkeypatch.delenv("IMAGE_PROVIDER_ROUTING", raising=False)
        from autonomous.ai.imageagent import ImageAgent
        gemini = _StubProviderClient("gemini")
        flux = _StubProviderClient("flux")
        agent = _patched_agent(monkeypatch, {"gemini": gemini, "flux": flux})

        ImageAgent.generate(agent, "prompt", aspect_ratio="Portrait")

        assert len(gemini.calls) == 1
        assert flux.calls == []

    def test_routing_on_low_tier_uses_flux(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        from autonomous.ai.imageagent import ImageAgent
        gemini = _StubProviderClient("gemini")
        flux = _StubProviderClient("flux")
        agent = _patched_agent(monkeypatch, {"gemini": gemini, "flux": flux})

        ImageAgent.generate(agent, "prompt", aspect_ratio="Portrait")

        assert len(flux.calls) == 1
        assert gemini.calls == []

    def test_routing_on_high_tier_uses_gemini(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        from autonomous.ai.imageagent import ImageAgent
        gemini = _StubProviderClient("gemini")
        flux = _StubProviderClient("flux")
        agent = _patched_agent(monkeypatch, {"gemini": gemini, "flux": flux})
        agent._data["provider"] = "flux"   # even when caller asked flux

        ImageAgent.generate(agent, "prompt", aspect_ratio="4K")

        assert len(gemini.calls) == 1
        assert flux.calls == []

    def test_route_false_bypasses_routing(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        from autonomous.ai.imageagent import ImageAgent
        gemini = _StubProviderClient("gemini")
        flux = _StubProviderClient("flux")
        agent = _patched_agent(monkeypatch, {"gemini": gemini, "flux": flux})
        agent._data["provider"] = "gemini"

        ImageAgent.generate(agent, "prompt", aspect_ratio="Portrait",
                            route=False)

        # routing would have picked flux; route=False keeps gemini
        assert len(gemini.calls) == 1
        assert flux.calls == []


class TestGenerateCostTelemetry:
    def test_writes_cost_estimate_to_job_meta(self, monkeypatch):
        monkeypatch.delenv("IMAGE_PROVIDER_ROUTING", raising=False)
        from autonomous.ai.imageagent import ImageAgent
        agent = _patched_agent(
            monkeypatch, {"gemini": _StubProviderClient("gemini")}
        )

        ImageAgent.generate(agent, "prompt", aspect_ratio="Portrait")

        cost_entries = [v for k, v in agent._meta_log if k == "cost_estimate_usd"]
        assert cost_entries == [0.012]   # gemini @ 0.5K

    def test_writes_effective_provider_to_job_meta(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        from autonomous.ai.imageagent import ImageAgent
        agent = _patched_agent(
            monkeypatch,
            {"gemini": _StubProviderClient("gemini"), "flux": _StubProviderClient("flux")},
        )

        ImageAgent.generate(agent, "prompt", aspect_ratio="Portrait")

        eff = [v for k, v in agent._meta_log if k == "effective_provider"]
        assert eff == ["flux"]


class _RaisingProviderClient:
    """Provider stub that always raises on generate_image."""

    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def generate_image(self, *_a, **_k):
        self.calls += 1
        raise self.exc

    def upscale_image(self, *_a, **_k):
        raise self.exc


class TestGenerateFallback:
    def test_fallback_on_routed_provider_failure(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        from autonomous.ai.imageagent import ImageAgent
        flux = _RaisingProviderClient(RuntimeError("flux down"))
        gemini = _StubProviderClient("gemini", bytes_=b"gemini-img")
        agent = _patched_agent(monkeypatch, {"flux": flux, "gemini": gemini})

        result = ImageAgent.generate(
            agent, "prompt",
            aspect_ratio="Portrait",
            fallback_provider="gemini",
        )

        assert result == b"gemini-img"
        assert flux.calls == 1
        assert len(gemini.calls) == 1
        # job_meta breadcrumbs
        flags = {k: v for k, v in agent._meta_log}
        assert flags["provider_fallback_used"] is True
        assert flags["effective_provider"] == "gemini"   # updated after fallback
        # cost reflects the actual provider — gemini Portrait → 0.5K = 0.012
        assert flags["cost_estimate_usd"] == 0.012

    def test_no_fallback_when_kwarg_is_none(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        from autonomous.ai.imageagent import ImageAgent
        flux = _RaisingProviderClient(RuntimeError("flux down"))
        gemini = _StubProviderClient("gemini")
        agent = _patched_agent(monkeypatch, {"flux": flux, "gemini": gemini})
        agent._data["fallback_provider"] = "gemini"  # instance default

        with pytest.raises(RuntimeError, match="flux down"):
            ImageAgent.generate(
                agent, "prompt",
                aspect_ratio="Portrait",
                fallback_provider=None,   # explicit override of instance default
            )
        assert gemini.calls == []

    def test_inherits_instance_fallback_when_kwarg_unset(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        from autonomous.ai.imageagent import ImageAgent
        flux = _RaisingProviderClient(RuntimeError("flux down"))
        gemini = _StubProviderClient("gemini", bytes_=b"gem")
        agent = _patched_agent(monkeypatch, {"flux": flux, "gemini": gemini})
        agent._data["fallback_provider"] = "gemini"

        result = ImageAgent.generate(
            agent, "prompt", aspect_ratio="Portrait"
        )
        assert result == b"gem"

    def test_fallback_itself_raises_propagates(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        from autonomous.ai.imageagent import ImageAgent
        flux = _RaisingProviderClient(RuntimeError("flux down"))
        gemini = _RaisingProviderClient(RuntimeError("gemini also down"))
        agent = _patched_agent(monkeypatch, {"flux": flux, "gemini": gemini})

        with pytest.raises(RuntimeError, match="gemini also down"):
            ImageAgent.generate(
                agent, "prompt", aspect_ratio="Portrait",
                fallback_provider="gemini",
            )

        flags = {k: v for k, v in agent._meta_log}
        assert flags["provider_fallback_used"] is True
        assert flags["fallback_succeeded"] is False


class TestHybridUpscaleEffectiveProvider:
    """The hybrid-upscale gate must look at the *effective* provider
    (after routing), not self.provider. Otherwise a routing-on call to
    FLUX would still trigger the local upscaler designed for Gemini
    output."""

    def test_hybrid_not_invoked_when_effective_provider_is_flux(
        self, monkeypatch
    ):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        monkeypatch.setenv("IMAGE_HYBRID_UPSCALE", "1")

        from autonomous.ai.imageagent import ImageAgent
        flux = _StubProviderClient("flux", bytes_=b"flux-base")
        local = _StubProviderClient("local")
        agent = _patched_agent(monkeypatch, {"flux": flux, "local": local})
        agent._data["provider"] = "gemini"   # requested
        # Wire MODEL_REGISTRY["local"] to a class that returns our stub.
        class _LocalCls:
            def __init__(self, **kw):
                pass
            def upscale_image(self, *a, **k):
                local.calls.append({"upscale": True})
                return b"upscaled"
        agent.MODEL_REGISTRY = {"local": _LocalCls}

        ImageAgent.generate(
            agent, "prompt", aspect_ratio="2K"
        )   # routes to flux

        assert flux.calls != []
        assert local.calls == []   # local upscaler NOT invoked

    def test_hybrid_invoked_when_effective_provider_is_gemini(
        self, monkeypatch
    ):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        monkeypatch.setenv("IMAGE_HYBRID_UPSCALE", "1")

        from autonomous.ai.imageagent import ImageAgent
        gemini = _StubProviderClient("gemini", bytes_=b"gem-base")
        local_calls = []

        class _LocalCls:
            def __init__(self, **kw):
                pass
            def upscale_image(self, *a, **k):
                local_calls.append({"upscale": True})
                return b"upscaled"

        agent = _patched_agent(monkeypatch, {"gemini": gemini})
        agent._data["provider"] = "gemini"
        agent.MODEL_REGISTRY = {"local": _LocalCls}

        ImageAgent.generate(
            agent, "prompt", aspect_ratio="4K"
        )   # 4K routes to gemini

        assert local_calls == [{"upscale": True}]


class TestUpscaleDispatch:
    def test_upscale_writes_cost_and_provider_meta(self, monkeypatch):
        monkeypatch.delenv("IMAGE_PROVIDER_ROUTING", raising=False)
        from autonomous.ai.imageagent import ImageAgent
        gemini = _StubProviderClient("gemini")
        agent = _patched_agent(monkeypatch, {"gemini": gemini})

        ImageAgent.upscale(
            agent, "prompt", image_content=b"in", aspect_ratio="2KPortrait"
        )

        flags = {k: v for k, v in agent._meta_log}
        assert flags["effective_provider"] == "gemini"
        assert flags["cost_estimate_usd"] == 0.078   # gemini 2K

    def test_upscale_honors_route_false(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        from autonomous.ai.imageagent import ImageAgent
        gemini = _StubProviderClient("gemini")
        flux = _StubProviderClient("flux")
        agent = _patched_agent(monkeypatch, {"gemini": gemini, "flux": flux})
        agent._data["provider"] = "gemini"

        ImageAgent.upscale(
            agent, "prompt", image_content=b"in",
            aspect_ratio="2KPortrait", route=False
        )

        # routing would have picked flux for 2KPortrait
        assert any("upscale" in c for c in gemini.calls)
        assert flux.calls == []
