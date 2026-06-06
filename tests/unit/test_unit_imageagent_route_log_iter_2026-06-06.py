"""Independent coverage for PR #41 / issue #36 — ImageAgent operator-visible
log on route re-target.

Issue #36 surfaced a silent-fallback class of bug: when ``_route_provider``
quietly retargeted from the caller's requested provider to a different
effective one, no log line was emitted. Issue #34 (FLUX FieldDoesNotExist)
had previously degraded every FLUX call to Gemini for an unknown duration
because operators had no breadcrumb in prod logs.

PR #41's fix adds a one-line ``log(..., _print=True)`` whenever the routing
branch fires AND ``effective != requested``. The new ``requested`` kwarg on
``_route_provider`` lets ``upscale`` thread the env-var override
(``IMAGE_AI_AGENT``) through so the breadcrumb names what the operator
actually set, not what the agent instance happened to default to.

Contracts pinned here (operator-visible surface — drift breaks log
scrapers / on-call eyes):

1. **Routing OFF preserves silent passthrough** — no log ever, even when
   ``requested != self.provider``. The new log line is scoped to the
   routing-ON branch.
2. **Routing ON, requested == effective** — no log (no re-target to
   report; emitting on no-op would just be noise in steady-state).
3. **Routing ON, requested != effective** — a single ``log()`` call with
   the exact ``requested=``, ``effective=``, ``ratio=`` breadcrumb shape,
   forwarded with ``_print=True`` so it lands on stdout (the
   container-natural surface).
4. **Default ``requested`` is ``self.provider``** — keeps ``generate()``
   (which doesn't pass the kwarg) showing the agent's own provider in the
   breadcrumb.
5. **Explicit ``requested`` overrides ``self.provider`` for the log only**
   — the *return value* still depends on the routing decision, not on the
   ``requested`` arg. Critical so ``upscale``'s env-var threading doesn't
   accidentally change the effective provider.
6. **Every call emits** (no de-dup / caching at this layer). Log throttling
   is the operator's job downstream; the routing layer's job is to leave
   the breadcrumb every time.

Fresh-perspective check: I deliberately did NOT consult dev's local tests
under ``tests/_dev_local/`` (gitignored — invisible in the PR diff).
Tests were derived from the diff in ``src/autonomous/ai/imageagent.py``
between ``_route_provider`` old/new and the ``upscale`` call-site change.
"""

import pytest

from autonomous.ai.imageagent import ImageAgent


def _agent(provider="local"):
    """ImageAgent bypassing AutoModel persistence.

    Same trick as ``tests/unit/test_unit_imageagent_routing.py::_agent`` —
    construct via ``__new__`` and seed ``_data`` so the StringAttr
    descriptors have values to return. Keeping a private factory rather
    than importing the existing one keeps this regression suite
    self-contained (revertable in one ``git rm`` if PR #41 is rolled
    back).
    """
    agent = ImageAgent.__new__(ImageAgent)
    agent._data = {"provider": provider}
    agent._initialised = False
    return agent


# ---------------------------------------------------------------------------
# Contract 1: routing OFF must NOT emit the breadcrumb log
# ---------------------------------------------------------------------------

class TestRoutingOffSilent:
    """When IMAGE_PROVIDER_ROUTING is unset/falsy, ``_route_provider``
    returns ``self.provider`` immediately without consulting ``requested``
    and MUST NOT emit any log line. Operators rely on the routing-OFF
    path being completely silent — surfacing route messages from a path
    that isn't actually routing would be misleading."""

    def test_routing_off_no_log_even_with_mismatched_requested(
        self, monkeypatch, capsys
    ):
        monkeypatch.delenv("IMAGE_PROVIDER_ROUTING", raising=False)
        agent = _agent(provider="gemini")
        # Pass an explicit ``requested`` that differs from self.provider.
        # If the implementation drifted to emit a log in routing-OFF when
        # requested != self.provider, this test would catch it.
        result = ImageAgent._route_provider(agent, "Portrait", requested="flux")
        assert result == "gemini"  # passthrough, not routed
        out = capsys.readouterr().out
        assert "Image route:" not in out, (
            f"routing-OFF must be silent; got stdout: {out!r}"
        )

    def test_routing_off_no_log_without_requested_kwarg(
        self, monkeypatch, capsys
    ):
        monkeypatch.delenv("IMAGE_PROVIDER_ROUTING", raising=False)
        agent = _agent(provider="gemini")
        result = ImageAgent._route_provider(agent, "4K")
        assert result == "gemini"
        out = capsys.readouterr().out
        assert "Image route:" not in out


# ---------------------------------------------------------------------------
# Contract 2: routing ON, no re-target, no log
# ---------------------------------------------------------------------------

class TestRoutingOnNoRetargetSilent:
    """When the routing branch fires but the effective provider equals
    what the caller requested, there's nothing to report. Steady-state
    noise here would drown the real re-target signal."""

    def test_high_tier_requested_gemini_no_log(self, monkeypatch, capsys):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        agent = _agent(provider="gemini")
        # 4K → gemini, requested defaults to self.provider = gemini → match.
        result = ImageAgent._route_provider(agent, "4K")
        assert result == "gemini"
        out = capsys.readouterr().out
        assert "Image route:" not in out

    def test_low_tier_requested_flux_no_log(self, monkeypatch, capsys):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        agent = _agent(provider="flux")
        # Portrait → flux, requested defaults to self.provider = flux → match.
        result = ImageAgent._route_provider(agent, "Portrait")
        assert result == "flux"
        out = capsys.readouterr().out
        assert "Image route:" not in out

    def test_explicit_requested_matches_effective_no_log(
        self, monkeypatch, capsys
    ):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        agent = _agent(provider="gemini")
        # 4K → gemini; explicit requested="gemini" also matches → no log.
        result = ImageAgent._route_provider(agent, "4K", requested="gemini")
        assert result == "gemini"
        out = capsys.readouterr().out
        assert "Image route:" not in out


# ---------------------------------------------------------------------------
# Contract 3: routing ON + re-target → log with breadcrumb fields
# ---------------------------------------------------------------------------

class TestRoutingOnRetargetEmitsLog:
    """The core of #36: when routing flips the provider, the operator gets
    one stdout breadcrumb naming requested vs effective vs ratio. The
    field names are an observability contract — log scrapers grep for
    'Image route:' and parse the kv pairs. Renaming is a downstream
    coordination cost, so we pin them here."""

    def test_low_tier_with_gemini_requested_logs_to_flux(
        self, monkeypatch, capsys
    ):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        agent = _agent(provider="gemini")
        # Portrait → flux, self.provider = gemini → mismatch → log.
        result = ImageAgent._route_provider(agent, "Portrait")
        assert result == "flux"
        out = capsys.readouterr().out
        assert "Image route:" in out
        assert "requested=gemini" in out
        assert "effective=flux" in out
        assert "ratio=Portrait" in out

    def test_high_tier_with_flux_requested_logs_to_gemini(
        self, monkeypatch, capsys
    ):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        agent = _agent(provider="flux")
        result = ImageAgent._route_provider(agent, "4K")
        assert result == "gemini"
        out = capsys.readouterr().out
        assert "Image route:" in out
        assert "requested=flux" in out
        assert "effective=gemini" in out
        assert "ratio=4K" in out

    def test_4kportrait_and_map_also_route_to_gemini_with_log(
        self, monkeypatch, capsys
    ):
        """4KPortrait and Map are in the high-tier set — re-targets the
        same way 4K does and the breadcrumb names the actual ratio so the
        operator can correlate with the call site."""
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        for ratio in ("4KPortrait", "Map"):
            agent = _agent(provider="flux")
            assert ImageAgent._route_provider(agent, ratio) == "gemini"
            out = capsys.readouterr().out
            assert f"ratio={ratio}" in out, (
                f"breadcrumb ratio token must be the original ratio "
                f"({ratio!r}), got stdout: {out!r}"
            )

    def test_log_emitted_every_call_no_dedup(self, monkeypatch, capsys):
        """The route layer leaves a breadcrumb on EVERY re-target.
        De-duping is a downstream concern; if N calls all re-target, ops
        sees N breadcrumbs (until/unless they configure their log pipeline
        to dedup). Don't add caching here without coordinating with #39's
        throttle layer in db_sync."""
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        agent = _agent(provider="gemini")
        for _ in range(3):
            ImageAgent._route_provider(agent, "Portrait")
        out = capsys.readouterr().out
        # Each call must produce its own "Image route:" line.
        assert out.count("Image route:") == 3


# ---------------------------------------------------------------------------
# Contract 4: default ``requested`` is ``self.provider``
# ---------------------------------------------------------------------------

class TestRequestedDefault:
    """Generate() calls ``_route_provider`` without a ``requested`` kwarg —
    the breadcrumb must still name the agent's own provider when the
    re-target fires, so operators reading the log know which agent
    instance was driving the call."""

    def test_default_requested_is_self_provider_in_log(
        self, monkeypatch, capsys
    ):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        agent = _agent(provider="local")  # neither gemini nor flux
        # 4K → gemini, requested defaults to self.provider="local" → mismatch.
        result = ImageAgent._route_provider(agent, "4K")
        assert result == "gemini"
        out = capsys.readouterr().out
        assert "requested=local" in out
        assert "effective=gemini" in out


# ---------------------------------------------------------------------------
# Contract 5: explicit ``requested`` for log, no effect on return value
# ---------------------------------------------------------------------------

class TestExplicitRequestedKwarg:
    """``upscale`` threads the env-var override (``IMAGE_AI_AGENT``) into
    ``requested`` so the breadcrumb names what the operator actually set.
    Critical: the kwarg only affects the LOG LINE, not the routing
    decision — the decision is still driven by aspect_ratio. If a future
    refactor accidentally made ``requested`` change the return value,
    operators would see drift between what the breadcrumb claims and
    what the call actually hit."""

    def test_explicit_requested_does_not_change_return_value(
        self, monkeypatch
    ):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        agent = _agent(provider="gemini")
        # Portrait routes to flux regardless of what ``requested`` says.
        for requested in ("gemini", "flux", "local", "nonsense-provider"):
            result = ImageAgent._route_provider(
                agent, "Portrait", requested=requested
            )
            assert result == "flux", (
                f"routing decision must be aspect_ratio-driven, not "
                f"requested-driven; got {result!r} for requested={requested!r}"
            )

    def test_explicit_requested_drives_log_line(self, monkeypatch, capsys):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        agent = _agent(provider="gemini")
        # self.provider=gemini but caller threads requested="local" (the
        # IMAGE_AI_AGENT env-var case from upscale). Portrait → flux,
        # so the mismatch fires. Breadcrumb must name the EXPLICIT
        # requested, not self.provider.
        ImageAgent._route_provider(agent, "Portrait", requested="local")
        out = capsys.readouterr().out
        assert "requested=local" in out, (
            f"explicit requested must drive the log line, not self.provider; "
            f"got stdout: {out!r}"
        )
        assert "requested=gemini" not in out


# ---------------------------------------------------------------------------
# Contract 6: upscale call-site wires IMAGE_AI_AGENT into ``requested``
# ---------------------------------------------------------------------------

class TestUpscaleCallSiteWiresEnvVar:
    """The upscale call site reads ``os.environ.get('IMAGE_AI_AGENT',
    self.provider)`` and threads that into ``_route_provider`` as
    ``requested``. This test exercises the call-site by patching
    ``_route_provider`` and asserting on what it was called with.

    Note: we mock at the ``_route_provider`` boundary rather than going
    end-to-end through ``get_client(...).upscale_image(...)`` because the
    full path needs HTTP/storage stubs that have nothing to do with the
    routing contract under test. Keeping the test narrow makes the
    failure mode obvious if the wiring drifts."""

    def test_env_override_threads_into_route_provider_requested(
        self, monkeypatch
    ):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        monkeypatch.setenv("IMAGE_AI_AGENT", "env-set-name")

        agent = _agent(provider="gemini")
        # Stub the rest of upscale's dependencies to short-circuit
        # (we only care about how _route_provider gets called).
        from autonomous.ai import image_cache
        monkeypatch.setattr(image_cache, "cache_key", lambda **_kw: "k")
        monkeypatch.setattr(
            image_cache, "get", lambda _key: b"cached-bytes"
        )
        agent.add_to_job_meta = lambda *_a, **_k: None

        captured = {}

        def fake_route_provider(self_, ratio, requested=None):
            captured["ratio"] = ratio
            captured["requested"] = requested
            return "flux"  # arbitrary; cache hit returns before use

        monkeypatch.setattr(
            ImageAgent, "_route_provider", fake_route_provider
        )

        # Drive upscale; the cache hit ends the call before any
        # provider client is touched.
        result = ImageAgent.upscale(agent, prompt="p")
        assert result == b"cached-bytes"

        # The env-var value must have been threaded through as ``requested``.
        assert captured["requested"] == "env-set-name"

    def test_upscale_route_false_does_not_consult_route_provider(
        self, monkeypatch
    ):
        """When ``route=False``, upscale uses ``requested`` directly and
        never calls ``_route_provider``. The new ``requested`` kwarg
        plumbing must not change this behavior — operators rely on
        ``route=False`` being a hard bypass."""
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        monkeypatch.setenv("IMAGE_AI_AGENT", "env-set-name")

        agent = _agent(provider="gemini")
        from autonomous.ai import image_cache
        monkeypatch.setattr(image_cache, "cache_key", lambda **_kw: "k")
        monkeypatch.setattr(
            image_cache, "get", lambda _key: b"cached-bytes"
        )
        agent.add_to_job_meta = lambda *_a, **_k: None

        called = []

        def fake_route_provider(self_, *a, **kw):
            called.append((a, kw))
            return "should-not-matter"

        monkeypatch.setattr(
            ImageAgent, "_route_provider", fake_route_provider
        )

        # route=False short-circuits before _route_provider.
        ImageAgent.upscale(agent, prompt="p", route=False)
        assert called == [], (
            f"route=False must skip _route_provider entirely; "
            f"got calls: {called!r}"
        )


# ---------------------------------------------------------------------------
# Contract 7: the log call uses _print=True (operator-visible on stdout)
# ---------------------------------------------------------------------------

class TestLogPrintFlag:
    """The log line MUST land on stdout (``_print=True``), not just go
    into the file/handler-only logger. Containers without log-file
    collection (the StoryTeller deployment shape) would otherwise miss
    the breadcrumb entirely. capsys captures stdout — if a future
    refactor switched to ``_print=False``, the assertion would catch it
    even without inspecting the call kwargs."""

    def test_log_appears_on_stdout(self, monkeypatch, capsys):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        agent = _agent(provider="gemini")
        ImageAgent._route_provider(agent, "Portrait")
        out = capsys.readouterr().out
        assert "Image route:" in out, (
            "breadcrumb must land on stdout via _print=True; "
            f"got stdout: {out!r}"
        )
