"""FluxAIModel — fal.ai-hosted FLUX.1 [pro] image generation adapter.

A third paid image provider alongside ``GeminiAIModel`` and
``LocalAIModel``. Targets cost reduction at Imagen-comparable creative
quality: ~$0.04/image at fal.ai vs. Gemini's $0.04 (1K) / $0.08 (2K) /
$0.16 (4K) per image.

v1 scope is text-to-image only — ``files=`` raises NotImplementedError.
img2img via fal.ai's redux/kontext endpoints is a necessary follow-up
(see specs/2026-06-02-image-gen-cost-design.md).

Auth: ``FAL_KEY`` env var. Module imports cleanly without it; the
first dispatch raises a RuntimeError with a pointer to the env var.

HTTP: ``autonomous.http.HttpClient`` (#50 slice E). Pre-migration this
was a bare ``_SESSION = requests.Session()`` plus an inner ``_post()``
that ``autonomous.ai.retry.retry`` wrapped for bounded retries. The
migration moves the retry policy onto the HttpClient instance and
deletes the inner-function dance — same observable behavior, less code.
"""

import json

import requests

from autonomous import log
from autonomous.ai._extract import extract_or_malformed
from autonomous.ai.exceptions import (
    GenerateImageEmptyResponseError,
    MalformedResponseError,
)
from autonomous.ai._credentials import resolve_api_key
from autonomous.ai._image_utils import resolve_image_config
from autonomous.ai.protocol import NotSupportedByProvider
from autonomous.config import settings
from autonomous.http import HttpClient
from autonomous.model.autoattr import StringAttr
from autonomous.model.automodel import AutoModel


# Module-level HTTP client for fal.ai (#50 slice E).
#
# Pre-migration the retry policy was an outer ``retry(_post, max_attempts,
# sleep_seconds, catch=(requests.RequestException,))`` wrapping an inner
# ``_post()`` closure that called ``_SESSION.post``. HttpClient absorbs
# that pattern — its constructor takes ``max_attempts`` + ``retry_backoff``
# directly, and the wrapping happens inside ``HttpClient.request``. The
# call sites below collapse to ``_HTTP.post(...)`` / ``_HTTP.get(...)``.
#
# Defaults:
# - ``timeout=None``: each call site already passes ``timeout=self._media_timeout``.
# - ``max_attempts=settings.flux_max_attempts``: same default the previous
#   ``retry(...)`` call read from the same setting (``flux_max_attempts``,
#   default 3).
# - ``retry_backoff=settings.flux_retry_sleep``: same default the previous
#   ``retry(...)`` call read from the same setting (``flux_retry_sleep``,
#   default 1.0).
# - ``transport_error_cls=requests.ConnectionError`` (#85): narrowed
#   from ``requests.RequestException`` because the broader parent
#   class made ``HttpClient._attempt``'s ``raise_for_status``-raised
#   ``HTTPError`` match the retry catch tuple (``HTTPError`` is-a
#   ``RequestException``), so 4xx responses that AREN'T in
#   ``transport_failure_codes`` would still burn the retry budget via
#   the catch-tuple branch. With ``ConnectionError`` as the catch
#   class, ``HTTPError`` no longer matches — 4xx fails fast at the
#   altitude layer (the per-call ``max_attempts=1`` override on the
#   CDN GET that #77 added becomes redundant for the
#   ``raise_for_status`` 4xx case, though it still short-circuits
#   the ``transport_failure_codes`` 5xx case which the CDN can also
#   produce). Downstream catch ``except (requests.RequestException,
#   ValueError, OSError)`` in ``generate_image`` still matches because
#   ``ConnectionError`` is-a ``RequestException``. Trade-off: the
#   line-307 re-raise in HttpClient now wraps Timeout /
#   ChunkedEncodingError as ConnectionError too, which is a slight
#   semantic distortion — the original is preserved on ``__cause__``,
#   so observability that walks the chain still sees the true type.
#
# **Behavior change vs the pre-migration retry shape:** the GET to
# fetch the generated image from fal.ai's CDN ran OUTSIDE the retry
# loop (only the POST was retried). Post-migration, HttpClient applies
# the same retry policy to both ``_HTTP.post`` and ``_HTTP.get``, so a
# transient CDN failure now retries 3× instead of failing immediately.
# Documented in MIGRATIONS.md.
#
# Tests monkeypatch ``flux._HTTP`` directly (for non-retry paths) or
# ``flux._HTTP.session.request`` (for retry paths, so HttpClient's
# internal retry wrapper actually fires). The pre-migration
# ``_SESSION`` attribute is not preserved as an alias — same rationale
# as slices C/D: ``session.post`` is bypassed by ``session.request``.
# ``transport_failure_codes={408, 429}`` (#89): #85's narrowing of
# ``transport_error_cls`` to ``ConnectionError`` made every
# ``raise_for_status``-raised HTTPError fail fast — correct for permanent
# 4xx (expired signed URL, 403, 404) but it also caught transient
# **429 Too Many Requests** from fal.ai burst-throttling, which pre-#85
# retried under the ``flux_max_attempts`` budget. Routing 408/429 through
# the ``is_transport_failure`` branch wraps them as the configured
# ``transport_error_cls`` (ConnectionError) so the retry loop engages
# again — same shape as openai_compat's 401→HPCUnreachableError extra.
# Permanent 4xx still fail fast (they're not in the set). The CDN GET
# leg passes ``max_attempts=1`` so a 429 there still short-circuits
# (a near-expired signed URL races the clock — see ``generate_image``).
_HTTP = HttpClient(
    timeout=None,
    max_attempts=settings.flux_max_attempts,
    retry_backoff=settings.flux_retry_sleep,
    transport_error_cls=requests.ConnectionError,
    transport_failure_codes=frozenset({408, 429}),
)


class FluxAIModel(AutoModel):
    _client = None

    # BaseAgent.get_client constructs every provider with
    # ``name=`` / ``instructions=`` / ``description=`` kwargs forwarded
    # from the agent instance. The other adapters inherit these via
    # BaseAgent's MRO; FluxAIModel inherits AutoModel directly. Without
    # these StringAttr declarations the Document's strict-field
    # validator raises ``FieldDoesNotExist`` and every routed-to-FLUX
    # call fails before any HTTP work. The fields are no-ops for fal.ai
    # (the API doesn't consume them) but they satisfy the Mongo schema.
    name = StringAttr(default="flux_agent")
    instructions = StringAttr(
        default="You are an AI image generation assistant using FLUX.1 [pro]."
    )
    description = StringAttr(
        default="FLUX.1 [pro] image generation adapter (fal.ai)."
    )

    # Model defaults are env-overridable so deployments can chase fal.ai's
    # model churn without a library release. Read from the central typed
    # catalog (autonomous.config) — guarded parsing means a malformed
    # FLUX_TIMEOUT_S falls back to the default instead of crashing import.
    _image_model = settings.flux_image_model
    _image_url_base = settings.flux_url_base
    _media_timeout = settings.flux_timeout_s
    # ``_max_attempts`` and ``_retry_sleep`` (settings.flux_max_attempts /
    # settings.flux_retry_sleep) used to live here as class attrs the
    # inner ``_post()`` retry wrapper read. Post-#50-slice-E the retry
    # config lives on ``_HTTP`` at module scope (read from the same
    # settings keys at module load). Tests that previously did
    # ``monkeypatch.setattr(FluxAIModel, "_retry_sleep", 0.0)`` to speed
    # up retry tests should instead do ``monkeypatch.setattr(_HTTP,
    # "retry_backoff", 0.0)``.

    # Per-(ratio, tier) wire-shape mapping for fal.ai. Pre-#149 these
    # branches were inline in _get_image_config; pulling the vocabulary
    # parse out lets us collapse the duplicated mapping with Gemini.
    _FLUX_SIZE_BY_RATIO_TIER = {
        ("16:9", "2K"): "landscape_4_3",
        ("3:4",  "2K"): "portrait_4_3",
        ("16:9", "4K"): "landscape_16_9",
        ("3:4",  "4K"): "portrait_16_9",
    }

    def _get_image_config(self, aspect_ratio_input):
        """Map autonomous's aspect-ratio vocabulary to fal.ai's
        ``(aspect_ratio, image_size)`` pair.

        fal.ai accepts ``aspect_ratio`` from {1:1, 16:9, 9:16, 4:3, 3:4,
        ...} and ``image_size`` from a preset enum
        (square/square_hd/portrait_4_3/portrait_16_9/landscape_4_3/
        landscape_16_9). The canonical vocabulary parse lives in
        ``_image_utils.resolve_image_config``; this method only
        translates the canonical ``(ratio, tier)`` to fal's wire shape.
        """
        ratio, tier = resolve_image_config(aspect_ratio_input)
        size = self._FLUX_SIZE_BY_RATIO_TIER.get((ratio, tier), "square_hd")
        return ratio, size

    # BYOK (#227): the env var holding this provider's credential.
    # ``BaseAgent`` binds a per-call ``api_key=`` against THIS name, so a
    # key issued for one provider can never be sent to another on a
    # fallback leg. An adapter that omits it silently ignores overrides.
    API_KEY_ENV = "FAL_KEY"

    def _require_api_key(self):
        """Resolve FAL_KEY at call time, not import time. A per-call
        BYOK override (#227) wins over the environment. Raises with a
        pointer to the env var if missing — easier to debug than a 401
        from fal.ai's API."""
        key = resolve_api_key(self.API_KEY_ENV).strip()
        if not key:
            raise RuntimeError(
                "FluxAIModel: FAL_KEY environment variable is not set. "
                "Set it (e.g. `export FAL_KEY=fal-...`) or configure the "
                "fallback_provider on the ImageAgent."
            )
        return key

    def generate_image(
        self,
        prompt,
        negative_prompt="",
        files=None,
        aspect_ratio="2KPortrait",
        style="",
    ):
        """Text-to-image via fal.ai FLUX.1 [pro].

        Raises ``NotImplementedError`` if ``files`` is non-empty —
        img2img is a v1.1 follow-up. Honors ``negative_prompt`` (unlike
        Gemini, which silently drops it)."""
        if files:
            raise NotImplementedError(
                "FluxAIModel does not yet support img2img via files=. "
                "Use provider='gemini' for this call, or set route=False "
                "on the ImageAgent call. See "
                "specs/2026-06-02-image-gen-cost-design.md."
            )

        api_key = self._require_api_key()
        ratio, size = self._get_image_config(aspect_ratio)

        style_payload = ""
        if isinstance(style, dict):
            style_payload = json.dumps(style)
        elif isinstance(style, str) and style:
            style_payload = json.dumps({"style": style})

        full_prompt = f"{prompt}. {style_payload}".strip(". ").strip()

        body = {
            "prompt": full_prompt,
            "aspect_ratio": ratio,
            "image_size": size,
            "num_images": 1,
            "enable_safety_checker": False,
        }
        if negative_prompt:
            body["negative_prompt"] = negative_prompt

        url = f"{self._image_url_base}/{self._image_model}"
        headers = {
            "Authorization": f"Key {api_key}",
            "Content-Type": "application/json",
        }

        try:
            # HttpClient runs the configured retry policy
            # (max_attempts + retry_backoff from settings) and calls
            # raise_for_status before returning, so a non-2xx exhausts
            # the retry budget and raises requests.RequestException
            # (the configured transport_error_cls) on exit. The pre-
            # migration inner ``_post()`` + ``retry(...)`` wrapper did
            # exactly this; HttpClient just absorbs the pattern.
            resp = _HTTP.post(
                url, headers=headers, json=body, timeout=self._media_timeout
            )

            # Issue #226: fal.ai runs its safety checker regardless of
            # the ``enable_safety_checker: False`` we send above, and a
            # trip is reported as HTTP 200 whose ``images[0].url`` points
            # at a solid-black frame, flagged by ``has_nsfw_concepts``
            # (some model families spell it ``nsfw_content_detected``).
            # Returning those bytes as a success stored a black square as
            # the caller's image AND kept ImageAgent's fallback_provider
            # from ever firing, because nothing raised. This is the same
            # event Gemini reports as a SAFETY finish_reason, so it raises
            # the same deterministic error: re-asking with the same prompt
            # is blocked again, so the caller should re-route, not retry.
            # Checked here rather than inside the extractor below because
            # ``GenerateImageEmptyResponseError`` subclasses ``ValueError``
            # and ``extract_or_malformed`` would rewrite it into a
            # ``MalformedResponseError`` — the body is well-formed; it is
            # the *content* that was refused.
            try:
                flags = resp.json()
            except ValueError:
                # Non-JSON 2xx: leave it to the extractor below, which
                # translates it to MalformedResponseError with an excerpt.
                flags = {}
            if any(flags.get("has_nsfw_concepts") or ()) or any(
                flags.get("nsfw_content_detected") or ()
            ):
                raise GenerateImageEmptyResponseError(
                    "fal.ai safety checker flagged the prompt; the response "
                    "carries a blank frame instead of an image. Re-route to "
                    "another provider (ImageAgent fallback_provider) — "
                    "retrying the same prompt returns the same block."
                )

            # Issue #142: shared malformed-2xx translation. The walk
            # (``payload["images"][0]["url"]`` with explicit empty/missing
            # checks) lives inside the extractor so ``ValueError`` /
            # ``KeyError`` / ``AttributeError`` / ``IndexError`` raised by
            # any step become a single typed ``MalformedResponseError``
            # carrying the body excerpt — symmetric with ``openai_compat``.
            def _extract_image_url(body):
                images = body.get("images") or []
                if not images:
                    raise ValueError(
                        f"fal.ai returned success but no images in response: "
                        f"{body!r}"
                    )
                image_url = images[0].get("url")
                if not image_url:
                    raise ValueError(
                        f"fal.ai response missing image URL: {images[0]!r}"
                    )
                return image_url

            image_url = extract_or_malformed(
                resp, "/fal/generate", _extract_image_url
            )
            # CDN fetch uses ``max_attempts=1`` (issue #77): a fal.ai
            # signed URL that 4xxes is permanently invalid (expired
            # token, deleted image, 403 from key drift), so burning
            # ``flux_max_attempts`` × ``flux_retry_sleep`` worth of
            # retries on it is pure latency waste. The per-call
            # override (HttpClient #77 extension) disables retry for
            # this leg only — the POST above still gets the full
            # ``settings.flux_max_attempts`` budget. Transient 5xx on
            # the CDN now also short-circuits to a single attempt; the
            # tradeoff favours fail-fast over recovery because the
            # signed URL is short-lived anyway and a retry against a
            # near-expired URL races the clock.
            img_resp = _HTTP.get(
                image_url, timeout=self._media_timeout, max_attempts=1
            )
            return img_resp.content
        except (
            requests.RequestException,
            ValueError,
            OSError,
            MalformedResponseError,
        ) as e:
            log(f"==== Error: FLUX image generation failed ==== {e}", _print=True)
            raise

    def upscale_image(
        self, prompt, image_content=None, aspect_ratio="2KPortrait", style=None
    ):
        """FLUX has no dedicated upscaler. Returns ``image_content``
        unchanged — same honest no-op as GeminiAIModel.upscale_image.
        Hybrid upscale via the local provider is the supported path."""
        log(
            "FluxAIModel does not support image upscaling; "
            "returning input image unchanged.",
            _print=False,
        )
        return image_content

    # --- AIModelProtocol conformance (#47 slice 2) -----------------
    # FLUX is image-only. The Protocol still requires every adapter to
    # declare every method so dispatch layers can introspect via
    # NotSupportedByProvider instead of catching the broader
    # AttributeError that "method missing" would otherwise raise.

    def generate_json(
        self,
        message,
        system_prompt=None,
        json_schema=None,
        schema_name="response",
        uri="",
        context=None,
        temperature=None,
        model=None,
        **_kwargs,  # #248 sampling knobs: accepted, ignored
    ):
        raise NotSupportedByProvider(
            method="generate_json",
            provider="flux",
            message=(
                "FluxAIModel is image-only; use provider='local' or "
                "'openai' for JSON generation."
            ),
        )

    def generate_transcription(self, audio_file, prompt=""):
        raise NotSupportedByProvider(
            method="generate_transcription",
            provider="flux",
            message=(
                "FluxAIModel is image-only; use provider='local' or "
                "'openai' for audio transcription."
            ),
        )
