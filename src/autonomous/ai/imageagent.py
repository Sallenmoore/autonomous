import os

from autonomous import log
from autonomous.ai import image_cache
from autonomous.ai.baseagent import BaseAgent
from autonomous.model.autoattr import StringAttr
from autonomous.ai._credentials import client_key_scope


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


def _aspect_to_size_token(aspect_ratio: str) -> str:
    """Map effective aspect_ratio to the cost-table size key.

    The cost table is keyed by provider + size class. Raw aspect tokens
    (Portrait, Landscape, 1:1, 16:9, etc.) bill at the provider's
    cheapest tier (gemini=0.5K for Portrait per the spec mapping;
    gemini=1K for Landscape). Tier tokens (2K, 2KPortrait, 4K, etc.)
    bill at their named size.
    """
    if aspect_ratio in {"2K", "2KPortrait"}:
        return "2K"
    if aspect_ratio in {"4K", "4KPortrait", "Map"}:
        return "4K"
    if aspect_ratio == "Landscape":
        return "1K"
    # Portrait + bare aspect ratios fall through to 0.5K (the cheap default)
    return "0.5K"


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

    def _route_provider(self, aspect_ratio: str, requested: str | None = None) -> str:
        """Resolve which provider actually receives the call.

        Only entered when the caller passed ``route=True`` — both
        ``generate`` and ``upscale`` short-circuit to a direct provider
        choice when ``route=False`` without entering this method. So
        the breadcrumb logic below only ever fires on the routing-ON
        path; the routing-off return at the top is for the
        ``IMAGE_PROVIDER_ROUTING`` env-var disabled case, not the
        per-call ``route=False`` case.

        When ``IMAGE_PROVIDER_ROUTING`` is off (default), returns
        ``self.provider`` immediately and emits no log. When on,
        dispatches by aspect_ratio tier (high-resolution / map →
        Gemini, else FLUX).

        ``requested`` is the provider the caller asked for. ``generate``
        does NOT thread an env-var override, so ``requested`` defaults
        to ``self.provider`` and the breadcrumb compares the routing
        decision against the agent instance's provider. ``upscale``
        threads the ``IMAGE_AI_AGENT`` env-var (falling back to
        ``self.provider``) through as ``requested``, so the breadcrumb
        on the upscale path names the env-overridden provider when set.
        The asymmetry is intentional — only ``upscale`` is the place ops
        switch providers per-request via env today.

        Emits a one-line ``log()`` whenever routing re-targets the
        provider (``effective != requested``). Without this the silent
        fallback path that hid issue #34 (FLUX FieldDoesNotExist → every
        FLUX call degraded to Gemini for an unknown duration) would
        remain invisible to operators reading prod logs.
        """
        if not _routing_enabled():
            return self.provider
        if requested is None:
            requested = self.provider
        if aspect_ratio in {"4K", "4KPortrait", "Map"}:
            effective = "gemini"
        else:
            effective = "flux"
        if effective != requested:
            log(
                f"Image route: requested={requested} effective={effective} "
                f"ratio={aspect_ratio}",
                _print=True,
            )
        return effective

    def _estimate_cost_usd(self, provider: str, size: str) -> float:
        """Look up the static per-call cost estimate. Returns 0.0 for
        unknown (provider, size) tuples — pure dict lookup that never
        raises (telemetry on the image-gen hot path must not be a
        failure source). Note this only guarantees *this lookup* is
        safe — the surrounding ``add_to_job_meta`` calls in
        ``generate``/``upscale`` can still raise if the meta sink is
        broken; see the broader contract at the call sites."""
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
        fallback_provider=_UNSET,
        route=True,
        api_key=None,
    ):
        effective_ratio = self._resolve_aspect_ratio(aspect_ratio, quality)
        effective_provider = (
            self._route_provider(effective_ratio) if route else self.provider
        )
        effective_fallback = self._resolve_fallback(fallback_provider)

        self.add_to_job_meta("prompt", prompt)
        self.add_to_job_meta("provider", self.provider)
        self.add_to_job_meta("effective_provider", effective_provider)
        self.add_to_job_meta("quality", quality)
        self.add_to_job_meta("aspect_ratio", effective_ratio)

        size_token = _aspect_to_size_token(effective_ratio)

        key = image_cache.cache_key(
            prompt=prompt,
            negative_prompt=negative_prompt,
            style=style,
            aspect_ratio=effective_ratio,
            files=files,
            provider=effective_provider,
            method="generate",
        )
        cached = image_cache.get(key)
        if cached is not None:
            log(
                f"Image cache HIT key={key[:12]} provider={effective_provider}",
                _print=False,
            )
            # Cache hit incurs zero real cost — billing telemetry must
            # reflect that. Setting the estimate AFTER the cache check
            # (rather than before) keeps the breadcrumb honest.
            self.add_to_job_meta("cost_estimate_usd", 0.0)
            return cached

        # Cache miss — we will actually dispatch to a provider, so the
        # estimate reflects the chargeable call.
        self.add_to_job_meta(
            "cost_estimate_usd",
            self._estimate_cost_usd(effective_provider, size_token),
        )

        # BYOK (#227): ``api_key`` overrides this provider's credential for
        # THIS call only. It is bound against the PRIMARY client's
        # ``API_KEY_ENV``, so the fallback leg below — a different provider —
        # reads its own credential and uses the deployment default. A user's
        # key is never sent to a provider it was not issued for.
        try:
            client = self.get_client(effective_provider)
            with client_key_scope(client, api_key):
                result = client.generate_image(
                    prompt,
                    negative_prompt=negative_prompt,
                    aspect_ratio=effective_ratio,
                    files=files,
                    style=style,
                )
        except Exception as exc:
            if effective_fallback is None or effective_fallback == effective_provider:
                raise
            log(
                f"Image gen fell back from {effective_provider} to "
                f"{effective_fallback}: {type(exc).__name__}: {exc}",
                _print=True,
            )
            self.add_to_job_meta("provider_fallback_used", True)
            # Stash the original error in job-meta so the operator can
            # see WHY we fell back even after a successful fallback.
            self.add_to_job_meta(
                "original_provider_error",
                f"{type(exc).__name__}: {exc}",
            )
            try:
                result = self.get_client(effective_fallback).generate_image(
                    prompt,
                    negative_prompt=negative_prompt,
                    aspect_ratio=effective_ratio,
                    files=files,
                    style=style,
                )
                self.add_to_job_meta("fallback_succeeded", True)
                # Update effective-provider + cost to reflect reality.
                effective_provider = effective_fallback
                self.add_to_job_meta("effective_provider", effective_provider)
                self.add_to_job_meta(
                    "cost_estimate_usd",
                    self._estimate_cost_usd(effective_provider, size_token),
                )
                # Recompute the cache key under the actual provider so future
                # direct-FLUX requests don't find Gemini bytes (see spec
                # "Cache key semantics on fallback"). The cost-amplification
                # variant: while FLUX is failing, every FLUX-routed call
                # misses the FLUX cache, falls back to Gemini, and bills the
                # Gemini call — rewriting the key under Gemini lets the next
                # identical request hit cache instead of billing again.
                key = image_cache.cache_key(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    style=style,
                    aspect_ratio=effective_ratio,
                    files=files,
                    provider=effective_provider,
                    method="generate",
                )
            except Exception as fallback_exc:
                self.add_to_job_meta("fallback_succeeded", False)
                # Chain via `from exc` so the operator sees BOTH the
                # fallback failure (now) and the original provider error
                # (the cause) in the traceback.
                raise fallback_exc from exc

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
            and effective_provider == "gemini"
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
            except Exception as exc:
                # Hybrid upscale is opt-in (IMAGE_HYBRID_UPSCALE env).
                # A failure here must NOT lose the successful Gemini
                # base image — the caller would prefer the lower-res
                # Gemini bytes over a 500. Broad except covers all the
                # ways the local upscaler can fail: requests.Timeout
                # (not OSError-derived), PIL.UnidentifiedImageError,
                # KeyError/AttributeError from a malformed media-API
                # JSON response. The breadcrumb carries the exception
                # class so an operator can grep for systemic failures.
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
        fallback_provider=_UNSET,
        route=True,
        api_key=None,
    ):
        effective_ratio = self._resolve_aspect_ratio(aspect_ratio, quality)
        requested = os.environ.get("IMAGE_AI_AGENT", self.provider)
        effective_provider = (
            self._route_provider(effective_ratio, requested=requested)
            if route
            else requested
        )
        effective_fallback = self._resolve_fallback(fallback_provider)

        size_token = _aspect_to_size_token(effective_ratio)
        self.add_to_job_meta("effective_provider", effective_provider)
        self.add_to_job_meta(
            "cost_estimate_usd",
            self._estimate_cost_usd(effective_provider, size_token),
        )

        key = image_cache.cache_key(
            prompt=prompt,
            style=style,
            aspect_ratio=effective_ratio,
            files=image_content,
            provider=effective_provider,
            method="upscale",
        )
        cached = image_cache.get(key)
        if cached is not None:
            log(
                f"Image cache HIT key={key[:12]} provider={effective_provider} (upscale)",
                _print=False,
            )
            return cached

        # BYOK (#227): ``api_key`` overrides this provider's credential for
        # THIS call only. It is bound against the PRIMARY client's
        # ``API_KEY_ENV``, so the fallback leg below — a different provider —
        # reads its own credential and uses the deployment default. A user's
        # key is never sent to a provider it was not issued for.
        try:
            client = self.get_client(effective_provider)
            with client_key_scope(client, api_key):
                result = client.upscale_image(
                    prompt,
                    image_content=image_content,
                    aspect_ratio=effective_ratio,
                    style=style,
                )
        except Exception as exc:
            if effective_fallback is None or effective_fallback == effective_provider:
                raise
            log(
                f"Upscale fell back from {effective_provider} to "
                f"{effective_fallback}: {type(exc).__name__}: {exc}",
                _print=True,
            )
            self.add_to_job_meta("provider_fallback_used", True)
            self.add_to_job_meta(
                "original_provider_error",
                f"{type(exc).__name__}: {exc}",
            )
            try:
                result = self.get_client(effective_fallback).upscale_image(
                    prompt,
                    image_content=image_content,
                    aspect_ratio=effective_ratio,
                    style=style,
                )
                self.add_to_job_meta("fallback_succeeded", True)
                effective_provider = effective_fallback
                self.add_to_job_meta("effective_provider", effective_provider)
                self.add_to_job_meta(
                    "cost_estimate_usd",
                    self._estimate_cost_usd(effective_provider, size_token),
                )
                key = image_cache.cache_key(
                    prompt=prompt,
                    style=style,
                    aspect_ratio=effective_ratio,
                    files=image_content,
                    provider=effective_provider,
                    method="upscale",
                )
            except Exception as fallback_exc:
                self.add_to_job_meta("fallback_succeeded", False)
                raise fallback_exc from exc

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
