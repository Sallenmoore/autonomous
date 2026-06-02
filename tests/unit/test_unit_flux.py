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

    def __init__(self, *, status=200, json_data=None, content=b""):
        self.status_code = status
        self._json = json_data or {}
        self.content = content

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

        def fake_get(url, timeout=None):
            captured["fetch_url"] = url
            return _FakeResponse(content=b"\x89PNG-bytes")

        from autonomous.ai.models import flux as flux_mod
        monkeypatch.setattr(flux_mod._SESSION, "post", fake_post)
        monkeypatch.setattr(flux_mod._SESSION, "get", fake_get)

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
        monkeypatch.setenv("FAL_KEY", "fal-test-key")
        calls = {"post": 0}

        def flaky_post(url, headers=None, json=None, timeout=None):
            calls["post"] += 1
            if calls["post"] < 3:
                raise requests.ConnectionError("simulated 5xx")
            return _FakeResponse(
                json_data={"images": [{"url": "https://cdn/x.webp"}]}
            )

        def fake_get(url, timeout=None):
            return _FakeResponse(content=b"OK")

        from autonomous.ai.models import flux as flux_mod
        monkeypatch.setattr(flux_mod._SESSION, "post", flaky_post)
        monkeypatch.setattr(flux_mod._SESSION, "get", fake_get)
        # Speed up retries — sleep_seconds is env-overridable.
        monkeypatch.setattr(flux_mod.FluxAIModel, "_retry_sleep", 0.0)

        result = flux_mod.FluxAIModel.generate_image(_flux(), "prompt")
        assert result == b"OK"
        assert calls["post"] == 3   # 2 failures + 1 success

    def test_5xx_after_max_attempts_raises(self, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "fal-test-key")
        calls = {"post": 0}

        def always_fail(url, headers=None, json=None, timeout=None):
            calls["post"] += 1
            raise requests.ConnectionError("permanent")

        from autonomous.ai.models import flux as flux_mod
        monkeypatch.setattr(flux_mod._SESSION, "post", always_fail)
        monkeypatch.setattr(flux_mod.FluxAIModel, "_retry_sleep", 0.0)

        with pytest.raises(requests.ConnectionError, match="permanent"):
            flux_mod.FluxAIModel.generate_image(_flux(), "prompt")
        assert calls["post"] == 3   # _max_attempts default

    def test_empty_images_array_raises_value_error(self, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "fal-test-key")

        def fake_post(url, headers=None, json=None, timeout=None):
            return _FakeResponse(json_data={"images": []})

        from autonomous.ai.models import flux as flux_mod
        monkeypatch.setattr(flux_mod._SESSION, "post", fake_post)

        with pytest.raises(ValueError, match="no images"):
            flux_mod.FluxAIModel.generate_image(_flux(), "prompt")

    def test_image_missing_url_raises_value_error(self, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "fal-test-key")

        def fake_post(url, headers=None, json=None, timeout=None):
            return _FakeResponse(json_data={"images": [{"width": 1024}]})

        from autonomous.ai.models import flux as flux_mod
        monkeypatch.setattr(flux_mod._SESSION, "post", fake_post)

        with pytest.raises(ValueError, match="image URL"):
            flux_mod.FluxAIModel.generate_image(_flux(), "prompt")


class TestUpscaleImage:
    def test_upscale_returns_input_unchanged(self):
        from autonomous.ai.models.flux import FluxAIModel
        original = b"original-image-bytes"
        out = FluxAIModel.upscale_image(_flux(), "prompt", image_content=original)
        assert out is original
