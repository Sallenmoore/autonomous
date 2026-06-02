import os

from autonomous import log
from autonomous.ai import image_cache
from autonomous.ai.baseagent import BaseAgent
from autonomous.model.autoattr import StringAttr


# Sentinel object distinguishes "caller did not pass kwarg" from
# "caller explicitly passed None to disable fallback"
_UNSET = object()


# Quality dial maps a caller-facing intent ("draft" / "standard" / "high")
# to an effective aspect_ratio sent to the provider. The aspect_ratio
# vocabulary is the providers' existing one — we just remap it before
# dispatch so callers don't have to know which ratio tier costs what.
#
# "standard" passes through the caller's aspect_ratio unchanged so the
# default behavior of every existing caller is preserved.
_QUALITY_ASPECT_MAP = {
    "draft": {
        "2KPortrait": "9:16",
        "4KPortrait": "9:16",
        "Portrait": "9:16",
        "2K": "16:9",
        "4K": "16:9",
        "Landscape": "16:9",
    },
    "standard": {},
    "high": {
        "2K": "4K",
        "2KPortrait": "4KPortrait",
        "Landscape": "4K",
        "Portrait": "4KPortrait",
    },
}


def _hybrid_upscale_enabled() -> bool:
    return os.environ.get("IMAGE_HYBRID_UPSCALE", "").lower() in {"1", "true", "yes"}


def _routing_enabled() -> bool:
    """True iff IMAGE_PROVIDER_ROUTING is set to a truthy string."""
    return os.environ.get("IMAGE_PROVIDER_ROUTING", "").lower() in {
        "1", "true", "yes"
    }


# Static cost-estimate table — useful for trend/comparison, NOT for
# audit-grade billing. Replace with parsed billing data in a follow-up
# (see specs/2026-06-02-image-gen-cost-design.md "Necessary follow-ups").
_COST_USD = {
    ("gemini", "0.5K"): 0.012,
    ("gemini", "1K"):   0.039,
    ("gemini", "2K"):   0.078,
    ("gemini", "4K"):   0.155,
    ("flux",   "*"):    0.040,
    ("local",  "*"):    0.000,
}


class ImageAgent(BaseAgent):
    name = StringAttr(default="imageagent")

    provider = StringAttr(default="local")

    fallback_provider = StringAttr(default=None)

    instructions = StringAttr(
        default="You are highly skilled AI trained to assist with generating images."
    )
    description = StringAttr(
        default="A helpful AI assistant trained to assist with generating images."
    )

    def _resolve_aspect_ratio(self, aspect_ratio: str, quality: str) -> str:
        """Apply the quality dial to derive the effective aspect_ratio.

        Unknown qualities pass the caller's aspect_ratio through
        unchanged so a typo never silently downgrades a high-quality
        request.
        """
        overrides = _QUALITY_ASPECT_MAP.get(quality)
        if overrides is None:
            return aspect_ratio
        return overrides.get(aspect_ratio, aspect_ratio)

    def _route_provider(self, aspect_ratio: str) -> str:
        """Resolve which provider actually receives the call.

        When IMAGE_PROVIDER_ROUTING is off (default), returns
        ``self.provider`` unchanged. When on, dispatches by aspect_ratio
        tier — high-resolution / map calls stay on Gemini, everything
        else routes to FLUX. ``self.provider`` is the *requested*
        provider; this method returns the *effective* provider.
        """
        if not _routing_enabled():
            return self.provider
        if aspect_ratio in {"4K", "4KPortrait", "Map"}:
            return "gemini"
        return "flux"

    def _estimate_cost_usd(self, provider: str, size: str) -> float:
        """Look up the static per-call cost estimate. Returns 0.0 for
        unknown (provider, size) tuples — silently rather than raising,
        because telemetry must never break an image-gen call."""
        if (provider, size) in _COST_USD:
            return _COST_USD[(provider, size)]
        if (provider, "*") in _COST_USD:
            return _COST_USD[(provider, "*")]
        return 0.0

    def _resolve_fallback(self, fallback_provider):
        """Apply the _UNSET-sentinel resolution rule.

        Returns the effective fallback provider string, or None to
        disable fallback for this call.
        """
        if fallback_provider is _UNSET:
            return self.fallback_provider
        return fallback_provider

    def generate(
        self,
        prompt,
        negative_prompt="blurry, low quality, distorted, deformed, disfigured, poorly drawn",
        files=None,
        aspect_ratio="2KPortrait",
        style=None,
        temperature=None,
        quality="standard",
    ):
        effective_ratio = self._resolve_aspect_ratio(aspect_ratio, quality)

        self.add_to_job_meta("prompt", prompt)
        self.add_to_job_meta("provider", self.provider)
        self.add_to_job_meta("quality", quality)
        self.add_to_job_meta("aspect_ratio", effective_ratio)

        key = image_cache.cache_key(
            prompt=prompt,
            negative_prompt=negative_prompt,
            style=style,
            aspect_ratio=effective_ratio,
            files=files,
            provider=self.provider,
            method="generate",
        )
        cached = image_cache.get(key)
        if cached is not None:
            log(
                f"Image cache HIT key={key[:12]} provider={self.provider}",
                _print=False,
            )
            return cached

        result = self.get_client(self.provider).generate_image(
            prompt,
            negative_prompt=negative_prompt,
            aspect_ratio=effective_ratio,
            files=files,
            style=style,
        )

        # Hybrid path: when the caller asked Gemini for a high-resolution
        # output (2K/4K) AND the operator opted in via env var, hand the
        # Gemini base bytes to the local upscaler. The local upscaler runs
        # on operator-controlled infrastructure rather than a per-call
        # paid API, so we get the resolution without paying Gemini for
        # the upscale tier. Sets ``hybrid_upscale`` job-meta to
        # ``succeeded`` / ``failed:<exc-class>`` / ``returned-base`` so a
        # billing-conscious caller can detect a silent-downgrade.
        if (
            result
            and self.provider == "gemini"
            and _hybrid_upscale_enabled()
            and effective_ratio in {"2K", "2KPortrait", "4K", "4KPortrait"}
        ):
            try:
                local_client = self.MODEL_REGISTRY["local"](
                    name=f"{self.name}-hybrid-upscaler",
                    instructions=self.instructions,
                    description=self.description,
                )
                upscaled = local_client.upscale_image(
                    prompt,
                    image_content=result,
                    aspect_ratio=effective_ratio,
                    style=style,
                )
                # Fall back to the Gemini base on any falsy upscale —
                # operator gets degraded resolution but not a broken
                # response. The ``returned-base`` breadcrumb makes this
                # visible to the job-meta consumer.
                if upscaled and upscaled is not result:
                    result = upscaled
                    self.add_to_job_meta("hybrid_upscale", "succeeded")
                else:
                    self.add_to_job_meta("hybrid_upscale", "returned-base")
            except (OSError, ValueError, RuntimeError) as exc:
                log(
                    f"Hybrid upscale failed; using Gemini base image: {exc}",
                    _print=False,
                )
                self.add_to_job_meta(
                    "hybrid_upscale", f"failed:{type(exc).__name__}"
                )

        if result:
            image_cache.put(key, result)
        return result

    def upscale(
        self,
        prompt,
        image_content=None,
        aspect_ratio="2KPortrait",
        style=None,
        quality="standard",
    ):
        effective_ratio = self._resolve_aspect_ratio(aspect_ratio, quality)
        provider = os.environ.get("IMAGE_AI_AGENT", self.provider)

        key = image_cache.cache_key(
            prompt=prompt,
            style=style,
            aspect_ratio=effective_ratio,
            files=image_content,
            provider=provider,
            method="upscale",
        )
        cached = image_cache.get(key)
        if cached is not None:
            log(
                f"Image cache HIT key={key[:12]} provider={provider} (upscale)",
                _print=False,
            )
            return cached

        result = self.get_client(provider).upscale_image(
            prompt,
            image_content=image_content,
            aspect_ratio=effective_ratio,
            style=style,
        )
        # Provider-agnostic no-op detection: gemini.upscale_image and the
        # local "size already matches target" branch both return the input
        # bytes unchanged. ``is`` is cheap and reliable here because both
        # implementations return the exact ``image_content`` reference
        # rather than a copy. Surface as ``upscale_supported=False`` so
        # callers don't silently see bytes-in-equal-bytes-out as success.
        if result is image_content:
            self.add_to_job_meta("upscale_supported", False)
        if result:
            image_cache.put(key, result)
        return result
