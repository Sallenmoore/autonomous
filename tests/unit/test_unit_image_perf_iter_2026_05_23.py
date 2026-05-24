"""Independent coverage for PR #116 (image gen perf bundle).

Targets three concerns introduced by the PR, written without consulting
dev's ephemeral tests:

1. ``autonomous.ai.image_cache`` — content-addressed cache module
   (hermetic; pure functions + filesystem only).
2. ``ImageAgent._resolve_aspect_ratio`` + ``_QUALITY_ASPECT_MAP`` —
   quality dial that remaps the caller's aspect_ratio.
3. ``_hybrid_upscale_enabled`` — env-var-gated routing into the local
   upscaler when paired with Gemini base generation.

Out of scope: the full ``ImageAgent.generate`` integration with the
provider clients (integration suite covers that). These unit tests
pin the surface area that's the most failure-prone if the helpers
get refactored without the integration suite running.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from autonomous.ai import image_cache
from autonomous.ai.imageagent import (
    ImageAgent,
    _QUALITY_ASPECT_MAP,
    _hybrid_upscale_enabled,
)


# ---------------------------------------------------------------------------
# image_cache.cache_key — determinism + keyword-only contract
# ---------------------------------------------------------------------------


class TestCacheKey:
    def test_same_inputs_yield_same_key(self):
        k1 = image_cache.cache_key(prompt="a fox", provider="local")
        k2 = image_cache.cache_key(prompt="a fox", provider="local")
        assert k1 == k2

    def test_different_prompts_yield_different_keys(self):
        k1 = image_cache.cache_key(prompt="a fox", provider="local")
        k2 = image_cache.cache_key(prompt="a cat", provider="local")
        assert k1 != k2

    def test_different_providers_yield_different_keys(self):
        k1 = image_cache.cache_key(prompt="x", provider="local")
        k2 = image_cache.cache_key(prompt="x", provider="gemini")
        assert k1 != k2

    def test_method_separates_generate_from_upscale(self):
        """Same prompt + provider but different method must not collide —
        otherwise a cached upscale result would serve a generate request."""
        gen = image_cache.cache_key(prompt="x", provider="local", method="generate")
        ups = image_cache.cache_key(prompt="x", provider="local", method="upscale")
        assert gen != ups

    def test_keyword_only_signature(self):
        """Positional args must fail — protects against silent meaning
        shifts when new fields are added to cache_key."""
        with pytest.raises(TypeError):
            image_cache.cache_key("the prompt")  # type: ignore[misc]

    def test_style_dict_serialization_is_order_independent(self):
        """JSON dump uses sort_keys=True, so dict insertion order
        shouldn't change the cache key."""
        k1 = image_cache.cache_key(prompt="x", style={"a": 1, "b": 2})
        k2 = image_cache.cache_key(prompt="x", style={"b": 2, "a": 1})
        assert k1 == k2


# ---------------------------------------------------------------------------
# image_cache._files_digest — handles None, bytes, dict, file-like
# ---------------------------------------------------------------------------


class TestFilesDigest:
    def test_none_and_empty_dict_produce_empty_digest(self):
        assert image_cache._files_digest(None) == ""
        assert image_cache._files_digest({}) == ""

    def test_bytes_input_is_hashed(self):
        d1 = image_cache._files_digest(b"hello")
        d2 = image_cache._files_digest(b"hello")
        d3 = image_cache._files_digest(b"world")
        assert d1 == d2
        assert d1 != d3
        assert d1.startswith("_bytes:")

    def test_dict_input_is_sorted_by_key(self):
        """Same files in different dict-insert order should hash equally."""
        d1 = image_cache._files_digest({"a": b"1", "b": b"2"})
        d2 = image_cache._files_digest({"b": b"2", "a": b"1"})
        assert d1 == d2

    def test_file_like_cursor_is_restored(self):
        """The cursor of a seekable file-like must be where the caller
        left it after _files_digest reads it."""
        buf = io.BytesIO(b"contents")
        buf.seek(3)
        before = buf.tell()
        image_cache._files_digest({"upload": buf})
        assert buf.tell() == before


# ---------------------------------------------------------------------------
# _cache_root + get/put — opt-in semantics
# ---------------------------------------------------------------------------


class TestCacheRoot:
    def test_unset_env_means_disabled(self, monkeypatch):
        monkeypatch.delenv("AUTONOMOUS_IMAGE_CACHE_DIR", raising=False)
        assert image_cache._cache_root() is None

    def test_empty_string_env_means_disabled(self, monkeypatch):
        monkeypatch.setenv("AUTONOMOUS_IMAGE_CACHE_DIR", "")
        assert image_cache._cache_root() is None

    def test_whitespace_only_env_means_disabled(self, monkeypatch):
        monkeypatch.setenv("AUTONOMOUS_IMAGE_CACHE_DIR", "   ")
        assert image_cache._cache_root() is None

    def test_nonexistent_dir_means_disabled(self, monkeypatch, tmp_path):
        ghost = tmp_path / "does-not-exist"
        monkeypatch.setenv("AUTONOMOUS_IMAGE_CACHE_DIR", str(ghost))
        # The module deliberately does NOT auto-create — misconfig stays
        # safe rather than dumping bytes into an unexpected location.
        assert image_cache._cache_root() is None

    def test_existing_dir_is_returned_as_path(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AUTONOMOUS_IMAGE_CACHE_DIR", str(tmp_path))
        assert image_cache._cache_root() == tmp_path


class TestCacheGetPut:
    def test_get_miss_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AUTONOMOUS_IMAGE_CACHE_DIR", str(tmp_path))
        assert image_cache.get("nonexistent_key") is None

    def test_get_when_disabled_returns_none(self, monkeypatch):
        monkeypatch.delenv("AUTONOMOUS_IMAGE_CACHE_DIR", raising=False)
        assert image_cache.get("anykey") is None

    def test_put_then_get_roundtrip(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AUTONOMOUS_IMAGE_CACHE_DIR", str(tmp_path))
        image_cache.put("abc", b"payload")
        assert image_cache.get("abc") == b"payload"

    def test_put_is_atomic_via_tmp_rename(self, monkeypatch, tmp_path):
        """No stray .tmp file should be left behind after a successful put."""
        monkeypatch.setenv("AUTONOMOUS_IMAGE_CACHE_DIR", str(tmp_path))
        image_cache.put("abc", b"payload")
        assert not (tmp_path / "abc.webp.tmp").exists()
        assert (tmp_path / "abc.webp").exists()

    def test_put_is_silent_when_disabled(self, monkeypatch, tmp_path):
        """No exception, no file — just a no-op."""
        monkeypatch.delenv("AUTONOMOUS_IMAGE_CACHE_DIR", raising=False)
        image_cache.put("abc", b"payload")
        # Cache disabled, so the tmp_path should be untouched.
        assert list(tmp_path.iterdir()) == []

    def test_put_empty_data_is_no_op(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AUTONOMOUS_IMAGE_CACHE_DIR", str(tmp_path))
        image_cache.put("abc", b"")
        assert not (tmp_path / "abc.webp").exists()

    def test_put_empty_key_is_no_op(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AUTONOMOUS_IMAGE_CACHE_DIR", str(tmp_path))
        image_cache.put("", b"payload")
        assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Quality dial — _resolve_aspect_ratio + _QUALITY_ASPECT_MAP
# ---------------------------------------------------------------------------


class TestQualityDial:
    """Test the quality-dial as a bound method without instantiating
    ImageAgent (which would pull AutoModel init through BaseAgent).
    We rely on the fact that ``_resolve_aspect_ratio`` only touches
    its own arguments — no self-state — so an unbound call works."""

    def test_standard_passes_through_unchanged(self):
        # "standard" maps to an empty override dict, so the caller's
        # aspect_ratio survives. This is the load-bearing default
        # behaviour for every existing caller.
        out = ImageAgent._resolve_aspect_ratio(None, "2KPortrait", "standard")
        assert out == "2KPortrait"

    def test_unknown_quality_is_typo_safe(self):
        """A typo like quality='haigh' must NOT silently downgrade
        a high-quality request — the PR explicitly calls this out."""
        out = ImageAgent._resolve_aspect_ratio(None, "2K", "haigh")
        assert out == "2K"

    def test_draft_collapses_2k_portrait_to_9_16(self):
        out = ImageAgent._resolve_aspect_ratio(None, "2KPortrait", "draft")
        assert out == "9:16"

    def test_draft_collapses_2k_landscape_to_16_9(self):
        out = ImageAgent._resolve_aspect_ratio(None, "2K", "draft")
        assert out == "16:9"

    def test_high_upgrades_2k_to_4k(self):
        out = ImageAgent._resolve_aspect_ratio(None, "2K", "high")
        assert out == "4K"

    def test_high_upgrades_2k_portrait_to_4k_portrait(self):
        out = ImageAgent._resolve_aspect_ratio(None, "2KPortrait", "high")
        assert out == "4KPortrait"

    def test_unknown_ratio_within_known_quality_passes_through(self):
        """If the ratio isn't in the override table for a known quality
        (e.g. someone passes a custom ratio with quality='high'), the
        ratio passes through unchanged rather than crashing."""
        out = ImageAgent._resolve_aspect_ratio(None, "1024x1024", "high")
        assert out == "1024x1024"


class TestQualityAspectMapShape:
    def test_three_quality_tiers_defined(self):
        assert set(_QUALITY_ASPECT_MAP) == {"draft", "standard", "high"}

    def test_standard_is_pass_through(self):
        """standard must be an empty dict — anything else would change
        behaviour for every existing caller without warning."""
        assert _QUALITY_ASPECT_MAP["standard"] == {}


# ---------------------------------------------------------------------------
# Hybrid upscale env-var routing
# ---------------------------------------------------------------------------


class TestHybridUpscaleEnv:
    @pytest.mark.parametrize("val", ["1", "true", "TRUE", "yes", "Yes", "YES"])
    def test_truthy_values_enable(self, monkeypatch, val):
        monkeypatch.setenv("IMAGE_HYBRID_UPSCALE", val)
        assert _hybrid_upscale_enabled() is True

    @pytest.mark.parametrize("val", ["", "0", "false", "no", "off", "anything-else"])
    def test_other_values_disable(self, monkeypatch, val):
        monkeypatch.setenv("IMAGE_HYBRID_UPSCALE", val)
        assert _hybrid_upscale_enabled() is False

    def test_unset_means_disabled(self, monkeypatch):
        monkeypatch.delenv("IMAGE_HYBRID_UPSCALE", raising=False)
        assert _hybrid_upscale_enabled() is False
