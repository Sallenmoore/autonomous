"""Independent coverage for the image gen perf bundle.

Targets five concerns from the perf bundle, written without consulting
dev's ephemeral tests:

1. ``autonomous.ai.image_cache`` — content-addressed cache module
   (hermetic; pure functions + filesystem only).
2. ``ImageAgent._resolve_aspect_ratio`` + ``_QUALITY_ASPECT_MAP`` —
   quality dial that remaps the caller's aspect_ratio.
3. ``_hybrid_upscale_enabled`` — env-var-gated routing into the local
   upscaler when paired with Gemini base generation.
4. ``ImageAgent.upscale`` no-op detection — both Gemini's "no upscaler"
   no-op and the local "size already matches target" branch return
   ``image_content`` unchanged; the agent surfaces this as
   ``upscale_supported=False`` job-meta so the caller can detect
   silent-downgrade.
5. ``ImageAgent.generate`` hybrid dispatch gate — four-way conjunction
   (result truthy AND provider==gemini AND env enabled AND ratio in
   the upscale set); each helper is covered above, this pins the
   conjunction.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from autonomous.ai import image_cache
from autonomous.ai.imageagent import (
    ImageAgent,
    _QUALITY_ASPECT_MAP,
    _hybrid_upscale_enabled,
)


class _FakeImageAgent:
    """Composition-not-inheritance fake that borrows ImageAgent's
    bound methods without dragging in AutoModel/Document machinery.

    Trying to bypass ``AutoModel.__init__`` via ``__new__`` runs into
    the vendored mongoengine fork's StringAttr descriptor protocol
    (it needs ``_initialised`` + ``_data`` + a long tail of state).
    The methods we're testing — ``generate`` and ``upscale`` — only
    touch ``self.{provider, name, instructions, description}``,
    ``self.get_client()``, ``self.add_to_job_meta()``, and
    ``self.MODEL_REGISTRY``. We mimic those exactly, leaving the
    code-under-test unchanged via plain method aliasing.
    """

    MODEL_REGISTRY: dict = {}  # populated per-test via patch.dict

    # Bind the actual methods under test to this fake class so the
    # production code path runs, not a re-implementation.
    _resolve_aspect_ratio = ImageAgent._resolve_aspect_ratio
    generate = ImageAgent.generate
    upscale = ImageAgent.upscale

    def __init__(self, provider: str):
        self.provider = provider
        self.name = "test-agent"
        self.instructions = "test"
        self.description = "test"
        self.meta_calls: list[tuple] = []
        # ``_client`` placeholder so ``get_client`` can be patched per-test.
        self._client = None

    def get_client(self, provider=None, *, persist: bool = True):
        # Overridden via patch.object per test.
        raise NotImplementedError("patch get_client per-test")

    def add_to_job_meta(self, k, v):
        # Capture rather than dispatch — keeps the tests free of any
        # AutoTasks / RQ / Redis dependency.
        self.meta_calls.append((k, v))


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


# ---------------------------------------------------------------------------
# ImageAgent.upscale — no-op detection across providers
# ---------------------------------------------------------------------------


class TestUpscaleNoOpBreadcrumb:
    """When the upstream upscaler returns the input bytes unchanged
    (Gemini's "no upscaler" no-op, or local's "size already matches"
    branch), ImageAgent.upscale must surface ``upscale_supported=False``
    as job meta. Without this, callers see bytes-in-equal-bytes-out as
    success and silent-downgrade goes undetected."""

    def _run_upscale(self, monkeypatch, *, provider, returns):
        monkeypatch.delenv("AUTONOMOUS_IMAGE_CACHE_DIR", raising=False)
        agent = _FakeImageAgent(provider)
        mock_client = MagicMock()
        mock_client.upscale_image.return_value = returns
        with patch.object(agent, "get_client", return_value=mock_client):
            result = agent.upscale("a prompt", image_content=b"original_bytes")
        return result, agent.meta_calls

    def test_unchanged_bytes_sets_upscale_unsupported(self, monkeypatch):
        """Gemini upscale returns input unchanged (the same object
        reference). Detected via ``is`` — fast and provider-agnostic."""
        original = b"original_bytes"
        result, meta_calls = self._run_upscale(
            monkeypatch, provider="gemini", returns=original
        )
        assert result is original
        assert ("upscale_supported", False) in meta_calls

    def test_actual_upscale_does_not_set_unsupported(self, monkeypatch):
        """A real upscaler returns NEW bytes. No breadcrumb should fire."""
        monkeypatch.delenv("AUTONOMOUS_IMAGE_CACHE_DIR", raising=False)
        agent = _FakeImageAgent("local")
        mock_client = MagicMock()
        mock_client.upscale_image.return_value = b"new_upscaled_bytes"
        with patch.object(agent, "get_client", return_value=mock_client):
            agent.upscale("p", image_content=b"original_bytes")
        assert ("upscale_supported", False) not in agent.meta_calls

    def test_local_size_matches_target_branch(self, monkeypatch):
        """Mirror of the gemini case for the local-model fallthrough
        return — same provider-agnostic detection."""
        monkeypatch.delenv("AUTONOMOUS_IMAGE_CACHE_DIR", raising=False)
        agent = _FakeImageAgent("local")
        original = b"img"
        mock_client = MagicMock()
        mock_client.upscale_image.return_value = original  # fallthrough no-op
        with patch.object(agent, "get_client", return_value=mock_client):
            agent.upscale("p", image_content=original)
        assert ("upscale_supported", False) in agent.meta_calls


# ---------------------------------------------------------------------------
# ImageAgent.generate — hybrid dispatch gate + breadcrumbs
# ---------------------------------------------------------------------------


class TestHybridDispatch:
    """The hybrid upscale path fires iff ALL of:
       (1) base generate_image returned truthy
       (2) provider == "gemini"
       (3) IMAGE_HYBRID_UPSCALE env truthy
       (4) effective_ratio in {2K, 2KPortrait, 4K, 4KPortrait}

    Each helper is covered in isolation by other classes; this pins
    the four-way conjunction so a future refactor of the gate can't
    silently drop a condition."""

    def _run_generate(self, monkeypatch, *, provider, env_enabled, aspect_ratio,
                       local_returns=b"upscaled_bytes", local_raises=None):
        monkeypatch.delenv("AUTONOMOUS_IMAGE_CACHE_DIR", raising=False)
        if env_enabled:
            monkeypatch.setenv("IMAGE_HYBRID_UPSCALE", "1")
        else:
            monkeypatch.delenv("IMAGE_HYBRID_UPSCALE", raising=False)

        agent = _FakeImageAgent(provider)

        base_client = MagicMock()
        base_client.generate_image.return_value = b"base_bytes"

        local_client_instance = MagicMock()
        if local_raises is not None:
            local_client_instance.upscale_image.side_effect = local_raises
        else:
            local_client_instance.upscale_image.return_value = local_returns
        local_client_factory = MagicMock(return_value=local_client_instance)

        # Patch MODEL_REGISTRY on the fake; the production code reads
        # self.MODEL_REGISTRY which finds the class-level dict.
        with patch.object(agent, "get_client", return_value=base_client), \
             patch.dict(_FakeImageAgent.MODEL_REGISTRY, {"local": local_client_factory}, clear=True):
            result = agent.generate("p", aspect_ratio=aspect_ratio, quality="standard")
        return result, local_client_factory.called, agent.meta_calls

    @pytest.mark.parametrize(
        "provider,env_enabled,aspect_ratio,should_fire",
        [
            # All four conditions met → hybrid path fires.
            ("gemini", True, "2K", True),
            ("gemini", True, "2KPortrait", True),
            ("gemini", True, "4K", True),
            ("gemini", True, "4KPortrait", True),
            # Wrong provider → no fire.
            ("local", True, "4K", False),
            ("openai", True, "4K", False),
            # Env disabled → no fire.
            ("gemini", False, "4K", False),
            # Wrong ratio → no fire (covers ratios outside the upscale set).
            ("gemini", True, "Landscape", False),
            ("gemini", True, "9:16", False),
        ],
    )
    def test_gate_fires_only_on_full_conjunction(
        self, monkeypatch, provider, env_enabled, aspect_ratio, should_fire
    ):
        result, upscaler_called, meta_calls = self._run_generate(
            monkeypatch,
            provider=provider,
            env_enabled=env_enabled,
            aspect_ratio=aspect_ratio,
        )
        assert upscaler_called is should_fire
        if should_fire:
            assert result == b"upscaled_bytes"
            assert ("hybrid_upscale", "succeeded") in meta_calls
        else:
            assert result == b"base_bytes"
            hybrid_meta_keys = [k for k, _ in meta_calls if k == "hybrid_upscale"]
            assert not hybrid_meta_keys

    def test_upscaler_exception_records_failed_breadcrumb(self, monkeypatch):
        """When the local upscaler raises an exception class in the
        catch tuple, the breadcrumb records the failure class so a
        billing-conscious operator can detect the silent-downgrade."""
        result, _, meta_calls = self._run_generate(
            monkeypatch,
            provider="gemini",
            env_enabled=True,
            aspect_ratio="4K",
            local_raises=OSError("disk full"),
        )
        assert result == b"base_bytes"  # silent-downgrade to base
        assert ("hybrid_upscale", "failed:OSError") in meta_calls
