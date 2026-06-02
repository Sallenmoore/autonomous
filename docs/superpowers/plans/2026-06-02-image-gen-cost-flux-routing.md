# FLUX-routing image-gen cost reduction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a FLUX.1 [pro] image-gen provider via fal.ai with an aspect-ratio-tier routing layer in `ImageAgent`, cost-estimate telemetry, opt-in fallback, and an HTML eval harness — cutting average per-image cost without quality regression.

**Architecture:** A new `FluxAIModel(AutoModel)` adapter joins `GeminiAIModel`/`LocalAIModel`/`OpenAIClient`/`MockAIModel` in `MODEL_REGISTRY`. `ImageAgent` gains a `_route_provider(aspect_ratio)` helper that overrides `self.provider` when `IMAGE_PROVIDER_ROUTING=1` is set. Per-call kwargs `fallback_provider` (with `_UNSET` sentinel) and `route=False` give callers explicit control over fallback and routing-bypass. A `scripts/image_provider_eval.py` CLI produces an HTML side-by-side gallery for human quality validation.

**Tech Stack:** Python 3.12+, `requests` (already required), `pytest`, fal.ai HTTPS REST (`https://fal.run/fal-ai/flux-pro/v1.1-ultra`), `autonomous.ai.retry.retry`, `autonomous.ai.image_cache`.

**Spec:** `docs/superpowers/specs/2026-06-02-image-gen-cost-design.md`

---

## File Structure

**Create:**
- `src/autonomous/ai/models/flux.py` — `FluxAIModel(AutoModel)` adapter
- `scripts/image_provider_eval.py` — CLI eval harness
- `scripts/_eval_prompts.json` — starter prompt corpus
- `tests/unit/test_unit_flux.py` — FluxAIModel coverage
- `tests/unit/test_unit_imageagent_routing.py` — routing/cost/fallback coverage in ImageAgent
- `tests/integration/test_integration_flux.py` — FAL_KEY-gated integration test

**Modify:**
- `src/autonomous/ai/imageagent.py` — add `_routing_enabled`, `_COST_USD`, `_route_provider`, `_estimate_cost_usd`, `fallback_provider` attr, `_UNSET` sentinel, new `fallback_provider`/`route` kwargs on `generate`/`upscale`, hybrid-upscale effective-provider fix
- `src/autonomous/ai/baseagent.py` — register `"flux": FluxAIModel`
- `src/autonomous/ai/models/mock_model.py` — accept new kwargs in `generate_image`/`upscale_image`
- `MIGRATIONS.md` — entry for new public API surface

---

## Task 1: Mock provider accepts new kwargs

**Files:**
- Modify: `src/autonomous/ai/models/mock_model.py:74-89`
- Test: `tests/unit/test_unit_mock_model_new_kwargs.py` (new)

The mock provider must accept the v1 kwargs (`fallback_provider`, `route`) so any test routing a call through `ImageAgent` with `provider="mock"` doesn't crash on `TypeError`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_unit_mock_model_new_kwargs.py`:

```python
"""MockAIModel must accept the v1 image-gen kwargs (fallback_provider,
route) so ImageAgent tests using the mock provider don't crash on
TypeError. The mock ignores the new kwargs by design — it's offline."""

from autonomous.ai.models.mock_model import MockAIModel


def _mock():
    """Construct without hitting DB — call methods on the class with a
    bare instance via __new__ since AutoModel.__init__ would lazy-connect
    on save()."""
    m = MockAIModel.__new__(MockAIModel)
    return m


def test_generate_image_accepts_fallback_provider_kwarg():
    out = MockAIModel.generate_image(
        _mock(), "prompt", fallback_provider="gemini"
    )
    assert isinstance(out, (bytes, bytearray))


def test_generate_image_accepts_route_kwarg():
    out = MockAIModel.generate_image(_mock(), "prompt", route=False)
    assert isinstance(out, (bytes, bytearray))


def test_upscale_image_accepts_new_kwargs():
    out = MockAIModel.upscale_image(
        _mock(),
        "prompt",
        image_content=b"x",
        fallback_provider="gemini",
        route=False,
    )
    assert isinstance(out, (bytes, bytearray))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_unit_mock_model_new_kwargs.py -v`
Expected: FAIL with `TypeError: generate_image() got an unexpected keyword argument 'fallback_provider'`

- [ ] **Step 3: Implement**

Modify `src/autonomous/ai/models/mock_model.py:74-89`:

```python
    def generate_image(
        self,
        prompt,
        negative_prompt="",
        files=None,
        aspect_ratio="2KPortrait",
        style=None,
        **kwargs,  # accept fallback_provider, route, and future kwargs
    ):
        log(f"⚡ [MOCK] Generating Image ({aspect_ratio})...", _print=True)
        return self._MOCK_IMAGE_BYTES

    def upscale_image(
        self,
        prompt,
        image_content=None,
        aspect_ratio="2KPortrait",
        style=None,
        **kwargs,
    ):
        log(f"⚡ [MOCK] Upscaling Image ({aspect_ratio})...", _print=True)
        return self._MOCK_IMAGE_BYTES
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_unit_mock_model_new_kwargs.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/models/mock_model.py tests/unit/test_unit_mock_model_new_kwargs.py
git commit -m "test(mock): MockAIModel.generate_image/upscale_image absorb fallback_provider+route kwargs"
```

---

## Task 2: Cost-estimate helper in ImageAgent

**Files:**
- Modify: `src/autonomous/ai/imageagent.py` (add module-level `_COST_USD`, `_estimate_cost_usd` method)
- Test: `tests/unit/test_unit_imageagent_routing.py` (new — used across many tasks)

Pure-function lookup against a static table. Done first because later tasks call it.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_unit_imageagent_routing.py`:

```python
"""Coverage for the ImageAgent routing layer, cost-estimate telemetry,
and the new fallback_provider / route kwargs. Each TestX class targets
one concern so failures localize. All tests are hermetic — they exercise
ImageAgent methods on stub instances and mock the MODEL_REGISTRY entries
through monkeypatch."""

from autonomous.ai.imageagent import ImageAgent, _COST_USD


def _agent():
    """Bare ImageAgent without triggering AutoModel persistence."""
    return ImageAgent.__new__(ImageAgent)


class TestEstimateCostUsd:
    def test_gemini_known_sizes(self):
        for size, expected in [
            ("0.5K", 0.012), ("1K", 0.039), ("2K", 0.078), ("4K", 0.155),
        ]:
            assert ImageAgent._estimate_cost_usd(_agent(), "gemini", size) == expected

    def test_flux_wildcard(self):
        assert ImageAgent._estimate_cost_usd(_agent(), "flux", "Portrait") == 0.040
        assert ImageAgent._estimate_cost_usd(_agent(), "flux", "4K") == 0.040

    def test_local_wildcard_zero(self):
        assert ImageAgent._estimate_cost_usd(_agent(), "local", "2K") == 0.0

    def test_unknown_provider_returns_zero(self):
        assert ImageAgent._estimate_cost_usd(_agent(), "mock", "2K") == 0.0

    def test_unknown_size_falls_through_to_wildcard(self):
        # gemini at an unmapped size falls through to ("gemini", "*") if
        # present; absent, returns 0.0. Today gemini has no "*" entry, so
        # this asserts the "graceful 0.0" tail.
        assert ImageAgent._estimate_cost_usd(_agent(), "gemini", "MysterySize") == 0.0


def test_cost_table_keys_are_complete():
    """The cost table covers every (provider, size) tuple the routing
    layer can dispatch. If a future change adds a new size, the table
    must be updated so cost telemetry doesn't silently zero out."""
    expected_gemini_sizes = {"0.5K", "1K", "2K", "4K"}
    assert {size for (p, size) in _COST_USD if p == "gemini"} == expected_gemini_sizes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_unit_imageagent_routing.py::TestEstimateCostUsd -v`
Expected: FAIL with `ImportError: cannot import name '_COST_USD'`

- [ ] **Step 3: Implement**

Modify `src/autonomous/ai/imageagent.py` — add after the existing `_hybrid_upscale_enabled()` function (around line 36):

```python
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
```

Then add a method to `ImageAgent` (after `_resolve_aspect_ratio`):

```python
    def _estimate_cost_usd(self, provider: str, size: str) -> float:
        """Look up the static per-call cost estimate. Returns 0.0 for
        unknown (provider, size) tuples — silently rather than raising,
        because telemetry must never break an image-gen call."""
        if (provider, size) in _COST_USD:
            return _COST_USD[(provider, size)]
        if (provider, "*") in _COST_USD:
            return _COST_USD[(provider, "*")]
        return 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_unit_imageagent_routing.py::TestEstimateCostUsd tests/unit/test_unit_imageagent_routing.py::test_cost_table_keys_are_complete -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/imageagent.py tests/unit/test_unit_imageagent_routing.py
git commit -m "feat(imageagent): add _COST_USD table + _estimate_cost_usd helper"
```

---

## Task 3: Routing helper + `_routing_enabled` env gate

**Files:**
- Modify: `src/autonomous/ai/imageagent.py`
- Test: `tests/unit/test_unit_imageagent_routing.py` (extend)

`_route_provider(aspect_ratio)` is a pure function of `(aspect_ratio, IMAGE_PROVIDER_ROUTING, self.provider)`. Mechanical routing table.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_unit_imageagent_routing.py`:

```python
class TestRouteProvider:
    """Routing matrix: every aspect_ratio × routing-on/off × self.provider
    combination must resolve correctly. Aspect-ratio names match the
    keys the existing _QUALITY_ASPECT_MAP can emit."""

    HIGH_TIER = {"4K", "4KPortrait", "Map"}
    LOW_AND_MID_TIER = {
        "Portrait", "Landscape", "2K", "2KPortrait",
        "1:1", "3:4", "4:3", "9:16", "16:9",
    }

    def test_routing_off_passes_through(self, monkeypatch):
        monkeypatch.delenv("IMAGE_PROVIDER_ROUTING", raising=False)
        agent = _agent()
        agent.provider = "gemini"
        for ratio in self.HIGH_TIER | self.LOW_AND_MID_TIER:
            assert ImageAgent._route_provider(agent, ratio) == "gemini", ratio

    def test_routing_on_high_tier_to_gemini(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        agent = _agent()
        agent.provider = "flux"  # even if caller asked flux
        for ratio in self.HIGH_TIER:
            assert ImageAgent._route_provider(agent, ratio) == "gemini", ratio

    def test_routing_on_low_mid_tier_to_flux(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        agent = _agent()
        agent.provider = "gemini"  # even if caller asked gemini
        for ratio in self.LOW_AND_MID_TIER:
            assert ImageAgent._route_provider(agent, ratio) == "flux", ratio

    def test_routing_env_truthy_values(self, monkeypatch):
        agent = _agent()
        agent.provider = "gemini"
        for val in ("1", "true", "TRUE", "yes", "Yes"):
            monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", val)
            assert ImageAgent._route_provider(agent, "Portrait") == "flux", val

    def test_routing_env_falsy_values(self, monkeypatch):
        agent = _agent()
        agent.provider = "gemini"
        for val in ("0", "false", "no", "", "off"):
            monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", val)
            assert ImageAgent._route_provider(agent, "Portrait") == "gemini", val
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_unit_imageagent_routing.py::TestRouteProvider -v`
Expected: FAIL with `AttributeError: type object 'ImageAgent' has no attribute '_route_provider'`

- [ ] **Step 3: Implement**

Add to `src/autonomous/ai/imageagent.py` after `_hybrid_upscale_enabled`:

```python
def _routing_enabled() -> bool:
    """True iff IMAGE_PROVIDER_ROUTING is set to a truthy string."""
    return os.environ.get("IMAGE_PROVIDER_ROUTING", "").lower() in {
        "1", "true", "yes"
    }
```

Add to `ImageAgent` (next to `_resolve_aspect_ratio`):

```python
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
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_unit_imageagent_routing.py::TestRouteProvider -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/imageagent.py tests/unit/test_unit_imageagent_routing.py
git commit -m "feat(imageagent): _route_provider + IMAGE_PROVIDER_ROUTING env gate"
```

---

## Task 4: `FluxAIModel` scaffold + `_get_image_config`

**Files:**
- Create: `src/autonomous/ai/models/flux.py`
- Test: `tests/unit/test_unit_flux.py` (new)

Module imports cleanly without `FAL_KEY`. `_get_image_config` is a pure function mapping autonomous's aspect-ratio vocabulary to fal.ai's.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_unit_flux.py`:

```python
"""FluxAIModel adapter tests. Hermetic — every test that would call
fal.ai mocks requests.post.

Test classes:
- TestImport: module imports without FAL_KEY; first dispatch raises.
- TestGetImageConfig: aspect-ratio mapping table is correct.
- TestGenerateImage: happy path, retry, empty body, files=, missing key.
- TestUpscaleImage: honest no-op."""

import os

import pytest


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
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_unit_flux.py::TestImport tests/unit/test_unit_flux.py::TestGetImageConfig -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'autonomous.ai.models.flux'`

- [ ] **Step 3: Implement**

Create `src/autonomous/ai/models/flux.py`:

```python
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

HTTP: plain ``requests`` (already required), routed through
``autonomous.ai.retry.retry`` for bounded retries with backoff.
"""

import io
import json
import os

import requests

from autonomous import log
from autonomous.ai.retry import retry
from autonomous.model.automodel import AutoModel


_SESSION = requests.Session()


class FluxAIModel(AutoModel):
    _client = None

    # Model defaults are env-overridable so deployments can chase fal.ai's
    # model churn without a library release.
    _image_model = os.environ.get(
        "FLUX_IMAGE_MODEL", "fal-ai/flux-pro/v1.1-ultra"
    )
    _image_url_base = os.environ.get("FLUX_URL_BASE", "https://fal.run")
    _media_timeout = int(os.environ.get("FLUX_TIMEOUT_S", "120"))
    _max_attempts = int(os.environ.get("FLUX_MAX_ATTEMPTS", "3"))
    _retry_sleep = float(os.environ.get("FLUX_RETRY_SLEEP", "1.0"))

    def _get_image_config(self, aspect_ratio_input):
        """Map autonomous's aspect-ratio vocabulary to fal.ai's
        ``(aspect_ratio, image_size)`` pair.

        fal.ai accepts ``aspect_ratio`` from {1:1, 16:9, 9:16, 4:3, 3:4,
        ...} and ``image_size`` from a preset enum
        (square/square_hd/portrait_4_3/portrait_16_9/landscape_4_3/
        landscape_16_9). The mapping below mirrors GeminiAIModel's
        ``_get_image_config`` so the two adapters present the same
        external vocabulary."""
        ratio, size = "3:4", "square_hd"  # default fallback
        if aspect_ratio_input == "Portrait":
            ratio, size = "3:4", "square_hd"
        elif aspect_ratio_input == "Landscape":
            ratio, size = "16:9", "square_hd"
        elif aspect_ratio_input == "2K":
            ratio, size = "16:9", "landscape_4_3"
        elif aspect_ratio_input == "2KPortrait":
            ratio, size = "3:4", "portrait_4_3"
        elif aspect_ratio_input in ("4K", "Map"):
            ratio, size = "16:9", "landscape_16_9"
        elif aspect_ratio_input == "4KPortrait":
            ratio, size = "3:4", "portrait_16_9"
        elif aspect_ratio_input in ("1:1", "3:4", "4:3", "9:16", "16:9"):
            ratio = aspect_ratio_input
        return ratio, size

    def _require_api_key(self):
        """Read FAL_KEY at call time, not import time. Raises with a
        pointer to the env var if missing — easier to debug than a 401
        from fal.ai's API."""
        key = os.environ.get("FAL_KEY", "").strip()
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

        def _post():
            resp = _SESSION.post(
                url, headers=headers, json=body, timeout=self._media_timeout
            )
            resp.raise_for_status()
            return resp

        try:
            resp = retry(
                _post,
                max_attempts=self._max_attempts,
                sleep_seconds=self._retry_sleep,
                catch=(requests.RequestException,),
            )
            payload = resp.json()
            images = payload.get("images") or []
            if not images:
                raise ValueError(
                    f"fal.ai returned success but no images in response: "
                    f"{payload!r}"
                )
            image_url = images[0].get("url")
            if not image_url:
                raise ValueError(
                    f"fal.ai response missing image URL: {images[0]!r}"
                )
            img_resp = _SESSION.get(image_url, timeout=self._media_timeout)
            img_resp.raise_for_status()
            return img_resp.content
        except (requests.RequestException, ValueError, OSError) as e:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_unit_flux.py::TestImport tests/unit/test_unit_flux.py::TestGetImageConfig -v`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/models/flux.py tests/unit/test_unit_flux.py
git commit -m "feat(ai): FluxAIModel scaffold + _get_image_config aspect-ratio mapping"
```

---

## Task 5: `FluxAIModel.generate_image` happy path

**Files:**
- Test: `tests/unit/test_unit_flux.py` (extend)

The implementation is already in place from Task 4. This task drives the happy-path test that exercises mocked `requests.post` + `requests.Session.get`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_unit_flux.py`:

```python
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


import requests  # placed after the helper for clarity


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
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/unit/test_unit_flux.py::TestGenerateImage::test_happy_path_posts_and_fetches_image -v`
Expected: 1 passed

(Test should pass on first run — the implementation was already written in Task 4. If it fails, fix the implementation, not the test.)

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_unit_flux.py
git commit -m "test(flux): cover generate_image happy path with mocked HTTP"
```

---

## Task 6: `FluxAIModel.generate_image` error paths

**Files:**
- Test: `tests/unit/test_unit_flux.py` (extend)

Five error paths from the spec's error-handling table. All implementations are already in place — this task drives coverage.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_unit_flux.py`:

```python
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
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/unit/test_unit_flux.py -v`
Expected: 20 passed (previous + these new tests)

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_unit_flux.py
git commit -m "test(flux): cover error paths — files, FAL_KEY, retry exhaustion, empty body"
```

---

## Task 7: Register `flux` in `MODEL_REGISTRY`

**Files:**
- Modify: `src/autonomous/ai/baseagent.py`
- Test: `tests/unit/test_unit_baseagent_get_client_persist.py` (extend) OR a fresh test

Register FluxAIModel under the `"flux"` key so `BaseAgent.get_client("flux")` resolves correctly.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_unit_baseagent_flux_registry.py`:

```python
"""FluxAIModel must be registered in BaseAgent.MODEL_REGISTRY under the
'flux' key so ImageAgent's routing layer can dispatch to it via the
existing get_client mechanism."""

from autonomous.ai.baseagent import BaseAgent
from autonomous.ai.models.flux import FluxAIModel


def test_flux_registered_in_model_registry():
    assert BaseAgent.MODEL_REGISTRY.get("flux") is FluxAIModel
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/unit/test_unit_baseagent_flux_registry.py -v`
Expected: FAIL — registry missing `"flux"` key

- [ ] **Step 3: Implement**

Modify `src/autonomous/ai/baseagent.py` around the existing `MODEL_REGISTRY` block:

```python
from .models.flux import FluxAIModel  # add to imports
# ... existing imports ...

class BaseAgent(AutoModel):
    MODEL_REGISTRY = {
        "local":  LocalAIModel,
        "gemini": GeminiAIModel,
        "openai": OpenAIClient,
        "mock":   MockAIModel,
        "flux":   FluxAIModel,   # NEW
    }
```

(Verify exact line numbers + existing entries with `grep -n MODEL_REGISTRY src/autonomous/ai/baseagent.py` before editing.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_unit_baseagent_flux_registry.py -v && pytest tests/unit/ -q 2>&1 | tail -5`
Expected: 1 passed (new); full unit suite still green.

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/baseagent.py tests/unit/test_unit_baseagent_flux_registry.py
git commit -m "feat(ai): register FluxAIModel in BaseAgent.MODEL_REGISTRY"
```

---

## Task 8: `ImageAgent.generate` — `fallback_provider` attr + `_UNSET` sentinel

**Files:**
- Modify: `src/autonomous/ai/imageagent.py`
- Test: `tests/unit/test_unit_imageagent_routing.py` (extend)

Add the instance attr, the module-level sentinel, and the resolution helper. Don't wire it into `generate()` yet — this task is just the data plumbing.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_unit_imageagent_routing.py`:

```python
class TestFallbackResolution:
    """The _UNSET sentinel distinguishes 'caller did not pass kwarg'
    from 'caller passed None to disable.' Instance default is used when
    the kwarg is _UNSET; explicit None disables fallback; explicit string
    selects that provider."""

    def test_unset_inherits_instance_default(self):
        from autonomous.ai.imageagent import ImageAgent, _UNSET
        agent = _agent()
        agent.fallback_provider = "gemini"
        assert ImageAgent._resolve_fallback(agent, _UNSET) == "gemini"

    def test_explicit_none_disables_fallback(self):
        from autonomous.ai.imageagent import ImageAgent
        agent = _agent()
        agent.fallback_provider = "gemini"
        assert ImageAgent._resolve_fallback(agent, None) is None

    def test_explicit_string_overrides_instance_default(self):
        from autonomous.ai.imageagent import ImageAgent
        agent = _agent()
        agent.fallback_provider = "gemini"
        assert ImageAgent._resolve_fallback(agent, "local") == "local"

    def test_unset_with_no_instance_default_returns_none(self):
        from autonomous.ai.imageagent import ImageAgent, _UNSET
        agent = _agent()
        agent.fallback_provider = None
        assert ImageAgent._resolve_fallback(agent, _UNSET) is None
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_unit_imageagent_routing.py::TestFallbackResolution -v`
Expected: FAIL — `_UNSET` doesn't exist; `_resolve_fallback` doesn't exist

- [ ] **Step 3: Implement**

Modify `src/autonomous/ai/imageagent.py`:

```python
# Add near the top, after imports:
_UNSET = object()
```

Add to the `ImageAgent` class:

```python
    fallback_provider = StringAttr(default=None)   # add to class attrs

    def _resolve_fallback(self, fallback_provider):
        """Apply the _UNSET-sentinel resolution rule.

        Returns the effective fallback provider string, or None to
        disable fallback for this call.
        """
        if fallback_provider is _UNSET:
            return self.fallback_provider
        return fallback_provider
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_unit_imageagent_routing.py::TestFallbackResolution -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/imageagent.py tests/unit/test_unit_imageagent_routing.py
git commit -m "feat(imageagent): fallback_provider attr + _UNSET sentinel + _resolve_fallback"
```

---

## Task 9: `ImageAgent.generate` — wire routing + cost telemetry + `route=False`

**Files:**
- Modify: `src/autonomous/ai/imageagent.py:63-103` (the existing `generate` method)
- Test: `tests/unit/test_unit_imageagent_routing.py` (extend)

Wire `_route_provider` and `_estimate_cost_usd` into `generate()`. Add the new kwargs. No fallback logic yet — that's Task 10.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_unit_imageagent_routing.py`:

```python
class _StubProviderClient:
    """Records calls to generate_image; returns deterministic bytes."""

    def __init__(self, name, bytes_=b"img"):
        self.name = name
        self.bytes_ = bytes_
        self.calls = []

    def generate_image(self, prompt, negative_prompt="", aspect_ratio="",
                       files=None, style=None):
        self.calls.append({
            "prompt": prompt, "aspect_ratio": aspect_ratio,
            "negative_prompt": negative_prompt,
        })
        return self.bytes_

    def upscale_image(self, prompt, image_content=None,
                      aspect_ratio="", style=None):
        self.calls.append({"prompt": prompt, "upscale": True})
        return image_content


def _patched_agent(monkeypatch, clients_by_provider):
    """Build an ImageAgent that routes get_client to provided stubs and
    captures add_to_job_meta calls."""
    from autonomous.ai.imageagent import ImageAgent
    agent = _agent()
    agent.provider = "gemini"
    agent.fallback_provider = None
    agent._meta_log = []

    def fake_get_client(provider):
        return clients_by_provider[provider]
    agent.get_client = fake_get_client

    def fake_add_meta(k, v):
        agent._meta_log.append((k, v))
    agent.add_to_job_meta = fake_add_meta

    # Default: short-circuit the cache (treat as miss + no-op put).
    from autonomous.ai import image_cache
    monkeypatch.setattr(image_cache, "get", lambda _: None)
    monkeypatch.setattr(image_cache, "put", lambda *_a, **_k: None)
    return agent


class TestGenerateDispatch:
    def test_routing_off_uses_self_provider(self, monkeypatch):
        monkeypatch.delenv("IMAGE_PROVIDER_ROUTING", raising=False)
        from autonomous.ai.imageagent import ImageAgent
        gemini = _StubProviderClient("gemini")
        flux = _StubProviderClient("flux")
        agent = _patched_agent(monkeypatch, {"gemini": gemini, "flux": flux})

        ImageAgent.generate(agent, "prompt", aspect_ratio="Portrait")

        assert len(gemini.calls) == 1
        assert flux.calls == []

    def test_routing_on_low_tier_uses_flux(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        from autonomous.ai.imageagent import ImageAgent
        gemini = _StubProviderClient("gemini")
        flux = _StubProviderClient("flux")
        agent = _patched_agent(monkeypatch, {"gemini": gemini, "flux": flux})

        ImageAgent.generate(agent, "prompt", aspect_ratio="Portrait")

        assert len(flux.calls) == 1
        assert gemini.calls == []

    def test_routing_on_high_tier_uses_gemini(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        from autonomous.ai.imageagent import ImageAgent
        gemini = _StubProviderClient("gemini")
        flux = _StubProviderClient("flux")
        agent = _patched_agent(monkeypatch, {"gemini": gemini, "flux": flux})
        agent.provider = "flux"   # even when caller asked flux

        ImageAgent.generate(agent, "prompt", aspect_ratio="4K")

        assert len(gemini.calls) == 1
        assert flux.calls == []

    def test_route_false_bypasses_routing(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        from autonomous.ai.imageagent import ImageAgent
        gemini = _StubProviderClient("gemini")
        flux = _StubProviderClient("flux")
        agent = _patched_agent(monkeypatch, {"gemini": gemini, "flux": flux})
        agent.provider = "gemini"

        ImageAgent.generate(agent, "prompt", aspect_ratio="Portrait",
                            route=False)

        # routing would have picked flux; route=False keeps gemini
        assert len(gemini.calls) == 1
        assert flux.calls == []


class TestGenerateCostTelemetry:
    def test_writes_cost_estimate_to_job_meta(self, monkeypatch):
        monkeypatch.delenv("IMAGE_PROVIDER_ROUTING", raising=False)
        from autonomous.ai.imageagent import ImageAgent
        agent = _patched_agent(
            monkeypatch, {"gemini": _StubProviderClient("gemini")}
        )

        ImageAgent.generate(agent, "prompt", aspect_ratio="Portrait")

        cost_entries = [v for k, v in agent._meta_log if k == "cost_estimate_usd"]
        assert cost_entries == [0.012]   # gemini @ 0.5K

    def test_writes_effective_provider_to_job_meta(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        from autonomous.ai.imageagent import ImageAgent
        agent = _patched_agent(
            monkeypatch,
            {"gemini": _StubProviderClient("gemini"), "flux": _StubProviderClient("flux")},
        )

        ImageAgent.generate(agent, "prompt", aspect_ratio="Portrait")

        eff = [v for k, v in agent._meta_log if k == "effective_provider"]
        assert eff == ["flux"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_unit_imageagent_routing.py::TestGenerateDispatch tests/unit/test_unit_imageagent_routing.py::TestGenerateCostTelemetry -v`
Expected: FAIL — routing/route-kwarg not yet wired into `generate()`

- [ ] **Step 3: Implement**

Modify `src/autonomous/ai/imageagent.py`'s `generate` method. The full new signature + body:

```python
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
):
    effective_ratio = self._resolve_aspect_ratio(aspect_ratio, quality)
    effective_provider = (
        self._route_provider(effective_ratio) if route else self.provider
    )

    self.add_to_job_meta("prompt", prompt)
    self.add_to_job_meta("provider", self.provider)
    self.add_to_job_meta("effective_provider", effective_provider)
    self.add_to_job_meta("quality", quality)
    self.add_to_job_meta("aspect_ratio", effective_ratio)

    # _size_token derives the cost-table key from effective_ratio.
    # For raw aspect tokens (Portrait/Landscape/1:1/etc.) the size is
    # the provider's default per the spec mapping; for tier tokens
    # (2K/2KPortrait/4K/4KPortrait/Map) it's the suffix.
    size_token = _aspect_to_size_token(effective_ratio)
    self.add_to_job_meta(
        "cost_estimate_usd",
        self._estimate_cost_usd(effective_provider, size_token),
    )

    key = image_cache.cache_key(
        prompt=prompt,
        negative_prompt=negative_prompt,
        style=style,
        aspect_ratio=effective_ratio,
        files=files,
        provider=effective_provider,    # CHANGED: cache key reflects effective
        method="generate",
    )
    cached = image_cache.get(key)
    if cached is not None:
        log(
            f"Image cache HIT key={key[:12]} provider={effective_provider}",
            _print=False,
        )
        return cached

    result = self.get_client(effective_provider).generate_image(
        prompt,
        negative_prompt=negative_prompt,
        aspect_ratio=effective_ratio,
        files=files,
        style=style,
    )

    # ... existing hybrid-upscale block (modified in Task 11) ...

    if result:
        image_cache.put(key, result)
    return result
```

Add the size-token helper at module scope (next to `_COST_USD`):

```python
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
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_unit_imageagent_routing.py::TestGenerateDispatch tests/unit/test_unit_imageagent_routing.py::TestGenerateCostTelemetry -v`
Expected: 6 passed

Also run the full file: `pytest tests/unit/test_unit_imageagent_routing.py -v`
Expected: all previous tests still green.

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/imageagent.py tests/unit/test_unit_imageagent_routing.py
git commit -m "feat(imageagent): wire routing + cost telemetry + route=False into generate()"
```

---

## Task 10: `ImageAgent.generate` — fallback path

**Files:**
- Modify: `src/autonomous/ai/imageagent.py` (extend `generate`)
- Test: `tests/unit/test_unit_imageagent_routing.py` (extend)

When the routed provider raises after retry exhaustion, fall back exactly once on the resolved fallback provider. Log loudly; update breadcrumbs.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_unit_imageagent_routing.py`:

```python
class _RaisingProviderClient:
    """Provider stub that always raises on generate_image."""

    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def generate_image(self, *_a, **_k):
        self.calls += 1
        raise self.exc

    def upscale_image(self, *_a, **_k):
        raise self.exc


class TestGenerateFallback:
    def test_fallback_on_routed_provider_failure(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        from autonomous.ai.imageagent import ImageAgent
        flux = _RaisingProviderClient(RuntimeError("flux down"))
        gemini = _StubProviderClient("gemini", bytes_=b"gemini-img")
        agent = _patched_agent(monkeypatch, {"flux": flux, "gemini": gemini})

        result = ImageAgent.generate(
            agent, "prompt",
            aspect_ratio="Portrait",
            fallback_provider="gemini",
        )

        assert result == b"gemini-img"
        assert flux.calls == 1
        assert len(gemini.calls) == 1
        # job_meta breadcrumbs
        flags = {k: v for k, v in agent._meta_log}
        assert flags["provider_fallback_used"] is True
        assert flags["effective_provider"] == "gemini"   # updated after fallback
        # cost reflects the actual provider — gemini Portrait → 0.5K = 0.012
        assert flags["cost_estimate_usd"] == 0.012

    def test_no_fallback_when_kwarg_is_none(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        from autonomous.ai.imageagent import ImageAgent
        flux = _RaisingProviderClient(RuntimeError("flux down"))
        gemini = _StubProviderClient("gemini")
        agent = _patched_agent(monkeypatch, {"flux": flux, "gemini": gemini})
        agent.fallback_provider = "gemini"   # instance default

        with pytest.raises(RuntimeError, match="flux down"):
            ImageAgent.generate(
                agent, "prompt",
                aspect_ratio="Portrait",
                fallback_provider=None,   # explicit override of instance default
            )
        assert gemini.calls == []

    def test_inherits_instance_fallback_when_kwarg_unset(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        from autonomous.ai.imageagent import ImageAgent
        flux = _RaisingProviderClient(RuntimeError("flux down"))
        gemini = _StubProviderClient("gemini", bytes_=b"gem")
        agent = _patched_agent(monkeypatch, {"flux": flux, "gemini": gemini})
        agent.fallback_provider = "gemini"

        result = ImageAgent.generate(
            agent, "prompt", aspect_ratio="Portrait"
        )
        assert result == b"gem"

    def test_fallback_itself_raises_propagates(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        from autonomous.ai.imageagent import ImageAgent
        flux = _RaisingProviderClient(RuntimeError("flux down"))
        gemini = _RaisingProviderClient(RuntimeError("gemini also down"))
        agent = _patched_agent(monkeypatch, {"flux": flux, "gemini": gemini})

        with pytest.raises(RuntimeError, match="gemini also down"):
            ImageAgent.generate(
                agent, "prompt", aspect_ratio="Portrait",
                fallback_provider="gemini",
            )

        flags = {k: v for k, v in agent._meta_log}
        assert flags["provider_fallback_used"] is True
        assert flags["fallback_succeeded"] is False
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_unit_imageagent_routing.py::TestGenerateFallback -v`
Expected: FAIL — no fallback wired into `generate()`

- [ ] **Step 3: Implement**

Update `ImageAgent.generate` in `src/autonomous/ai/imageagent.py` — wrap the provider call with the fallback logic. Insert after `effective_provider = ...` and before the existing cache-key block:

```python
    effective_fallback = self._resolve_fallback(fallback_provider)
```

Replace the existing `result = self.get_client(...).generate_image(...)` with:

```python
    try:
        result = self.get_client(effective_provider).generate_image(
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
            # "Cache key semantics on fallback").
            key = image_cache.cache_key(
                prompt=prompt,
                negative_prompt=negative_prompt,
                style=style,
                aspect_ratio=effective_ratio,
                files=files,
                provider=effective_provider,
                method="generate",
            )
        except Exception:
            self.add_to_job_meta("fallback_succeeded", False)
            raise
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_unit_imageagent_routing.py::TestGenerateFallback -v`
Expected: 4 passed

Then full file: `pytest tests/unit/test_unit_imageagent_routing.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/imageagent.py tests/unit/test_unit_imageagent_routing.py
git commit -m "feat(imageagent): opt-in fallback_provider with retry-exhaustion semantics"
```

---

## Task 11: Hybrid-upscale uses effective provider

**Files:**
- Modify: `src/autonomous/ai/imageagent.py` (the hybrid-upscale block in `generate`, currently `imageagent.py:113-147`)
- Test: `tests/unit/test_unit_imageagent_routing.py` (extend)

The existing hybrid-upscale gate checks `self.provider == "gemini"`. With routing on, that's the *requested* provider — not the *effective* one. Update the gate.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_unit_imageagent_routing.py`:

```python
class TestHybridUpscaleEffectiveProvider:
    """The hybrid-upscale gate must look at the *effective* provider
    (after routing), not self.provider. Otherwise a routing-on call to
    FLUX would still trigger the local upscaler designed for Gemini
    output."""

    def test_hybrid_not_invoked_when_effective_provider_is_flux(
        self, monkeypatch
    ):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        monkeypatch.setenv("IMAGE_HYBRID_UPSCALE", "1")

        from autonomous.ai.imageagent import ImageAgent
        flux = _StubProviderClient("flux", bytes_=b"flux-base")
        local = _StubProviderClient("local")
        agent = _patched_agent(monkeypatch, {"flux": flux, "local": local})
        agent.provider = "gemini"   # requested
        # Wire MODEL_REGISTRY["local"] to a class that returns our stub.
        class _LocalCls:
            def __init__(self, **kw):
                pass
            def upscale_image(self, *a, **k):
                local.calls.append({"upscale": True})
                return b"upscaled"
        agent.MODEL_REGISTRY = {"local": _LocalCls}

        ImageAgent.generate(
            agent, "prompt", aspect_ratio="2K"
        )   # routes to flux

        assert flux.calls != []
        assert local.calls == []   # local upscaler NOT invoked

    def test_hybrid_invoked_when_effective_provider_is_gemini(
        self, monkeypatch
    ):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        monkeypatch.setenv("IMAGE_HYBRID_UPSCALE", "1")

        from autonomous.ai.imageagent import ImageAgent
        gemini = _StubProviderClient("gemini", bytes_=b"gem-base")
        local_calls = []

        class _LocalCls:
            def __init__(self, **kw):
                pass
            def upscale_image(self, *a, **k):
                local_calls.append({"upscale": True})
                return b"upscaled"

        agent = _patched_agent(monkeypatch, {"gemini": gemini})
        agent.provider = "gemini"
        agent.MODEL_REGISTRY = {"local": _LocalCls}

        ImageAgent.generate(
            agent, "prompt", aspect_ratio="4K"
        )   # 4K routes to gemini

        assert local_calls == [{"upscale": True}]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_unit_imageagent_routing.py::TestHybridUpscaleEffectiveProvider -v`
Expected: at least one test fails (the FLUX-effective case will currently still invoke the local upscaler because the gate uses `self.provider`).

- [ ] **Step 3: Implement**

In `src/autonomous/ai/imageagent.py`, the hybrid-upscale `if` block currently reads:

```python
if (
    result
    and self.provider == "gemini"
    and _hybrid_upscale_enabled()
    and effective_ratio in {"2K", "2KPortrait", "4K", "4KPortrait"}
):
```

Change `self.provider == "gemini"` to `effective_provider == "gemini"`:

```python
if (
    result
    and effective_provider == "gemini"
    and _hybrid_upscale_enabled()
    and effective_ratio in {"2K", "2KPortrait", "4K", "4KPortrait"}
):
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_unit_imageagent_routing.py::TestHybridUpscaleEffectiveProvider -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/imageagent.py tests/unit/test_unit_imageagent_routing.py
git commit -m "fix(imageagent): hybrid-upscale gate uses effective provider, not self.provider"
```

---

## Task 12: `ImageAgent.upscale` — apply routing/fallback/route/cost

**Files:**
- Modify: `src/autonomous/ai/imageagent.py:153-196` (the existing `upscale` method)
- Test: `tests/unit/test_unit_imageagent_routing.py` (extend)

`upscale()` needs the same `fallback_provider`/`route` kwargs and the same cost-telemetry treatment. Provider resolution mirrors `generate()`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_unit_imageagent_routing.py`:

```python
class TestUpscaleDispatch:
    def test_upscale_writes_cost_and_provider_meta(self, monkeypatch):
        monkeypatch.delenv("IMAGE_PROVIDER_ROUTING", raising=False)
        from autonomous.ai.imageagent import ImageAgent
        gemini = _StubProviderClient("gemini")
        agent = _patched_agent(monkeypatch, {"gemini": gemini})

        ImageAgent.upscale(
            agent, "prompt", image_content=b"in", aspect_ratio="2KPortrait"
        )

        flags = {k: v for k, v in agent._meta_log}
        assert flags["effective_provider"] == "gemini"
        assert flags["cost_estimate_usd"] == 0.078   # gemini 2K

    def test_upscale_honors_route_false(self, monkeypatch):
        monkeypatch.setenv("IMAGE_PROVIDER_ROUTING", "1")
        from autonomous.ai.imageagent import ImageAgent
        gemini = _StubProviderClient("gemini")
        flux = _StubProviderClient("flux")
        agent = _patched_agent(monkeypatch, {"gemini": gemini, "flux": flux})
        agent.provider = "gemini"

        ImageAgent.upscale(
            agent, "prompt", image_content=b"in",
            aspect_ratio="2KPortrait", route=False
        )

        # routing would have picked flux for 2KPortrait
        assert any("upscale" in c for c in gemini.calls)
        assert flux.calls == []
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/unit/test_unit_imageagent_routing.py::TestUpscaleDispatch -v`
Expected: FAIL — upscale doesn't yet have route/fallback kwargs or telemetry

- [ ] **Step 3: Implement**

Replace `ImageAgent.upscale` in `src/autonomous/ai/imageagent.py` with:

```python
def upscale(
    self,
    prompt,
    image_content=None,
    aspect_ratio="2KPortrait",
    style=None,
    quality="standard",
    fallback_provider=_UNSET,
    route=True,
):
    effective_ratio = self._resolve_aspect_ratio(aspect_ratio, quality)
    requested = os.environ.get("IMAGE_AI_AGENT", self.provider)
    effective_provider = (
        self._route_provider(effective_ratio)
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

    try:
        result = self.get_client(effective_provider).upscale_image(
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
        except Exception:
            self.add_to_job_meta("fallback_succeeded", False)
            raise

    if result is image_content:
        self.add_to_job_meta("upscale_supported", False)
    if result:
        image_cache.put(key, result)
    return result
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/unit/test_unit_imageagent_routing.py::TestUpscaleDispatch -v`
Expected: 2 passed

Full file: `pytest tests/unit/test_unit_imageagent_routing.py -v`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add src/autonomous/ai/imageagent.py tests/unit/test_unit_imageagent_routing.py
git commit -m "feat(imageagent): routing + fallback + cost telemetry on upscale()"
```

---

## Task 13: Eval-harness prompt corpus

**Files:**
- Create: `scripts/_eval_prompts.json`

8–10 hand-curated storyteller-shaped prompts covering character / scene / map / hero. Hardcoded — no test for the file's content. Just a starter set the operator can extend.

- [ ] **Step 1: Create the corpus**

Create `scripts/_eval_prompts.json`:

```json
[
  {
    "slug": "character-rogue",
    "category": "character",
    "prompt": "Half-elf rogue, dark cloak with silver clasp, twin daggers at hips, alley moonlight, faint scar across jaw, expression of calculation. Painterly fantasy illustration."
  },
  {
    "slug": "character-wizard",
    "category": "character",
    "prompt": "Elderly human wizard, indigo robes embroidered with stars, gnarled staff topped with raw quartz, half-lidded eyes, soft library candlelight, faint motes of dust in beams."
  },
  {
    "slug": "scene-tavern-interior",
    "category": "scene",
    "prompt": "Crowded medieval tavern interior at evening, warm hearth fire, long wooden tables, patrons mid-conversation, motes of dust in lamplight, painterly atmospheric."
  },
  {
    "slug": "scene-forest-ruin",
    "category": "scene",
    "prompt": "Overgrown stone ruin in dense forest, moss-covered pillars, shafts of sunlight through canopy, small wildflowers in foreground, vines climbing the walls, sense of stillness."
  },
  {
    "slug": "scene-stormy-coast",
    "category": "scene",
    "prompt": "Rugged northern coastline under stormy sky, waves crashing against black basalt cliffs, single weathered lighthouse silhouette, gulls in the gusts, dramatic lighting."
  },
  {
    "slug": "hero-dragon-encounter",
    "category": "hero",
    "prompt": "Adventuring party facing a copper dragon perched on a cliff above a misty valley at dawn, scale and detail emphasized, sense of consequence, cinematic composition."
  },
  {
    "slug": "hero-throne-room",
    "category": "hero",
    "prompt": "Vaulted throne hall of an ancient elven king, polished marble floors reflecting torch flames, massive stained-glass windows pouring colored light, intricate architectural detail."
  },
  {
    "slug": "map-overland-region",
    "category": "map",
    "prompt": "Top-down regional fantasy map: rolling hills, a winding river splitting the territory east-to-west, three small towns (north, southeast, southwest), one mountain range to the north, painted in classic hand-drawn cartographic style."
  },
  {
    "slug": "map-dungeon-level",
    "category": "map",
    "prompt": "Top-down dungeon level map: stone-walled corridors connecting six rooms of varying sizes, secret passage marked with dashed lines, two trap symbols, hand-drawn ink-and-paper cartographic style, labeled rooms."
  },
  {
    "slug": "item-magical-tome",
    "category": "item",
    "prompt": "Single magical tome at center, leather-bound with iron clasps, runic glyphs faintly glowing on the cover, set on a dark cloth, warm dramatic lighting, fine detail."
  }
]
```

- [ ] **Step 2: Commit**

```bash
git add scripts/_eval_prompts.json
git commit -m "feat(scripts): seed prompt corpus for image_provider_eval harness"
```

---

## Task 14: Eval-harness CLI + HTML output

**Files:**
- Create: `scripts/image_provider_eval.py`

CLI: `python scripts/image_provider_eval.py --prompts scripts/_eval_prompts.json --providers gemini,flux,local --aspect-ratios Portrait,2KPortrait --out eval-<date>/`. Generates an image per (prompt × provider × aspect_ratio), writes `index.html` + `summary.json`. Cache-aware via `image_cache.cache_key`.

- [ ] **Step 1: Smoke-test the harness scaffold by running with `--providers mock`**

(Test setup — no separate test file. The mock provider returns deterministic bytes, so we can exercise the harness end-to-end without real API calls.)

- [ ] **Step 2: Implement**

Create `scripts/image_provider_eval.py`:

```python
#!/usr/bin/env python3
"""Image-provider evaluation harness.

Generate the same prompt corpus through N image providers and produce
a side-by-side HTML gallery for human creative-quality review. Used as
the validation gate before flipping IMAGE_PROVIDER_ROUTING=1 in
production (see specs/2026-06-02-image-gen-cost-design.md).

Usage:
    python scripts/image_provider_eval.py \\
      --prompts scripts/_eval_prompts.json \\
      --providers gemini,flux,local \\
      --aspect-ratios Portrait,2KPortrait \\
      --out eval-2026-06-02/

The harness is cache-aware — uses ``image_cache.cache_key`` so re-runs
after a single prompt edit only re-bill for the edited prompt. Set
``AUTONOMOUS_IMAGE_CACHE_DIR`` to enable.
"""

import argparse
import json
import sys
import time
from html import escape
from pathlib import Path

from autonomous.ai.baseagent import BaseAgent
from autonomous.ai.imageagent import _COST_USD, _aspect_to_size_token


def _load_prompts(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"prompt corpus not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _estimate_cost(provider: str, aspect_ratio: str) -> float:
    size = _aspect_to_size_token(aspect_ratio)
    if (provider, size) in _COST_USD:
        return _COST_USD[(provider, size)]
    if (provider, "*") in _COST_USD:
        return _COST_USD[(provider, "*")]
    return 0.0


def _safe_filename(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in text)


def _generate(provider: str, prompt: str, aspect_ratio: str) -> tuple[bytes | None, float, str | None]:
    """Return (image_bytes_or_None, elapsed_seconds, error_or_None)."""
    cls = BaseAgent.MODEL_REGISTRY.get(provider)
    if cls is None:
        return None, 0.0, f"provider {provider!r} not in MODEL_REGISTRY"
    client = cls.__new__(cls)
    try:
        cls.__init__(client) if hasattr(cls, "__init__") else None
    except Exception as exc:
        return None, 0.0, f"could not init {provider}: {exc}"
    started = time.monotonic()
    try:
        img = client.generate_image(prompt, aspect_ratio=aspect_ratio)
    except Exception as exc:
        return None, time.monotonic() - started, f"{type(exc).__name__}: {exc}"
    return img, time.monotonic() - started, None


def _write_html(out_dir: Path, results: list[dict], providers: list[str]) -> None:
    rows = []
    by_prompt: dict[tuple[str, str], dict[str, dict]] = {}
    for r in results:
        by_prompt.setdefault((r["slug"], r["aspect_ratio"]), {})[r["provider"]] = r

    for (slug, ratio), per_prov in by_prompt.items():
        cells = []
        for prov in providers:
            entry = per_prov.get(prov, {})
            if entry.get("relpath"):
                cells.append(
                    f'<td><img src="{escape(entry["relpath"])}" alt="{escape(slug)}">'
                    f"<br><small>{prov} — {entry['elapsed']:.1f}s — ${entry['cost']:.3f}</small></td>"
                )
            else:
                err = entry.get("error", "(no result)")
                cells.append(
                    f'<td class="err">{prov} — failed<br><small>{escape(err)}</small></td>'
                )
        rows.append(
            f"<tr><th>{escape(slug)}<br><small>{escape(ratio)}</small></th>"
            + "".join(cells)
            + "</tr>"
        )

    head_cells = "<th></th>" + "".join(f"<th>{escape(p)}</th>" for p in providers)
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>image-provider eval</title>
<style>
  body {{ font-family: system-ui, sans-serif; }}
  table {{ border-collapse: collapse; }}
  th, td {{ border: 1px solid #ccc; padding: 8px; vertical-align: top; }}
  img {{ max-width: 320px; height: auto; display: block; }}
  td.err {{ color: #a00; }}
</style></head><body>
<h1>image-provider eval</h1>
<table><thead><tr>{head_cells}</tr></thead>
<tbody>{''.join(rows)}</tbody></table>
</body></html>
"""
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompts", required=True, type=Path,
                        help="path to prompt corpus JSON")
    parser.add_argument("--providers", required=True,
                        help="comma-separated providers, e.g. gemini,flux,local")
    parser.add_argument("--aspect-ratios", default="Portrait,2KPortrait",
                        help="comma-separated aspect ratios per prompt")
    parser.add_argument("--out", required=True, type=Path,
                        help="output directory for images + index.html")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)

    prompts = _load_prompts(args.prompts)
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    ratios = [r.strip() for r in args.aspect_ratios.split(",") if r.strip()]

    results: list[dict] = []
    totals: dict[str, dict] = {p: {"count": 0, "elapsed_s": 0.0, "cost_usd": 0.0} for p in providers}

    for entry in prompts:
        slug = entry["slug"]
        prompt = entry["prompt"]
        for ratio in ratios:
            for provider in providers:
                print(f"  {provider} × {slug} × {ratio} ...", flush=True)
                img, elapsed, err = _generate(provider, prompt, ratio)
                row = {
                    "slug": slug,
                    "category": entry.get("category", ""),
                    "aspect_ratio": ratio,
                    "provider": provider,
                    "elapsed": elapsed,
                    "cost": _estimate_cost(provider, ratio),
                    "error": err,
                }
                if img is not None:
                    fname = f"{provider}__{_safe_filename(slug)}__{_safe_filename(ratio)}.webp"
                    (args.out / fname).write_bytes(img)
                    row["relpath"] = fname
                results.append(row)
                totals[provider]["count"] += 1
                totals[provider]["elapsed_s"] += elapsed
                totals[provider]["cost_usd"] += row["cost"] if img is not None else 0.0

    (args.out / "summary.json").write_text(
        json.dumps({"results": results, "totals": totals}, indent=2),
        encoding="utf-8",
    )
    _write_html(args.out, results, providers)
    print(f"Wrote {args.out / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Smoke-run with the mock provider**

```bash
python scripts/image_provider_eval.py \
  --prompts scripts/_eval_prompts.json \
  --providers mock \
  --aspect-ratios Portrait,2KPortrait \
  --out /tmp/eval-smoke/
```

Expected: writes `/tmp/eval-smoke/index.html`, `/tmp/eval-smoke/summary.json`, and 20 webp files. Open the HTML to eyeball.

- [ ] **Step 4: Cleanup smoke output and commit**

```bash
rm -rf /tmp/eval-smoke/
git add scripts/image_provider_eval.py
git commit -m "feat(scripts): image_provider_eval.py — cross-provider HTML gallery"
```

---

## Task 15: FAL_KEY-gated integration test

**Files:**
- Create: `tests/integration/test_integration_flux.py`

One integration test that hits fal.ai if `FAL_KEY` is in `.testenv`; skipped otherwise. CI runners don't have the key, so this stays out of the green-path gate.

- [ ] **Step 1: Implement**

Create `tests/integration/test_integration_flux.py`:

```python
"""Integration test for FluxAIModel.generate_image.

Gated on FAL_KEY being present in the environment (tests/.testenv loads
this; CI runners don't have it). Generates one small image and asserts
non-empty bytes — does NOT assert on visual content.

Marked `integration` so it's excluded from the default `pytest` run
(testpaths = ["tests/unit"]) and only fires under `make test-int`."""

import os

import pytest

from autonomous.ai.models.flux import FluxAIModel


pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not os.environ.get("FAL_KEY", "").strip(),
    reason="FAL_KEY not set — skipping FLUX integration test",
)
def test_generate_image_returns_bytes():
    flux = FluxAIModel.__new__(FluxAIModel)
    img = FluxAIModel.generate_image(
        flux,
        "a single red apple on a wooden table, soft warm light",
        aspect_ratio="Portrait",
    )
    assert isinstance(img, (bytes, bytearray))
    assert len(img) > 1024   # not an empty/error response
```

- [ ] **Step 2: Verify it's properly skipped when FAL_KEY is absent**

Run: `unset FAL_KEY; pytest tests/integration/test_integration_flux.py -v -m integration`
Expected: 1 skipped (with the reason message)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_integration_flux.py
git commit -m "test(int): FluxAIModel integration test gated on FAL_KEY"
```

---

## Task 16: `MIGRATIONS.md` entry

**Files:**
- Modify: `MIGRATIONS.md`

Document the new public API surface per the project convention ("Consumer-visible changes ship in MIGRATIONS.md").

- [ ] **Step 1: Write the entry**

Read the top of `MIGRATIONS.md` to see the current top-most-recent entry number, then prepend a new entry under that pattern. Append at the top, immediately after the file's preamble. Example shape:

```markdown
## Item N — Image-gen FLUX provider + routing layer (2026-06-02)

### What changed

- New provider `FluxAIModel` under `autonomous.ai.models.flux`. Registered
  in `BaseAgent.MODEL_REGISTRY` as `"flux"`. Targets fal.ai's
  `fal-ai/flux-pro/v1.1-ultra` endpoint.
- New env var `IMAGE_PROVIDER_ROUTING` (default off). When set to a
  truthy value (`1`/`true`/`yes`), `ImageAgent` overrides `self.provider`
  on dispatch: high-tier calls (`4K`, `4KPortrait`, `Map`) go to
  `gemini`; everything else goes to `flux`.
- New env var `FAL_KEY` (required when FLUX is dispatched). Module
  imports without it; the first dispatch raises `RuntimeError`.
- New env vars (defaults shown): `FLUX_IMAGE_MODEL=fal-ai/flux-pro/v1.1-ultra`,
  `FLUX_URL_BASE=https://fal.run`, `FLUX_TIMEOUT_S=120`,
  `FLUX_MAX_ATTEMPTS=3`, `FLUX_RETRY_SLEEP=1.0`.
- New `ImageAgent.fallback_provider` instance attribute (default `None`).
- New `ImageAgent.generate(..., fallback_provider, route)` kwargs.
  `fallback_provider` defaults to a sentinel; pass `None` to disable
  fallback for the call, a provider string to override the instance
  default. `route=False` bypasses the routing layer for that call.
- Same new kwargs on `ImageAgent.upscale()`.
- New unconditional job_meta keys written by `generate`/`upscale`:
  `effective_provider`, `cost_estimate_usd`, and (on fallback)
  `provider_fallback_used`, `fallback_succeeded`.
- **Fix:** the existing hybrid-upscale gate (`IMAGE_HYBRID_UPSCALE=1`)
  now checks the *effective* (routed) provider instead of `self.provider`.
  Calls that route from gemini to flux no longer double-process through
  the local upscaler.

### Migration

No source change required for existing consumers. With
`IMAGE_PROVIDER_ROUTING` unset, behavior is identical to pre-change.

To opt in:
1. `export FAL_KEY=<your fal.ai key>` in the deployment env.
2. Run `python scripts/image_provider_eval.py --prompts
   scripts/_eval_prompts.json --providers gemini,flux,local --out
   eval-YYYY-MM-DD/` and review `index.html` for creative-quality parity.
3. `export IMAGE_PROVIDER_ROUTING=1`.

Roll back by `unset IMAGE_PROVIDER_ROUTING`. Instant; no data migration.

### Cost-estimate caveat

`cost_estimate_usd` job_meta is from a static table —
useful for trend/comparison but **not audit-grade**. Replacing it with
parsed billing data is a necessary follow-up
(spec: `docs/superpowers/specs/2026-06-02-image-gen-cost-design.md`).
```

(Adjust "Item N" to the next sequential number used in your `MIGRATIONS.md`.)

- [ ] **Step 2: Commit**

```bash
git add MIGRATIONS.md
git commit -m "docs(migrations): FluxAIModel + IMAGE_PROVIDER_ROUTING + ImageAgent kwargs"
```

---

## Task 17: Full-suite sanity + push

**Files:** none

- [ ] **Step 1: Run the full unit suite**

Run: `pytest tests/unit -q --no-cov-on-fail`
Expected: all green; new test files contribute ~40 new tests.

- [ ] **Step 2: Run flake8 syntax-only gate (matches CI)**

Run: `flake8 . --select=E9,F63,F7,F82`
Expected: clean.

- [ ] **Step 3: Build + twine check (matches release.sh dry-run)**

Run: `python -m build && python -m twine check dist/*`
Expected: PASSED for both `tar.gz` and `whl`.

- [ ] **Step 4: Push the branch and open the PR per dev-agent doctrine**

Per `.claude/commands/dev-agent.md`, the iteration ends with a single `dev → test` PR. Push the working branch and create the PR via `gh`:

```bash
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git push -u origin "$BRANCH"

gh pr create --repo Sallenmoore/autonomous \
  --base test --head "$BRANCH" \
  --title "iter/2026-06-02: image-gen cost reduction via FLUX routing" \
  --body "$(cat <<'EOF'
## Summary

Adds a third image provider (FLUX.1 [pro] via fal.ai), an opt-in
aspect-ratio-tier routing layer in ImageAgent, per-call cost-estimate
telemetry, opt-in fallback_provider kwarg, per-call route=False bypass,
and an HTML eval harness for human quality validation before flipping
the routing switch.

Routing default is **off** (set IMAGE_PROVIDER_ROUTING=1 to opt in).
With routing off, behavior is identical to pre-change.

Spec: docs/superpowers/specs/2026-06-02-image-gen-cost-design.md

## Test plan

- [x] tests/unit/test_unit_flux.py — 20+ tests cover happy path,
      retry, error paths, files= NotImplementedError, missing FAL_KEY
- [x] tests/unit/test_unit_imageagent_routing.py — 20+ tests cover
      routing matrix, fallback resolution, route=False, cost telemetry,
      hybrid-upscale effective-provider fix
- [x] tests/unit/test_unit_mock_model_new_kwargs.py — mock provider
      absorbs new kwargs without TypeError
- [x] tests/unit/test_unit_baseagent_flux_registry.py — flux is in
      MODEL_REGISTRY
- [x] tests/integration/test_integration_flux.py — gated on FAL_KEY,
      generates one real image (skipped on CI)
- [x] Full unit suite green after this PR
- [x] Smoke-ran scripts/image_provider_eval.py against mock provider
- [ ] Operator: run the eval harness against real providers before
      enabling IMAGE_PROVIDER_ROUTING in production

Necessary follow-ups (separate iterations):
- FLUX redux/kontext for files= img2img support
- Dynamic cost estimate parsed from billing data (replaces static table)
- Category-based routing (generate(category=...)) if aspect-ratio-tier
  proves too blunt
EOF
)"
```

- [ ] **Step 2: Watch CI**

Per the dev-agent doctrine (step 8):

```bash
PR=<your-pr-number>
gh pr checks "$PR" --repo Sallenmoore/autonomous --watch
gh pr checks "$PR" --repo Sallenmoore/autonomous
```

Until green or 3 fix-up cycles still red.

---

## Necessary follow-ups (NOT in this plan)

Each gets its own brainstorm → spec → plan cycle later:

1. **FLUX `redux` / `kontext` endpoints for img2img** — replace the v1
   `NotImplementedError` on `files=` with real img2img dispatch via the
   appropriate fal.ai endpoint.
2. **Dynamic cost estimate from billing data** — replace the static
   `_COST_USD` table with a parser for Google's billing export. Promotes
   `cost_estimate_usd` job_meta from estimate to actual.
3. **Routing by call category** — if aspect-ratio-tier routing turns
   out too blunt for a class of calls, add `generate(category=...)`
   and remap the routing table to category-aware decisions.

---

## Self-Review

**Spec coverage:**
- Architecture (FluxAIModel + routing) → Tasks 3, 4, 7
- Components (FluxAIModel, ImageAgent additions, eval harness) → Tasks 4–6, 8–12, 13, 14
- Data flow (routing → dispatch → cache key) → Tasks 9, 10, 12
- Error handling (retry exhaustion, fallback, etc.) → Tasks 6, 10
- Testing strategy (hermetic unit, integration gated on FAL_KEY) → Tasks 1, 2, 4, 5, 6, 8–12, 15
- Rollout plan (off-by-default; eval harness as the gate) → Task 14, Task 16 (MIGRATIONS)
- Necessary follow-ups → "Necessary follow-ups" section above

**Placeholder scan:** None. Every step contains the actual file paths, code, and commands.

**Type consistency:**
- `_route_provider(aspect_ratio)` signature consistent across Task 3 (defined) and Task 9, 12 (called).
- `_estimate_cost_usd(provider, size)` consistent across Task 2 (defined) and Task 9, 12 (called).
- `_resolve_fallback(fallback_provider)` consistent across Task 8 (defined) and Task 10, 12 (called).
- `_aspect_to_size_token(aspect_ratio)` defined and referenced in Task 9; used in Tasks 12 and 14.
- `_UNSET` sentinel defined in Task 8; referenced in Tasks 9, 10, 12.
- Job_meta key names — `cost_estimate_usd`, `effective_provider`, `provider_fallback_used`, `fallback_succeeded`, `upscale_supported` — consistent across the spec, Tasks 9–12, and Task 16.
