"""LiteLLMImageModel — OpenAI-compatible LiteLLM gateway adapter.

Text / JSON / summary (#264): delegated to an ``OpenAIClient`` retargeted at
``LITELLM_API_BASE_URL`` with the ``LITELLM_*`` models and key, so
``TEXT_AI_AGENT=litellm`` / ``JSON_AI_AGENT=litellm`` / per-call
``provider="litellm"`` route off the single ``HPC_*`` slot while HPC stays
usable side-by-side. Composition, not inheritance: subclassing the
``OpenAIClient`` Document would move this adapter's persisted docs into
OpenAIClient's collection under a new ``_cls`` and orphan existing
references. (The class keeps its historical name for the same reason.)

Images:

Targets an arbitrary OpenAI-compatible image endpoint (a LiteLLM gateway
serving ``POST /v1/images/generations``) so a consumer can set
``IMAGE_AI_AGENT=litellm`` and route entity-image generation through a
shared gateway for unified routing / fallbacks / cost tracking, keeping
the same underlying models (Gemini, FLUX, Imagen) behind the gateway —
a transparent repoint (issue #199, driver: Sallenmoore/StoryTeller#497).

Sibling of ``FluxAIModel`` and ``GeminiAIModel``. Differs from
``OpenAIClient`` (``openai_compat.py``) — which is OpenAI-compatible but
explicitly refuses images (text/embeddings/transcription only) — and from
``FluxAIModel``, which speaks fal.ai's *native* JSON shape rather than the
OpenAI image shape.

v1 scope is text-to-image only — ``files=`` raises ``NotImplementedError``
(same as ``FluxAIModel``), so the ImageAgent caller's existing
``fallback_provider="gemini"`` carries the reference-image / multi-subject
path to direct Gemini unchanged. The OpenAI ``/v1/images/edits``
multi-subject case is a deliberate follow-up.

Auth: ``LITELLM_API_KEY`` → ``Authorization: Bearer``. The header is only
sent when the key is set; gateways that don't enforce auth (e.g. on a
private docker network) work without it.

HTTP: ``autonomous.http.HttpClient`` for transport/retry parity with the
other adapters, and the shared ``extract_or_malformed`` helper for
malformed-2xx translation — exactly as ``flux.py`` does.
"""

import base64

import requests

from autonomous import log
from autonomous.ai._extract import extract_or_malformed
from autonomous.ai._image_utils import resolve_image_config
from autonomous.ai.models.openai_compat import HPCUnreachableError, OpenAIClient
from autonomous.ai.exceptions import MalformedResponseError
from autonomous.ai.protocol import NotSupportedByProvider
from autonomous.config import settings
from autonomous.http import HttpClient
from autonomous.model.autoattr import StringAttr
from autonomous.model.automodel import AutoModel
from autonomous.ai._credentials import resolve_api_key


# Transport tuning. The issue's config surface is exactly three fields
# (base_url / api_key / image_model), so timeout + retry live as module
# literals rather than env-configurable settings — they mirror flux's
# defaults (120s / 3 attempts / 1.0s backoff).
# ponytail: literals, not settings fields; promote to an `ai_litellm`
# timeout/retry group only if a deployment needs to tune them.
_TIMEOUT_S = 120
_MAX_ATTEMPTS = 3
_RETRY_SLEEP = 1.0


# Module-level HTTP client for the gateway (mirrors flux._HTTP). Same
# transport-failure handling as the other OpenAI-shaped adapters:
# ``transport_error_cls=requests.ConnectionError`` so a permanent 4xx
# (bad model, malformed prompt) fails fast at the altitude layer instead
# of burning the retry budget, while transient ``408``/``429`` from the
# gateway route through the transport-failure branch and re-engage retry.
# ``timeout=None`` here because each call site passes ``timeout=`` explicitly.
#
# Tests monkeypatch ``litellm._HTTP`` (non-retry paths) or
# ``litellm._HTTP.session.request`` (retry paths, so the internal retry
# wrapper actually fires).
_HTTP = HttpClient(
    timeout=None,
    max_attempts=_MAX_ATTEMPTS,
    retry_backoff=_RETRY_SLEEP,
    transport_error_cls=requests.ConnectionError,
    transport_failure_codes=frozenset({408, 429}),
)


class LiteLLMImageModel(AutoModel):
    _client = None

    # BaseAgent.get_client constructs every provider with
    # ``name=`` / ``instructions=`` / ``description=`` kwargs. This adapter
    # inherits AutoModel directly (like FluxAIModel), so without these
    # StringAttr declarations the Document's strict-field validator raises
    # ``FieldDoesNotExist`` before any HTTP work. They're no-ops for the
    # gateway (the OpenAI image API doesn't consume them) but satisfy the
    # Mongo schema.
    name = StringAttr(default="litellm_agent")
    instructions = StringAttr(
        default="You are an AI image generation assistant using an "
        "OpenAI-compatible (LiteLLM) gateway."
    )
    description = StringAttr(
        default="OpenAI-compatible LiteLLM gateway adapter (images + text)."
    )

    # Config snapshot from the central typed catalog (autonomous.config),
    # matching openai_compat's class-attr idiom. Read once at import (after
    # load_dotenv); tests monkeypatch the class attrs to retarget.
    _base_url = settings.litellm_image_api_base_url.rstrip("/")
    _api_key = settings.litellm_api_key
    _image_model = settings.litellm_image_model
    _media_timeout = _TIMEOUT_S
    _text_base_url = settings.litellm_api_base_url.rstrip("/")
    _text_model = settings.litellm_text_model
    _json_model = settings.litellm_json_model
    _summary_model = settings.litellm_summary_model

    # OpenAI images/generations accepts a fixed ``size`` enum, not an
    # arbitrary resolution — so we map by aspect-ratio orientation only
    # (the canonical (ratio, tier) tier hint has no OpenAI equivalent; the
    # gateway/underlying model picks the actual pixel budget). The canonical
    # vocabulary parse is shared via ``resolve_image_config`` (#149).
    _OPENAI_SIZE_BY_RATIO = {
        "1:1": "1024x1024",
        "4:3": "1024x1024",
        "3:4": "1024x1792",
        "9:16": "1024x1792",
        "16:9": "1792x1024",
    }

    def _get_image_size(self, aspect_ratio_input):
        """Map autonomous's aspect-ratio vocabulary to an OpenAI ``size``."""
        ratio, _tier = resolve_image_config(aspect_ratio_input)
        return self._OPENAI_SIZE_BY_RATIO.get(ratio, "1024x1024")

    def _images_endpoint(self):
        """Build the ``/v1/images/generations`` URL, tolerating a base that
        already includes ``/v1``.

        The issue spec is ``POST {base}/v1/images/generations``, but the
        OpenAI-compatible convention (and this deployment's own gateway URL)
        commonly bakes ``/v1`` into the base_url. Appending ``/v1``
        unconditionally would 404 on a ``.../v1`` base, so normalize."""
        base = self._base_url.rstrip("/")
        if not base:
            raise RuntimeError(
                "LiteLLMImageModel: LITELLM_IMAGE_API_BASE_URL is not set. "
                "Point it at the gateway (e.g. https://litellm.example/v1) "
                "or configure the fallback_provider on the ImageAgent."
            )
        if base.endswith("/v1"):
            return f"{base}/images/generations"
        return f"{base}/v1/images/generations"

    # BYOK (#227): the env var holding this provider's credential.
    # ``BaseAgent`` binds a per-call ``api_key=`` against THIS name, so a
    # key issued for one provider can never be sent to another on a
    # fallback leg. An adapter that omits it silently ignores overrides.
    API_KEY_ENV = "LITELLM_API_KEY"

    def _headers(self):
        h = {"Content-Type": "application/json"}
        # Only send Bearer auth when a key is configured — gateways on a
        # trusted network may not enforce it; a missing key surfaces as the
        # gateway's own 401 rather than a client-side guess. A per-call
        # BYOK override (#227) wins over the class-attr snapshot.
        if key := resolve_api_key(self.API_KEY_ENV, self._api_key):
            h["Authorization"] = f"Bearer {key}"
        return h

    @staticmethod
    def _extract_image(body):
        """Walk an OpenAI images/generations response to raw bytes or a
        fetchable URL. Runs inside ``extract_or_malformed`` so every
        ``ValueError`` (missing data, bad base64 → binascii.Error) becomes a
        typed ``MalformedResponseError`` with the body excerpt attached —
        symmetric with flux's ``_extract_image_url``."""
        data = body.get("data") or []
        if not data:
            raise ValueError(
                f"litellm returned success but no image data: {body!r}"
            )
        item = data[0]
        b64 = item.get("b64_json")
        if b64:
            return "b64", base64.b64decode(b64)
        url = item.get("url")
        if url:
            return "url", url
        raise ValueError(
            f"litellm image item missing b64_json and url: {item!r}"
        )

    def generate_image(
        self,
        prompt,
        negative_prompt="",
        files=None,
        aspect_ratio="2KPortrait",
        style="",
    ):
        """Text-to-image via the OpenAI ``/v1/images/generations`` shape.

        Raises ``NotImplementedError`` if ``files`` is non-empty — the
        reference-image (``/v1/images/edits``) path is a follow-up; the
        ImageAgent caller's ``fallback_provider="gemini"`` carries it.

        ``negative_prompt`` / ``style`` are accepted for signature parity
        but not wired — the OpenAI images/generations body has no field for
        them (the issue-authoritative body is ``{model, prompt, n, size}``)."""
        if files:
            raise NotImplementedError(
                "LiteLLMImageModel does not support reference-image / img2img "
                "via files= (the OpenAI /v1/images/edits path is a follow-up). "
                "Use provider='gemini' for this call, or rely on the "
                "ImageAgent's fallback_provider='gemini' default."
            )

        url = self._images_endpoint()
        body = {
            "model": self._image_model,
            "prompt": prompt,
            "n": 1,
            "size": self._get_image_size(aspect_ratio),
        }

        try:
            resp = _HTTP.post(
                url, headers=self._headers(), json=body, timeout=self._media_timeout
            )
            kind, value = extract_or_malformed(
                resp, "/litellm/images/generations", self._extract_image
            )
            if kind == "b64":
                return value
            # ``.url`` variant: the gateway returned a link rather than
            # inline base64. Fetch with ``max_attempts=1`` (issue #77
            # rationale) — a signed/short-lived image URL that 4xxes is
            # permanently invalid, so retrying it is pure latency waste.
            img_resp = _HTTP.get(
                value, timeout=self._media_timeout, max_attempts=1
            )
            return img_resp.content
        except (
            requests.RequestException,
            ValueError,
            OSError,
            MalformedResponseError,
        ) as e:
            log(
                f"==== Error: LiteLLM image generation failed ==== {e}",
                _print=True,
            )
            raise

    def upscale_image(
        self, prompt, image_content=None, aspect_ratio="2KPortrait", style=None
    ):
        """No dedicated upscaler on the gateway path. Returns
        ``image_content`` unchanged — the same honest no-op as
        ``FluxAIModel`` / ``GeminiAIModel``."""
        log(
            "LiteLLMImageModel does not support image upscaling; "
            "returning input image unchanged.",
            _print=False,
        )
        return image_content

    # --- Text / JSON / summary (#264) ----------------------------------

    def _text_client(self):
        """A transient ``OpenAIClient`` pointed at the gateway. Built per
        call (never saved) so class-attr monkeypatches retarget it and the
        strict-mode negative cache keys on the gateway URL, not HPC's."""
        base = self._text_base_url.rstrip("/")
        if not base:
            # Same exception the HPC slot raises when unconfigured, so
            # callers' existing handlers cover both providers.
            raise HPCUnreachableError(
                "LITELLM_API_BASE_URL is not configured; cannot reach the "
                "LiteLLM gateway for text/JSON generation."
            )
        if not base.endswith("/v1"):
            base += "/v1"
        client = OpenAIClient(
            name=self.name,
            instructions=self.instructions,
            description=self.description,
        )
        client._base_url = base
        client._api_key = self._api_key
        client._text_model = self._text_model
        client._json_model = self._json_model
        client._summary_model = self._summary_model
        # BYOK (#227): resolve the per-call key under LiteLLM's env var, so
        # an HPC key bound for another leg never reaches the gateway.
        client.API_KEY_ENV = self.API_KEY_ENV
        return client

    def generate_text(self, message, *args, **kwargs):
        return self._text_client().generate_text(message, *args, **kwargs)

    def generate_json(self, message, *args, **kwargs):
        return self._text_client().generate_json(message, *args, **kwargs)

    def summarize_text(self, text, primer="", model=None):
        return self._text_client().summarize_text(text, primer=primer, model=model)

    # --- AIModelProtocol conformance (#47 slice 2) -----------------
    # The Protocol requires every adapter to declare every method so
    # dispatch layers introspect via NotSupportedByProvider instead of
    # catching the broader AttributeError that "method missing" raises.

    def generate_transcription(self, audio_file, prompt=""):
        raise NotSupportedByProvider(
            method="generate_transcription",
            provider="litellm",
            message=(
                "LiteLLMImageModel does not wire transcription; use "
                "provider='local' or 'openai' for audio transcription."
            ),
        )
