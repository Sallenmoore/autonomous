"""FluxAIModel adapter tests. Hermetic — every test that would call
fal.ai mocks requests.post.

Test classes:
- TestImport: module imports without FAL_KEY; first dispatch raises.
- TestGetImageConfig: aspect-ratio mapping table is correct.
- TestGenerateImage: happy path, retry, empty body, files=, missing key.
- TestUpscaleImage: honest no-op."""

import os

import pytest
import requests


def _flux():
    """Bare FluxAIModel without DB."""
    from autonomous.ai.models.flux import FluxAIModel
    return FluxAIModel.__new__(FluxAIModel)


class TestImport:
    def test_module_imports_without_fal_key(self, monkeypatch):
        monkeypatch.delenv("FAL_KEY", raising=False)
        # Re-import is OK; the absence of FAL_KEY at import time must not
        # raise. Bug shape we're guarding: an import-time
        # `os.environ["FAL_KEY"]` would brick image gen entirely when the
        # key is unset, including for callers that never touch FLUX.
        from autonomous.ai.models import flux  # noqa: F401


class TestGetImageConfig:
    @pytest.mark.parametrize("input_key,expected", [
        ("Portrait",   ("3:4",  "square_hd")),
        ("Landscape",  ("16:9", "square_hd")),
        ("2K",         ("16:9", "landscape_4_3")),
        ("2KPortrait", ("3:4",  "portrait_4_3")),
        ("4K",         ("16:9", "landscape_16_9")),
        ("4KPortrait", ("3:4",  "portrait_16_9")),
        ("Map",        ("16:9", "landscape_16_9")),
        ("1:1",        ("1:1",  "square_hd")),
        ("3:4",        ("3:4",  "square_hd")),
        ("16:9",       ("16:9", "square_hd")),
        ("Unknown",    ("3:4",  "square_hd")),  # default fallback
    ])
    def test_aspect_ratio_mapping(self, input_key, expected):
        from autonomous.ai.models.flux import FluxAIModel
        assert FluxAIModel._get_image_config(_flux(), input_key) == expected


class _FakeResponse:
    """Stand-in for requests.Response. Only the surface FluxAIModel uses."""

    def __init__(self, *, status=200, json_data=None, content=b"", text=""):
        self.status_code = status
        self._json = json_data or {}
        self.content = content
        # ``text`` is read by ``MalformedResponseError.from_response`` for
        # the body excerpt (#142 adoption of ``extract_or_malformed``).
        self.text = text or repr(json_data or {})
        self.headers = {"Content-Type": "application/json"}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class TestGenerateImage:
    def test_happy_path_posts_and_fetches_image(self, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "fal-test-key")

        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _FakeResponse(
                json_data={"images": [{"url": "https://cdn/x.webp"}]}
            )

        def fake_get(url, timeout=None, **kwargs):
            # **kwargs accepts ``max_attempts=`` added by issue #77
            # (flux passes max_attempts=1 on the CDN GET to short-circuit
            # retry on signed-URL 4xx). Source change + stub signature
            # widening are inseparable — same authorization pattern as
            # the #50 HttpClient migration slices.
            captured["fetch_url"] = url
            return _FakeResponse(content=b"\x89PNG-bytes")

        from autonomous.ai.models import flux as flux_mod
        # Post-#50-slice-E: patch _HTTP.post and _HTTP.get directly. The
        # test doesn't exercise the retry path, so bypassing HttpClient's
        # internal wrapping is fine. The MagicMock fixture's
        # raise_for_status is a no-op (slice C lesson — defense in depth
        # for test mocks that don't trigger raise_for_status).
        monkeypatch.setattr(flux_mod._HTTP, "post", fake_post)
        monkeypatch.setattr(flux_mod._HTTP, "get", fake_get)

        result = flux_mod.FluxAIModel.generate_image(
            _flux(),
            "a dragon over a mountain",
            negative_prompt="blurry",
            aspect_ratio="Portrait",
        )

        assert result == b"\x89PNG-bytes"
        assert captured["url"].endswith("/fal-ai/flux-pro/v1.1-ultra")
        assert captured["headers"]["Authorization"] == "Key fal-test-key"
        assert captured["json"]["prompt"].startswith("a dragon over a mountain")
        assert captured["json"]["aspect_ratio"] == "3:4"
        assert captured["json"]["image_size"] == "square_hd"
        assert captured["json"]["negative_prompt"] == "blurry"
        assert captured["fetch_url"] == "https://cdn/x.webp"

    def test_files_kwarg_raises_not_implemented(self, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "fal-test-key")
        from autonomous.ai.models.flux import FluxAIModel
        with pytest.raises(NotImplementedError, match="img2img"):
            FluxAIModel.generate_image(
                _flux(), "prompt", files={"ref.webp": b"\x00"}
            )

    def test_missing_fal_key_raises_runtime_error(self, monkeypatch):
        monkeypatch.delenv("FAL_KEY", raising=False)
        from autonomous.ai.models.flux import FluxAIModel
        with pytest.raises(RuntimeError, match="FAL_KEY"):
            FluxAIModel.generate_image(_flux(), "prompt")

    def test_blank_fal_key_raises_runtime_error(self, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "   ")
        from autonomous.ai.models.flux import FluxAIModel
        with pytest.raises(RuntimeError, match="FAL_KEY"):
            FluxAIModel.generate_image(_flux(), "prompt")

    def test_5xx_retries_then_eventually_succeeds(self, monkeypatch):
        # Post-#50-slice-E patches ``_HTTP.session.request`` (the layer
        # HttpClient.request actually invokes) so HttpClient's internal
        # retry wrapper fires. Patching ``_HTTP.post`` directly would
        # bypass the retry budget — the mock would raise once and the
        # test would see calls["post"] == 1 instead of 3.
        monkeypatch.setenv("FAL_KEY", "fal-test-key")
        calls = {"post": 0}

        def flaky_request(method, url, *args, **kwargs):
            if method == "POST":
                calls["post"] += 1
                if calls["post"] < 3:
                    raise requests.ConnectionError("simulated 5xx")
                return _FakeResponse(
                    json_data={"images": [{"url": "https://cdn/x.webp"}]}
                )
            if method == "GET":
                return _FakeResponse(content=b"OK")
            raise AssertionError(f"unexpected method: {method}")

        from autonomous.ai.models import flux as flux_mod
        monkeypatch.setattr(flux_mod._HTTP.session, "request", flaky_request)
        # Speed up retries — replaces the pre-migration
        # ``monkeypatch.setattr(FluxAIModel, "_retry_sleep", 0.0)``.
        # The retry config now lives on the HttpClient instance.
        monkeypatch.setattr(flux_mod._HTTP, "retry_backoff", 0.0)

        result = flux_mod.FluxAIModel.generate_image(_flux(), "prompt")
        assert result == b"OK"
        assert calls["post"] == 3   # 2 failures + 1 success

    def test_5xx_after_max_attempts_raises(self, monkeypatch):
        # Post-#50-slice-E behavior change: HttpClient wraps the caught
        # requests.ConnectionError into the configured
        # ``transport_error_cls=requests.RequestException`` on retry
        # exhaustion. The original ConnectionError's message is
        # preserved in the wrapper. Update the pytest.raises to match
        # the wrapper class; pre-migration this raised ConnectionError
        # directly via the retry() helper.
        monkeypatch.setenv("FAL_KEY", "fal-test-key")
        calls = {"post": 0}

        def always_fail(method, url, *args, **kwargs):
            if method == "POST":
                calls["post"] += 1
            raise requests.ConnectionError("permanent")

        from autonomous.ai.models import flux as flux_mod
        monkeypatch.setattr(flux_mod._HTTP.session, "request", always_fail)
        monkeypatch.setattr(flux_mod._HTTP, "retry_backoff", 0.0)

        with pytest.raises(requests.RequestException, match="permanent"):
            flux_mod.FluxAIModel.generate_image(_flux(), "prompt")
        assert calls["post"] == 3   # HttpClient.max_attempts default

    def test_empty_images_array_raises_malformed(self, monkeypatch):
        # No retry path exercised here — patch _HTTP.post directly.
        # Issue #142: malformed-2xx (empty ``images`` array) now
        # translates to ``MalformedResponseError`` via the shared
        # ``extract_or_malformed`` helper, symmetric with openai_compat.
        # The original ``ValueError`` is preserved on ``__cause__``.
        from autonomous.ai.exceptions import MalformedResponseError
        monkeypatch.setenv("FAL_KEY", "fal-test-key")

        def fake_post(url, headers=None, json=None, timeout=None):
            return _FakeResponse(json_data={"images": []})

        from autonomous.ai.models import flux as flux_mod
        monkeypatch.setattr(flux_mod._HTTP, "post", fake_post)

        with pytest.raises(MalformedResponseError, match="no images"):
            flux_mod.FluxAIModel.generate_image(_flux(), "prompt")

    def test_image_missing_url_raises_malformed(self, monkeypatch):
        # Issue #142: same translation as the empty-array case. The
        # inner ``ValueError("fal.ai response missing image URL: ...")``
        # raised by the extractor is caught by ``MALFORMED_2XX_EXCEPTIONS``
        # and re-raised as the typed error.
        from autonomous.ai.exceptions import MalformedResponseError
        monkeypatch.setenv("FAL_KEY", "fal-test-key")

        def fake_post(url, headers=None, json=None, timeout=None):
            return _FakeResponse(json_data={"images": [{"width": 1024}]})

        from autonomous.ai.models import flux as flux_mod
        monkeypatch.setattr(flux_mod._HTTP, "post", fake_post)

        with pytest.raises(MalformedResponseError, match="image URL"):
            flux_mod.FluxAIModel.generate_image(_flux(), "prompt")


    def test_nsfw_flagged_response_raises_and_skips_cdn_fetch(self, monkeypatch):
        # Issue #226: fal.ai runs its safety checker even though the
        # request body sets ``enable_safety_checker: False``, and answers
        # HTTP 200 carrying a solid-black frame with
        # ``has_nsfw_concepts: [true]``. Returning those bytes as a
        # success stored a black square as the entity image and stopped
        # ImageAgent's ``fallback_provider`` from ever firing. Raising
        # the deterministic empty-image error is what re-routes to Gemini.
        from autonomous.ai.exceptions import GenerateImageEmptyResponseError
        monkeypatch.setenv("FAL_KEY", "fal-test-key")
        calls = {"get": 0}

        def fake_post(url, headers=None, json=None, timeout=None):
            return _FakeResponse(
                json_data={
                    "images": [{"url": "https://cdn/black.png"}],
                    "has_nsfw_concepts": [True],
                }
            )

        def fake_get(url, timeout=None, **kwargs):
            calls["get"] += 1
            return _FakeResponse(content=b"\x00" * 16)

        from autonomous.ai.models import flux as flux_mod
        monkeypatch.setattr(flux_mod._HTTP, "post", fake_post)
        monkeypatch.setattr(flux_mod._HTTP, "get", fake_get)

        with pytest.raises(GenerateImageEmptyResponseError, match="safety"):
            flux_mod.FluxAIModel.generate_image(_flux(), "a mix of two actors")

        # The flagged frame must never be downloaded — paying for the CDN
        # round trip to fetch a black square is pure waste.
        assert calls["get"] == 0

    def test_nsfw_flag_all_false_is_a_normal_success(self, monkeypatch):
        # The common shape: fal.ai returns ``has_nsfw_concepts: [false]``
        # on every clean generation. The guard must not treat that as a
        # block, or FLUX would fall back to Gemini on every single call.
        monkeypatch.setenv("FAL_KEY", "fal-test-key")

        def fake_post(url, headers=None, json=None, timeout=None):
            return _FakeResponse(
                json_data={
                    "images": [{"url": "https://cdn/ok.webp"}],
                    "has_nsfw_concepts": [False],
                }
            )

        def fake_get(url, timeout=None, **kwargs):
            return _FakeResponse(content=b"\x89PNG-clean")

        from autonomous.ai.models import flux as flux_mod
        monkeypatch.setattr(flux_mod._HTTP, "post", fake_post)
        monkeypatch.setattr(flux_mod._HTTP, "get", fake_get)

        assert flux_mod.FluxAIModel.generate_image(
            _flux(), "a dragon"
        ) == b"\x89PNG-clean"

    def test_nsfw_content_detected_alias_also_raises(self, monkeypatch):
        # fal.ai is not consistent across model families: some endpoints
        # report the block as ``nsfw_content_detected`` instead of
        # ``has_nsfw_concepts`` (#226 names both). Honour either spelling
        # so a model swap can't silently reopen the black-frame hole.
        from autonomous.ai.exceptions import GenerateImageEmptyResponseError
        monkeypatch.setenv("FAL_KEY", "fal-test-key")

        def fake_post(url, headers=None, json=None, timeout=None):
            return _FakeResponse(
                json_data={
                    "images": [{"url": "https://cdn/black.png"}],
                    "nsfw_content_detected": [True],
                }
            )

        def fake_get(url, timeout=None, **kwargs):  # pragma: no cover
            raise AssertionError(f"flagged frame must not be fetched: {url}")

        from autonomous.ai.models import flux as flux_mod
        monkeypatch.setattr(flux_mod._HTTP, "post", fake_post)
        monkeypatch.setattr(flux_mod._HTTP, "get", fake_get)

        with pytest.raises(GenerateImageEmptyResponseError, match="safety"):
            flux_mod.FluxAIModel.generate_image(_flux(), "prompt")


class TestUpscaleImage:
    def test_upscale_returns_input_unchanged(self):
        from autonomous.ai.models.flux import FluxAIModel
        original = b"original-image-bytes"
        out = FluxAIModel.upscale_image(_flux(), "prompt", image_content=original)
        assert out is original
