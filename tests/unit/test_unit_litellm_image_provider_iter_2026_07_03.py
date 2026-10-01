"""Independent test coverage for the LiteLLM OpenAI-compatible image provider.

PR #200 (dev branch ``iter/2026-07-03-batch``, closes #199) adds
``autonomous.ai.models.litellm.LiteLLMImageModel`` — a new ``ImageAgent``
provider that speaks the OpenAI ``images/generations`` shape against a shared
LiteLLM gateway. It registers under ``BaseAgent.MODEL_REGISTRY["litellm"]``,
maps autonomous's aspect-ratio vocabulary to the OpenAI ``size`` enum by
orientation, tolerates a trailing ``/v1`` on the gateway base URL, sends
``Authorization: Bearer`` only when a key is configured, defers the
reference-image path with ``NotImplementedError`` (so the ImageAgent
``fallback_provider`` engages), and translates malformed-2xx bodies through
the shared ``extract_or_malformed`` helper.

These tests are written from a fresh read of the PR #200 diff — the test
agent's independent second perspective — WITHOUT consulting the dev agent's
gitignored ``tests/_dev_local`` ephemerals. Hermetic: every path that would
reach the gateway monkeypatches ``litellm._HTTP`` (mirrors the flux suite);
no test opens a socket or needs Mongo/Redis/Ollama.
"""

import base64

import pytest
import requests

from autonomous.ai.baseagent import BaseAgent
from autonomous.ai.exceptions import MalformedResponseError
from autonomous.ai.models.litellm import LiteLLMImageModel
from autonomous.ai.protocol import NotSupportedByProvider
from autonomous.config import Settings


def _litellm():
    """Bare ``LiteLLMImageModel`` with no Document/DB construction.

    Same escape hatch the flux suite uses (``FluxAIModel.__new__``): the
    adapter's HTTP methods only read class attrs (``_base_url`` / ``_api_key``
    / ``_image_model`` / ``_media_timeout``), so an uninitialized instance is
    sufficient once those class attrs are monkeypatched by ``_configure``.
    """
    return LiteLLMImageModel.__new__(LiteLLMImageModel)


def _configure(monkeypatch, *, base="https://litellm.example/v1",
               key="sk-test", model="image-flux"):
    """Retarget the import-time config snapshot the adapter reads.

    ``LiteLLMImageModel`` snapshots ``settings.litellm_*`` into class attrs at
    import; the source comment says tests monkeypatch those class attrs. We
    rstrip ``base`` to mirror the source's own ``.rstrip("/")`` at snapshot.
    """
    monkeypatch.setattr(LiteLLMImageModel, "_base_url", base.rstrip("/"))
    monkeypatch.setattr(LiteLLMImageModel, "_api_key", key)
    monkeypatch.setattr(LiteLLMImageModel, "_image_model", model)


class _FakeResponse:
    """Stand-in for ``requests.Response`` — only the surface the adapter and
    ``extract_or_malformed`` touch (``.json()`` / ``.content`` / ``.text`` /
    ``.status_code`` / ``.raise_for_status`` / ``.headers``)."""

    def __init__(self, *, status=200, json_data=None, content=b"", text=""):
        self.status_code = status
        self._json = json_data if json_data is not None else {}
        self.content = content
        self.text = text or repr(self._json)
        self.headers = {"Content-Type": "application/json"}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


# ---------------------------------------------------------------------------
# Registry dispatch — the mechanism ImageAgent uses to route a provider string
# to a client class (BaseAgent.get_client → MODEL_REGISTRY[provider]).
# ---------------------------------------------------------------------------

class TestRegistryDispatch:
    def test_registered_under_litellm_key(self):
        assert BaseAgent.MODEL_REGISTRY.get("litellm") is LiteLLMImageModel

    def test_get_client_routes_litellm_string_to_adapter(self, monkeypatch):
        """The provider string ``"litellm"`` must instantiate the adapter via
        the real ``get_client`` path — the routing contract, exercised
        hermetically with a stub self (no AutoModel/Mongo construction of the
        agent) and ``persist=False`` (no DB writes)."""

        class _StubAgent:
            MODEL_REGISTRY = BaseAgent.MODEL_REGISTRY

            def __init__(self):
                self.provider = "litellm"
                self.name = "stub"
                self.instructions = ""
                self.description = ""
                self.client = None

            def save(self):  # pragma: no cover - persist=False never calls it
                raise AssertionError("save() must not fire with persist=False")

        agent = _StubAgent()
        client = BaseAgent.get_client(agent, persist=False)
        assert isinstance(client, LiteLLMImageModel)
        assert agent.client is client

    def test_unknown_provider_does_not_resolve_to_litellm(self):
        # Guard against a typo'd key silently colliding — only the exact
        # "litellm" string maps here.
        assert BaseAgent.MODEL_REGISTRY.get("lite-llm") is None
        assert BaseAgent.MODEL_REGISTRY.get("litellm_image") is None


# ---------------------------------------------------------------------------
# Aspect-ratio → OpenAI size. OpenAI images/generations takes a fixed size
# enum, so the adapter maps by orientation only (via resolve_image_config).
# ---------------------------------------------------------------------------

class TestImageSizeMapping:
    @pytest.mark.parametrize("aspect_input,expected", [
        ("1:1",        "1024x1024"),   # square
        ("4:3",        "1024x1024"),   # landscape-ish → square bucket
        ("3:4",        "1024x1792"),   # portrait
        ("9:16",       "1024x1792"),   # portrait
        ("16:9",       "1792x1024"),   # landscape
        ("2K",         "1792x1024"),   # resolve → 16:9
        ("2KPortrait", "1024x1792"),   # resolve → 3:4  (adapter default input)
        ("4K",         "1792x1024"),   # resolve → 16:9
        ("4KPortrait", "1024x1792"),   # resolve → 3:4
        ("Portrait",   "1024x1792"),   # resolve → 3:4
        ("Landscape",  "1792x1024"),   # resolve → 16:9
        ("Map",        "1792x1024"),   # resolve → 16:9
    ])
    def test_known_ratios_map_by_orientation(self, aspect_input, expected):
        assert _litellm()._get_image_size(aspect_input) == expected

    def test_unknown_ratio_defaults_to_portrait(self):
        # resolve_image_config's fallback is ("3:4", "low"); the adapter's
        # ratio table maps "3:4" → portrait 1024x1792. So an unrecognized
        # aspect key lands on the portrait bucket, NOT the 1024x1024 default
        # branch (which is unreachable via resolve_image_config's ratio set).
        assert _litellm()._get_image_size("totally-bogus") == "1024x1792"
        assert _litellm()._get_image_size("") == "1024x1792"


# ---------------------------------------------------------------------------
# Base-URL normalization — the issue spec is POST {base}/v1/images/generations
# but the deployment's own gateway URL bakes /v1 into the base. Appending /v1
# unconditionally would 404 a .../v1 base.
# ---------------------------------------------------------------------------

class TestEndpointNormalization:
    def test_bare_host_base_gets_v1_appended(self, monkeypatch):
        _configure(monkeypatch, base="https://litellm.example")
        assert (
            _litellm()._images_endpoint()
            == "https://litellm.example/v1/images/generations"
        )

    def test_base_already_ending_v1_is_not_doubled(self, monkeypatch):
        _configure(monkeypatch, base="https://litellm.example/v1")
        assert (
            _litellm()._images_endpoint()
            == "https://litellm.example/v1/images/generations"
        )

    def test_trailing_slash_is_tolerated(self, monkeypatch):
        # A trailing slash on either shape must not produce a // in the path.
        _configure(monkeypatch, base="https://litellm.example/v1/")
        assert (
            _litellm()._images_endpoint()
            == "https://litellm.example/v1/images/generations"
        )

    def test_empty_base_raises_runtime_error(self, monkeypatch):
        _configure(monkeypatch, base="")
        with pytest.raises(RuntimeError, match="LITELLM_IMAGE_API_BASE_URL"):
            _litellm()._images_endpoint()


# ---------------------------------------------------------------------------
# Auth header — Bearer only when a key is set; omitted otherwise so an
# unauthenticated gateway (private docker net) works and a missing key
# surfaces as the gateway's own 401 rather than a client-side guess.
# ---------------------------------------------------------------------------

class TestAuthHeaders:
    def test_bearer_header_present_with_configured_key(self, monkeypatch):
        _configure(monkeypatch, key="sk-configured")
        headers = _litellm()._headers()
        assert headers["Authorization"] == "Bearer sk-configured"
        assert headers["Content-Type"] == "application/json"

    def test_auth_header_omitted_when_key_unset(self, monkeypatch):
        _configure(monkeypatch, key="")
        headers = _litellm()._headers()
        assert "Authorization" not in headers
        assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# generate_image — the OpenAI images/generations happy paths + refusals.
# ---------------------------------------------------------------------------

class TestGenerateImage:
    def test_b64_json_variant_decodes_inline_bytes(self, monkeypatch):
        _configure(monkeypatch, base="https://gw.example/v1",
                   key="sk-abc", model="image-flux")
        raw = b"\x89PNG-inline-bytes"
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            return _FakeResponse(json_data={
                "data": [{"b64_json": base64.b64encode(raw).decode()}]
            })

        def fake_get(url, timeout=None, **kwargs):  # pragma: no cover
            raise AssertionError("b64 path must not fetch a URL")

        from autonomous.ai.models import litellm as litellm_mod
        monkeypatch.setattr(litellm_mod._HTTP, "post", fake_post)
        monkeypatch.setattr(litellm_mod._HTTP, "get", fake_get)

        result = _litellm().generate_image("a dragon", aspect_ratio="2K")

        assert result == raw
        assert captured["url"] == "https://gw.example/v1/images/generations"
        assert captured["headers"]["Authorization"] == "Bearer sk-abc"
        # Issue-authoritative body shape: {model, prompt, n, size}.
        assert captured["json"] == {
            "model": "image-flux",
            "prompt": "a dragon",
            "n": 1,
            "size": "1792x1024",   # 2K → 16:9 → landscape
        }
        assert captured["timeout"] == LiteLLMImageModel._media_timeout

    def test_url_variant_fetches_and_returns_content(self, monkeypatch):
        _configure(monkeypatch, base="https://gw.example/v1", key="sk-abc")
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            return _FakeResponse(json_data={
                "data": [{"url": "https://cdn.example/generated.png"}]
            })

        def fake_get(url, timeout=None, **kwargs):
            captured["fetch_url"] = url
            captured["max_attempts"] = kwargs.get("max_attempts")
            return _FakeResponse(content=b"fetched-image-bytes")

        from autonomous.ai.models import litellm as litellm_mod
        monkeypatch.setattr(litellm_mod._HTTP, "post", fake_post)
        monkeypatch.setattr(litellm_mod._HTTP, "get", fake_get)

        result = _litellm().generate_image("a castle")

        assert result == b"fetched-image-bytes"
        assert captured["fetch_url"] == "https://cdn.example/generated.png"
        # A signed/short-lived image URL that 4xxes is permanently invalid,
        # so the fetch leg must disable retry (max_attempts=1) — retrying it
        # is pure latency waste (issue #77 rationale carried from flux).
        assert captured["max_attempts"] == 1

    def test_b64_is_preferred_over_url_when_both_present(self, monkeypatch):
        # _extract_image checks b64_json first; a response carrying both must
        # decode inline and never fetch.
        _configure(monkeypatch, base="https://gw.example/v1")
        raw = b"inline-wins"

        def fake_post(url, headers=None, json=None, timeout=None):
            return _FakeResponse(json_data={"data": [{
                "b64_json": base64.b64encode(raw).decode(),
                "url": "https://cdn.example/should-not-fetch.png",
            }]})

        def fake_get(url, timeout=None, **kwargs):  # pragma: no cover
            raise AssertionError("must not fetch when b64_json is present")

        from autonomous.ai.models import litellm as litellm_mod
        monkeypatch.setattr(litellm_mod._HTTP, "post", fake_post)
        monkeypatch.setattr(litellm_mod._HTTP, "get", fake_get)

        assert _litellm().generate_image("x") == raw

    def test_negative_prompt_and_style_are_not_wired_into_body(self, monkeypatch):
        # The OpenAI images/generations body has no field for them; they are
        # accepted for signature parity but must not leak into the request.
        _configure(monkeypatch, base="https://gw.example/v1")
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["json"] = json
            return _FakeResponse(json_data={"data": [{"b64_json": base64.b64encode(b"z").decode()}]})

        from autonomous.ai.models import litellm as litellm_mod
        monkeypatch.setattr(litellm_mod._HTTP, "post", fake_post)

        _litellm().generate_image(
            "prompt", negative_prompt="blurry, deformed", style="watercolor",
        )
        assert set(captured["json"]) == {"model", "prompt", "n", "size"}
        assert "blurry" not in repr(captured["json"])
        assert "watercolor" not in repr(captured["json"])

    def test_files_non_empty_raises_not_implemented(self, monkeypatch):
        # Reference-image path is deferred so ImageAgent's
        # fallback_provider="gemini" carries it. NotImplementedError is the
        # signal ImageAgent.generate catches to trigger fallback.
        _configure(monkeypatch, base="https://gw.example/v1")
        with pytest.raises(NotImplementedError, match="reference-image|files"):
            _litellm().generate_image("prompt", files={"ref.png": b"\x00"})

    def test_api_key_is_never_logged_on_failure(self, monkeypatch):
        # Security pin: the Bearer key must not reach the log sink. The error
        # path logs the exception; HttpClient's message is "{method} {url}
        # failed..." (url carries no key), but pin it so a future refactor
        # that logs headers/body is caught here.
        _configure(monkeypatch, base="https://gw.example/v1", key="sk-super-secret")
        logged = []

        def fake_post(url, headers=None, json=None, timeout=None):
            raise requests.ConnectionError("gateway down")

        from autonomous.ai.models import litellm as litellm_mod
        monkeypatch.setattr(litellm_mod._HTTP, "post", fake_post)
        monkeypatch.setattr(litellm_mod, "log", lambda *a, **k: logged.append(" ".join(str(x) for x in a)))

        with pytest.raises(requests.ConnectionError):
            _litellm().generate_image("prompt")
        assert logged, "the failure path must emit a diagnostic log line"
        assert not any("sk-super-secret" in line for line in logged)


# ---------------------------------------------------------------------------
# Malformed-2xx translation — a success status with an unextractable body
# becomes a typed MalformedResponseError via the shared extract_or_malformed
# helper (symmetric with flux), NOT a leaked stdlib exception.
# ---------------------------------------------------------------------------

class TestMalformedResponse:
    def _post_returning(self, monkeypatch, body):
        _configure(monkeypatch, base="https://gw.example/v1")

        def fake_post(url, headers=None, json=None, timeout=None):
            return _FakeResponse(json_data=body)

        from autonomous.ai.models import litellm as litellm_mod
        monkeypatch.setattr(litellm_mod._HTTP, "post", fake_post)

    def test_empty_data_array_raises_malformed(self, monkeypatch):
        self._post_returning(monkeypatch, {"data": []})
        with pytest.raises(MalformedResponseError, match="no image data"):
            _litellm().generate_image("prompt")

    def test_missing_data_key_raises_malformed(self, monkeypatch):
        self._post_returning(monkeypatch, {"created": 123})
        with pytest.raises(MalformedResponseError, match="no image data"):
            _litellm().generate_image("prompt")

    def test_item_without_b64_or_url_raises_malformed(self, monkeypatch):
        self._post_returning(monkeypatch, {"data": [{"revised_prompt": "x"}]})
        with pytest.raises(MalformedResponseError, match="missing b64_json and url"):
            _litellm().generate_image("prompt")

    def test_undecodable_b64_raises_malformed(self, monkeypatch):
        # base64.b64decode on garbage raises binascii.Error (a ValueError
        # subclass) INSIDE the extractor, so it must translate too — not leak.
        self._post_returning(monkeypatch, {"data": [{"b64_json": "!!!not-base64!!!"}]})
        with pytest.raises(MalformedResponseError):
            _litellm().generate_image("prompt")

    def test_malformed_carries_endpoint_label(self, monkeypatch):
        # The typed error preserves the endpoint label for structured triage.
        self._post_returning(monkeypatch, {"data": []})
        with pytest.raises(MalformedResponseError) as exc_info:
            _litellm().generate_image("prompt")
        assert exc_info.value.endpoint == "/litellm/images/generations"


# ---------------------------------------------------------------------------
# upscale_image — honest no-op passthrough (same as flux/gemini). ImageAgent's
# upscale path relies on `result is image_content` to flag upscale_supported.
# ---------------------------------------------------------------------------

class TestUpscaleImage:
    def test_returns_input_bytes_unchanged_by_identity(self):
        original = b"original-image-bytes"
        out = _litellm().upscale_image("prompt", image_content=original)
        assert out is original

    def test_returns_none_when_no_input(self):
        assert _litellm().upscale_image("prompt") is None


# ---------------------------------------------------------------------------
# Non-image protocol methods — image-only adapter declares them but refuses
# with the typed NotSupportedByProvider (a NotImplementedError subclass).
# ---------------------------------------------------------------------------

class TestProtocolConformance:
    # generate_json is supported since #264 (delegates to the gateway).

    def test_generate_transcription_not_supported(self):
        with pytest.raises(NotSupportedByProvider) as exc_info:
            _litellm().generate_transcription(b"audio")
        assert exc_info.value.method == "generate_transcription"


# ---------------------------------------------------------------------------
# Config group env wiring — the three LITELLM_* fields flow through Settings
# with the documented default (image-flux) and secret redaction on the key.
# ---------------------------------------------------------------------------

class TestConfigEnvWiring:
    _KEYS = ("LITELLM_IMAGE_API_BASE_URL", "LITELLM_API_KEY", "LITELLM_IMAGE_MODEL")

    def test_defaults_when_unset(self, monkeypatch):
        for k in self._KEYS:
            monkeypatch.delenv(k, raising=False)
        s = Settings()
        assert s.litellm_image_api_base_url == ""
        assert s.litellm_api_key == ""
        assert s.litellm_image_model == "image-flux"

    def test_env_values_are_snapshotted(self, monkeypatch):
        monkeypatch.setenv("LITELLM_IMAGE_API_BASE_URL", "https://gw.example/v1")
        monkeypatch.setenv("LITELLM_API_KEY", "sk-live")
        monkeypatch.setenv("LITELLM_IMAGE_MODEL", "image-gemini-3.1")
        s = Settings()
        assert s.litellm_image_api_base_url == "https://gw.example/v1"
        assert s.litellm_api_key == "sk-live"
        assert s.litellm_image_model == "image-gemini-3.1"

    def test_api_key_is_a_redacted_secret(self, monkeypatch):
        monkeypatch.setenv("LITELLM_API_KEY", "sk-secret")
        s = Settings()
        assert s.as_dict()["litellm_api_key"] == "***"
        assert s.as_dict(redact_secrets=False)["litellm_api_key"] == "sk-secret"

    def test_base_url_and_model_are_not_redacted(self, monkeypatch):
        monkeypatch.setenv("LITELLM_IMAGE_API_BASE_URL", "https://gw.example/v1")
        monkeypatch.setenv("LITELLM_IMAGE_MODEL", "image-flux")
        s = Settings()
        d = s.as_dict()
        assert d["litellm_image_api_base_url"] == "https://gw.example/v1"
        assert d["litellm_image_model"] == "image-flux"
