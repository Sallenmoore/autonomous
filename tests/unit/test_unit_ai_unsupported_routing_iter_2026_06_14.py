"""Independent coverage for PR #123 — `NotSupportedByProvider` migration
of flux + openai_compat adapters (#47 slice 2).

Dev's committed test for this PR (`TestSlice2UnsupportedDeclarations`
appended to `test_unit_ai_protocol_conformance.py`) verifies each
newly-declared method raises and that the typed exception attributes
populate. That's the existence proof.

This file covers behavior the dev test doesn't:

- **Routing-hint discoverability.** The point of upgrading from a
  raw `NotImplementedError` to `NotSupportedByProvider` is so users
  reading the error see *which adapter to use instead*. Pin the
  hint text — naming the fallback provider is the value-add.
- **`generate_audio` migration.** Dev's runtime tests stop at the
  Protocol-scoped methods; this one's outside slice 1 scope but
  was still migrated in PR #123 (per the diff). Without coverage
  it could regress silently.
- **Dispatch-layer routing simulation.** The `.method` / `.provider`
  attributes exist so callers can fall back to a different provider.
  Exercise the catch-and-reroute pattern end-to-end across the two
  adapters this slice touched.
- **OpenAI's new explicit signatures.** Dev's signature test runs
  through the conformance catalog. Mine pins each new kwarg accepts
  without raising TypeError on the dispatch shape (positional + kw
  mixed), which the *args/**kwargs version trivially accepted but
  the new explicit form has to consciously preserve.
- **Flux's existing image methods still work.** Slice 2 only added
  the missing-method declarations; verify the pre-existing
  `generate_image` / `upscale_image` signatures didn't drift.

If the typed exception's routing hint gets stripped, `generate_audio`
regresses to raw NotImplementedError, or the new explicit OpenAI
signatures lose a kwarg the dispatch layer sends — dev's test stays
green and mine catches it.
"""

from __future__ import annotations

import inspect

import pytest

from autonomous.ai.models.flux import FluxAIModel
from autonomous.ai.models.openai_compat import OpenAIClient
from autonomous.ai.protocol import NotSupportedByProvider


def _new_flux() -> FluxAIModel:
    # Bypass __init__ — instantiation would hit AutoModel descriptor +
    # MongoDB connection paths. We're testing method-body behavior,
    # not construction.
    return FluxAIModel.__new__(FluxAIModel)


def _new_openai() -> OpenAIClient:
    return OpenAIClient.__new__(OpenAIClient)


class TestFluxRoutingHints:
    """The Flux declarations name the fallback provider explicitly.

    Discoverability matters: a developer hitting one of these from
    code reads the error message and knows immediately to try
    `provider='local'` (Ollama) or `'openai'`. If the hint text is
    refactored into a generic "not supported", users have to grep
    the source to discover the routing options.
    """

    def test_generate_json_hint_names_local_and_openai_fallbacks(self):
        flux = _new_flux()
        with pytest.raises(NotSupportedByProvider) as exc_info:
            flux.generate_json("any prompt")
        rendered = str(exc_info.value)
        assert "local" in rendered
        assert "openai" in rendered

    def test_generate_transcription_hint_names_local_and_openai(self):
        flux = _new_flux()
        with pytest.raises(NotSupportedByProvider) as exc_info:
            flux.generate_transcription(b"some-audio-bytes")
        rendered = str(exc_info.value)
        assert "local" in rendered
        assert "openai" in rendered

    def test_generate_json_hint_explains_image_only_constraint(self):
        # Naming WHY (image-only) helps users build the right mental
        # model — they stop trying to coerce flux to text tasks.
        flux = _new_flux()
        with pytest.raises(NotSupportedByProvider) as exc_info:
            flux.generate_json("any prompt")
        assert "image-only" in str(exc_info.value).lower()


class TestOpenAIRoutingHints:
    """OpenAI's image methods name the IMAGE_AI_AGENT env var.

    The hint reproduces the configuration switch — readers don't
    have to chase down the dispatch code to learn how to opt into
    a different provider. Preserve that.
    """

    def test_generate_image_hint_names_image_ai_agent_env(self):
        client = _new_openai()
        with pytest.raises(NotSupportedByProvider) as exc_info:
            client.generate_image("a watercolor of a fjord")
        rendered = str(exc_info.value)
        assert "IMAGE_AI_AGENT" in rendered
        assert "gemini" in rendered

    def test_upscale_image_hint_names_image_ai_agent_env(self):
        client = _new_openai()
        with pytest.raises(NotSupportedByProvider) as exc_info:
            client.upscale_image("upscale this", image_content=b"placeholder")
        rendered = str(exc_info.value)
        assert "IMAGE_AI_AGENT" in rendered
        assert "gemini" in rendered

    def test_generate_audio_hint_names_tts_ai_agent_env(self):
        # PR #123 migrated generate_audio too (out of slice 1 scope
        # but on the same file). Routes via TTS_AI_AGENT, distinct
        # env var from the image methods.
        client = _new_openai()
        with pytest.raises(NotSupportedByProvider) as exc_info:
            client.generate_audio("read this")
        rendered = str(exc_info.value)
        assert "TTS_AI_AGENT" in rendered


class TestGenerateAudioMigration:
    """Outside slice 1's Protocol scope but migrated in PR #123.

    Dev's slice-2 runtime tests cover the four Protocol methods; this
    file is the only coverage `generate_audio` gets. If the migration
    is reverted (back to raw NotImplementedError), dev's slice-2
    runtime checks stay green and this test fails.
    """

    def test_raises_typed_exception(self):
        client = _new_openai()
        with pytest.raises(NotImplementedError) as exc_info:
            client.generate_audio("read this aloud")
        assert isinstance(exc_info.value, NotSupportedByProvider)

    def test_method_and_provider_populated(self):
        client = _new_openai()
        with pytest.raises(NotSupportedByProvider) as exc_info:
            client.generate_audio("anything")
        assert exc_info.value.method == "generate_audio"
        assert exc_info.value.provider == "openai_compat"

    def test_preserves_args_kwargs_signature(self):
        # The migration intentionally keeps generate_audio on
        # *args/**kwargs because audio isn't in AIModelProtocol yet
        # (per the PR body). Verify the shape didn't tighten by
        # accident — a tightened signature here would break callers
        # mid-migration.
        sig = inspect.signature(OpenAIClient.generate_audio)
        kinds = {p.kind for p in sig.parameters.values() if p.name != "self"}
        assert inspect.Parameter.VAR_POSITIONAL in kinds
        assert inspect.Parameter.VAR_KEYWORD in kinds


class TestDispatchLayerRoutingPattern:
    """End-to-end simulation of the dispatch-layer fallback pattern
    the typed exception was designed to enable.

    Pattern: ImageAgent tries openai_compat; on
    `NotSupportedByProvider`, introspects `.method` and routes the
    same call to a different provider. This proves the wiring works
    across multiple adapters in this slice (flux + openai_compat),
    not just that the exception type carries fields.
    """

    def _attempt(self, adapter, method_name, *args, **kwargs):
        """Mock dispatch: catch typed exception → return routing decision."""
        try:
            getattr(adapter, method_name)(*args, **kwargs)
            return ("succeeded", None)
        except NotSupportedByProvider as exc:
            return ("routed", {"method": exc.method, "provider": exc.provider})

    def test_openai_image_call_routes_via_provider_attribute(self):
        outcome, info = self._attempt(_new_openai(), "generate_image", "x")
        assert outcome == "routed"
        assert info == {"method": "generate_image", "provider": "openai_compat"}

    def test_flux_json_call_routes_via_provider_attribute(self):
        outcome, info = self._attempt(_new_flux(), "generate_json", "x")
        assert outcome == "routed"
        assert info == {"method": "generate_json", "provider": "flux"}

    def test_different_providers_distinguishable_after_catch(self):
        # If a caller polls both adapters, the `.provider` attr is
        # what disambiguates which side declined. Verify they're
        # actually different values.
        _, flux_info = self._attempt(_new_flux(), "generate_json", "x")
        _, oai_info = self._attempt(_new_openai(), "generate_image", "x")
        assert flux_info["provider"] != oai_info["provider"]


class TestOpenAIExplicitSignaturesAcceptDispatchKwargs:
    """The migration from `*args/**kwargs` to explicit signatures has
    to consciously preserve every kwarg the dispatch layer sends.

    `*args/**kwargs` trivially accepts anything; the new explicit
    form has to enumerate the kwargs exhaustively. Verify each
    Protocol kwarg is accepted (the call raises NotSupportedByProvider
    rather than TypeError "unexpected keyword argument").
    """

    def test_generate_image_accepts_negative_prompt_kwarg(self):
        client = _new_openai()
        with pytest.raises(NotSupportedByProvider):
            client.generate_image("prompt", negative_prompt="ugly")

    def test_generate_image_accepts_files_kwarg(self):
        client = _new_openai()
        with pytest.raises(NotSupportedByProvider):
            client.generate_image("prompt", files=[b"source-img"])

    def test_generate_image_accepts_aspect_ratio_kwarg(self):
        client = _new_openai()
        with pytest.raises(NotSupportedByProvider):
            client.generate_image("prompt", aspect_ratio="1KSquare")

    def test_generate_image_accepts_style_kwarg(self):
        client = _new_openai()
        with pytest.raises(NotSupportedByProvider):
            client.generate_image("prompt", style="watercolor")

    def test_generate_image_rejects_unknown_kwarg(self):
        # Other side of the explicit-signature coin: unknown kwargs
        # now blow up at the boundary (which is the right failure mode
        # — the dispatch layer would be silently dropping data
        # otherwise). The *args/**kwargs shape couldn't distinguish.
        client = _new_openai()
        with pytest.raises(TypeError):
            client.generate_image("prompt", made_up_kwarg=42)

    def test_upscale_image_accepts_image_content_kwarg(self):
        client = _new_openai()
        with pytest.raises(NotSupportedByProvider):
            client.upscale_image("prompt", image_content=b"img-bytes")

    def test_upscale_image_accepts_aspect_ratio_kwarg(self):
        client = _new_openai()
        with pytest.raises(NotSupportedByProvider):
            client.upscale_image("prompt", aspect_ratio="2KPortrait")


class TestFluxPreExistingMethodsUntouched:
    """Slice 2 added new declarations to FluxAIModel — verify the
    pre-existing image methods didn't drift.

    The diff for PR #123 should only have inserted methods at the
    end of FluxAIModel. Signature inspection on the pre-existing
    `generate_image` / `upscale_image` is the cheap way to confirm
    the migration didn't accidentally rewrite them.
    """

    def test_generate_image_signature_preserved(self):
        # FluxAIModel.generate_image existed before this slice with
        # its own signature; just confirm it's still callable as a
        # method (not converted to an unsupported-stub).
        method = getattr(FluxAIModel, "generate_image", None)
        assert method is not None
        sig = inspect.signature(method)
        # Has positional `prompt` (canonical) — not a sentinel of
        # full equivalence, but a fast smoke that we didn't replace
        # this with a no-arg stub.
        assert "prompt" in sig.parameters

    def test_upscale_image_signature_preserved(self):
        method = getattr(FluxAIModel, "upscale_image", None)
        assert method is not None
        sig = inspect.signature(method)
        assert "image_content" in sig.parameters

    def test_generate_image_not_replaced_with_stub(self):
        # If slice 2 mistakenly overwrote Flux's generate_image with
        # an unsupported-stub, calling it would raise
        # NotSupportedByProvider before reaching the real body.
        # Source inspection: the method's body must NOT just raise
        # the typed exception immediately.
        src = inspect.getsource(FluxAIModel.generate_image)
        assert "NotSupportedByProvider" not in src
