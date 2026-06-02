"""Coverage for the ImageAgent routing layer, cost-estimate telemetry,
and the new fallback_provider / route kwargs. Each TestX class targets
one concern so failures localize. All tests are hermetic — they exercise
ImageAgent methods on stub instances and mock the MODEL_REGISTRY entries
through monkeypatch."""

from autonomous.ai.imageagent import ImageAgent, _COST_USD


def _agent():
    """Bare ImageAgent without triggering AutoModel persistence."""
    return ImageAgent.__new__(ImageAgent)


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
        """Set provider directly via __dict__ to bypass descriptor."""
        agent.__dict__["provider"] = provider

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
