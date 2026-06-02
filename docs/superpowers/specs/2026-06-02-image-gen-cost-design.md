# Image-gen cost reduction via FLUX routing

**Status:** Approved, awaiting implementation plan
**Date:** 2026-06-02
**Owner:** samoore
**Affected packages:** `autonomous.ai.imageagent`, `autonomous.ai.models` (new `flux` adapter), `autonomous.ai.image_cache` (unchanged), `scripts/image_provider_eval.py` (new)

## Context

Image generation through `GeminiAIModel` is the dominant per-call cost in the `autonomous` library's AI surface. As of 2026-06-02 the existing cost levers are all shipped:

- **Disk cache** (`autonomous.ai.image_cache`) — opt-in content-addressed cache via `AUTONOMOUS_IMAGE_CACHE_DIR`
- **Quality dial** in `ImageAgent` (`_QUALITY_ASPECT_MAP`) — `draft` / `standard` / `high`
- **Hybrid upscale** (`IMAGE_HYBRID_UPSCALE=1`) — Gemini base + local upscale, avoiding Imagen's 4K tier
- **Smaller defaults** (commit `60bac37`) — `Portrait` dropped 4× (2K → 0.5K), `Landscape` dropped 2× (2K → 1K), fallback shifted to `3:4 / 0.5K`

Per-call Gemini cost is bounded by the multimodal output-token model: roughly $0.012 (0.5K) / $0.039 (1K) / $0.078 (2K) / $0.155 (4K) per image at ~$30/1M output tokens.

The `LocalAIModel` provider hits a self-hosted `MEDIA_API_BASE_URL` service at near-zero marginal cost, but **its creative output does not match Imagen on prompt adherence** for storyteller's call mix. That is why storyteller has been routing to Gemini despite `ImageAgent.provider`'s `"local"` default.

## Goal

Cut average per-image cost without regressing creative quality (prompt adherence and aesthetic — not technical resolution).

## Non-goals

- Changing storyteller's existing call sites in this iteration. The autonomous-library surface changes; storyteller picks up the change when the operator opts in.
- Replacing Gemini as a provider option. Gemini remains available for high-tier calls and as a per-call escalation target.
- Image-to-image (`files=`) support on the new provider. v1 is text-to-image only; flagged as a necessary follow-up below.
- Automated quality regression detection. Human review of the eval harness output is the quality gate.

## Architecture

A new `FluxAIModel(AutoModel)` adapter joins `GeminiAIModel` / `LocalAIModel` / `OpenAIClient` / `MockAIModel` in `MODEL_REGISTRY` under the key `"flux"`. It calls fal.ai's `fal-ai/flux-pro/v1.1-ultra` endpoint via plain `requests` (no new dependency), authenticated via `FAL_KEY`.

A routing layer in `ImageAgent` decides at dispatch time which provider gets the call when `IMAGE_PROVIDER_ROUTING=1` is set. Routing table:

| Aspect ratio (after quality dial) | Provider |
|---|---|
| `Portrait`, `Landscape`, `1:1`, `3:4`, `4:3`, `9:16`, `16:9` | `flux` |
| `2K`, `2KPortrait` | `flux` |
| `4K`, `4KPortrait`, `Map` | `gemini` |

`ImageAgent.provider` keeps its semantic meaning (the *requested* provider). The routing layer overrides it on dispatch only when routing is enabled. With routing off, behavior is identical to today.

Cost telemetry is unconditional: every `ImageAgent.generate()` and `upscale()` call writes a `cost_estimate_usd` value to job_meta from a static per-provider, per-size price table. This produces baseline measurements even before routing is flipped on.

Two retry-on-failure ergonomics ship in v1:

- **`fallback_provider` kwarg** (and matching instance default `ImageAgent.fallback_provider`) — opt-in per-call auto-fallback. After the routed provider exhausts `autonomous.ai.retry.retry`'s bounded retries, fall back exactly once on the named provider. Logs loudly; marks `job_meta.provider_fallback_used = True`; cost telemetry records the actual-cost provider.
- **`route=False` kwarg** — per-call routing bypass. Caller declares "use `self.provider` regardless of routing rules." Different use case from fallback (explicit, not reactive).

## Components and interfaces

### `src/autonomous/ai/models/flux.py` (new)

```python
class FluxAIModel(AutoModel):
    _client = None

    _image_model = os.environ.get("FLUX_IMAGE_MODEL", "fal-ai/flux-pro/v1.1-ultra")
    _image_url = "https://fal.run"
    _media_timeout = int(os.environ.get("FLUX_TIMEOUT_S", "120"))

    def _get_image_config(self, aspect_ratio_input: str) -> tuple[str, str]:
        """Map autonomous's aspect-ratio vocabulary to fal.ai's
        (aspect_ratio, image_size) pair. Same shape as gemini's helper."""

    def generate_image(
        self,
        prompt: str,
        negative_prompt: str = "",
        files=None,
        aspect_ratio: str = "2KPortrait",
        style="",
    ) -> bytes:
        """Text-to-image. Raises NotImplementedError if files is non-empty
        (v1 scope). Honors negative_prompt (unlike Gemini)."""

    def upscale_image(
        self,
        prompt: str,
        image_content: bytes = None,
        aspect_ratio: str = "2KPortrait",
        style=None,
    ) -> bytes:
        """No dedicated FLUX upscaler. Returns image_content unchanged
        and logs — identical shape to GeminiAIModel.upscale_image."""
```

- **Backend:** plain `requests` (already required), no `fal_client` dependency.
- **Auth:** `Authorization: Key $FAL_KEY` header. Module imports cleanly without the key set; first dispatch raises `RuntimeError` with a pointer to the env var.
- **Aspect ratio mapping:** fal.ai accepts `aspect_ratio` from `{"1:1", "16:9", "9:16", "4:3", "3:4", "16:10", "10:16", "21:9", "9:21"}`. Map autonomous's `Portrait/Landscape/2K/2KPortrait/4K/4KPortrait/Map` keys into this vocabulary in `_get_image_config`, same shape as `GeminiAIModel._get_image_config`.
- **Retry:** route the POST through `autonomous.ai.retry.retry` for bounded HTTP retries (matches the convention noted in CLAUDE.md).

### `src/autonomous/ai/imageagent.py` (additions)

```python
def _routing_enabled() -> bool:
    return os.environ.get("IMAGE_PROVIDER_ROUTING", "").lower() in {"1", "true", "yes"}


# Static cost table — estimates, not audit-grade.
_COST_USD = {
    ("gemini", "0.5K"): 0.012,
    ("gemini", "1K"):   0.039,
    ("gemini", "2K"):   0.078,
    ("gemini", "4K"):   0.155,
    ("flux",   "*"):    0.040,
    ("local",  "*"):    0.000,
}


class ImageAgent(BaseAgent):
    # ... existing attrs ...
    fallback_provider = StringAttr(default=None)

    def _route_provider(self, aspect_ratio: str) -> str:
        """Return the actual provider for this call after routing rules."""
        if not _routing_enabled():
            return self.provider
        if aspect_ratio in {"4K", "4KPortrait", "Map"}:
            return "gemini"
        return "flux"

    def _estimate_cost_usd(self, provider: str, aspect_ratio: str) -> float:
        """Look up static cost estimate; fall through to provider wildcard."""

    def generate(
        self, prompt, negative_prompt="...", files=None,
        aspect_ratio="2KPortrait", style=None, temperature=None,
        quality="standard",
        fallback_provider=None,   # NEW: override instance default; None means "use instance default"
        route=True,                # NEW: False skips routing layer for this call
    ): ...

    def upscale(
        self, prompt, image_content=None, aspect_ratio="2KPortrait",
        style=None, quality="standard",
        fallback_provider=None,   # NEW
        route=True,                # NEW
    ): ...
```

Fallback-provider resolution uses a sentinel default to distinguish "kwarg not passed" from "kwarg explicitly disabled":

```python
_UNSET = object()

def generate(self, ..., fallback_provider=_UNSET, route=True):
    if fallback_provider is _UNSET:
        effective_fallback = self.fallback_provider   # inherit instance default
    else:
        effective_fallback = fallback_provider        # explicit value (None disables)
```

- Caller passes nothing → inherits `self.fallback_provider`.
- Caller passes `None` → disables fallback for this call (overrides instance default).
- Caller passes `"gemini"` (or any provider string) → uses that provider as fallback.

**Hybrid-upscale interaction:** the existing `IMAGE_HYBRID_UPSCALE` gate (`imageagent.py:113`) currently checks `self.provider == "gemini"`. Update to check the **effective** (routed) provider so FLUX-generated images do not get double-processed through the local upscaler.

### `scripts/image_provider_eval.py` (new)

CLI:

```
python scripts/image_provider_eval.py \
  --prompts scripts/_eval_prompts.json \
  --providers gemini,flux,local \
  --aspect-ratios Portrait,Landscape,2K,2KPortrait \
  --out eval-2026-06-02/
```

- Reads a JSON prompt corpus (ship `scripts/_eval_prompts.json` with 8–10 hand-curated storyteller-shaped prompts covering character / scene / map / hero shapes).
- For each (prompt, provider, aspect_ratio) tuple: generates an image, records timing + estimated cost.
- Outputs:
  - `<out>/<provider>/<prompt-slug>--<aspect>.webp` — image files
  - `<out>/index.html` — CSS grid (rows = prompts × aspect, cols = providers) for side-by-side visual comparison
  - `<out>/summary.json` — per-provider totals (count, time, cost estimate)
- **Cache-aware** — uses `image_cache.cache_key` so re-running after a single prompt edit only re-bills for the edited prompt.

The harness is the quality gate. Human review of the HTML grid is the validation step before flipping `IMAGE_PROVIDER_ROUTING=1`.

### `MockAIModel` (`src/autonomous/ai/models/mock_model.py`)

Update `MockAIModel.generate_image` signature to accept the new kwargs (`fallback_provider`, `route`) without `TypeError`. Behavior is unchanged: returns deterministic mock bytes for offline tests.

## Data flow

Worked example — `ImageAgent(provider="gemini").generate(prompt, aspect_ratio="Portrait", quality="standard")` with routing on, cache enabled, no fallback:

```
storyteller → ImageAgent.generate(...)
  ├─ _resolve_aspect_ratio("Portrait", "standard") → "Portrait"
  ├─ _route_provider("Portrait")                   → "flux"
  ├─ image_cache.cache_key(provider="flux", aspect_ratio="Portrait", ...)
  ├─ image_cache.get(key) → bytes? → return            # cache HIT short-circuits
  ├─ MODEL_REGISTRY["flux"](...).generate_image(prompt, aspect_ratio="Portrait", ...)
  │     ├─ _get_image_config("Portrait")           → ("3:4", image_size)
  │     ├─ retry.retry(requests.post, "https://fal.run/fal-ai/flux-pro/v1.1-ultra", ...)
  │     ├─ extract image URL from response, GET URL → bytes
  │     └─ return bytes
  ├─ job_meta:
  │     effective_provider = "flux"
  │     cost_estimate_usd  = 0.040
  │     provider_fallback_used = False
  ├─ image_cache.put(key, bytes)
  └─ return bytes
```

Worked example — same call with `fallback_provider="gemini"` and FLUX fails:

```
storyteller → ImageAgent.generate(..., fallback_provider="gemini")
  ├─ _route_provider("Portrait") → "flux"
  ├─ MODEL_REGISTRY["flux"](...).generate_image(...)
  │     ├─ retry.retry(...) raises requests.RequestException after N retries
  ├─ log("Image gen fell back from flux to gemini: <exc>", _print=True)
  ├─ MODEL_REGISTRY["gemini"](...).generate_image(prompt, aspect_ratio="Portrait", ...)
  │     └─ return bytes
  ├─ job_meta:
  │     effective_provider     = "gemini"
  │     cost_estimate_usd      = 0.012     # Portrait at 0.5K
  │     provider_fallback_used = True
  ├─ image_cache.put(key_for_gemini, bytes)    # cache key reflects actual provider
  └─ return bytes
```

**Cache key semantics on fallback:** the cache key is computed from the *effective* (actual) provider that produced the bytes. On a fallback, results are stored under the fallback provider's key — *not* under the originally-routed provider's key. Rationale: storing a Gemini image under a FLUX key would corrupt later direct-FLUX lookups (e.g., from the eval harness) with cross-provider output. Cost consequence: while FLUX is failing, every routed-to-FLUX request misses the FLUX cache, falls back to Gemini, and bills the Gemini call — exactly the behavior the cost-amplification warning describes. Operator signal: many `provider_fallback_used=True` job_meta entries → FLUX is degraded, address the underlying outage.

## Error handling

| Failure | Behavior |
|---|---|
| FLUX 4xx (auth, bad request) | Raise after retry. Same shape as Gemini's `genai.errors.APIError`. |
| FLUX 5xx / network timeout | `retry.retry` retries with backoff; after exhaustion, raise — unless `fallback_provider` is set, in which case fall back once. |
| FLUX returns 200 but no image URL | Raise `ValueError`. |
| FLUX image-URL fetch fails | Raise `OSError`. |
| Missing `FAL_KEY` when FLUX is dispatched | Raise `RuntimeError` at call time with env-var pointer. Not at import time. |
| `files=` passed to FLUX path | Raise `NotImplementedError` with a message recommending `provider="gemini"` or `route=False` for that call. |
| `FluxAIModel` import fails (e.g., module bug) | Surface as a one-time warning at first dispatch; fall back to `self.provider` for routing. Prevents an import bug from bricking image gen entirely. |
| `fallback_provider` itself fails | Propagate the fallback's exception. No second-level fallback. Job_meta records `provider_fallback_used=True, fallback_succeeded=False`. |

**Auto-fallback is opt-in.** With `fallback_provider=None` (default), FLUX failure raises. This avoids silent cost amplification: a FLUX outage with auto-fallback would 5× the bill on every retry without the operator's consent.

## Testing strategy

### Hermetic unit tests (`tests/unit/`)

| Test target | Shape |
|---|---|
| `FluxAIModel._get_image_config` | Parametrized; every input key → expected (aspect_ratio, image_size). |
| `FluxAIModel.generate_image` happy path | Mock `requests.post` + URL fetch. Assert payload shape, auth header, byte return. |
| `FluxAIModel.generate_image` with `files=` | Assert raises `NotImplementedError`. |
| `FluxAIModel.generate_image` 5xx with retry | Mock 503 then 200; assert N≤retry-cap, final success. |
| `FluxAIModel.generate_image` empty body | Mock 200 + no image URL; assert `ValueError` shape matches gemini's. |
| `FluxAIModel` import without `FAL_KEY` | Module imports clean; first dispatch raises `RuntimeError`. |
| `ImageAgent._route_provider` matrix | Every (aspect_ratio × routing-on/off × self.provider) combination resolves correctly. |
| `ImageAgent.generate` with fallback_provider, FLUX raises | Mock both providers; assert gemini called once after retry exhaustion, job_meta breadcrumbs correct. |
| `ImageAgent.generate` with `route=False` | Routing on but `route=False`; `self.provider` honored regardless of aspect_ratio. |
| `ImageAgent.generate` cost_estimate_usd | Every (provider, size) tuple writes the table value to job_meta. |
| Cache + routing interaction | Cache key reflects effective (routed) provider, not requested provider. |
| Hybrid-upscale gate uses effective provider | Set routing on, hybrid on, `self.provider="gemini"`; aspect_ratio routes to flux; assert local upscaler is NOT invoked. |
| `MockAIModel.generate_image` accepts new kwargs | No `TypeError` when `fallback_provider`/`route` are passed. |

### Integration tests (`tests/integration/`)

One integration test, gated on `FAL_KEY` in `.testenv`. Generates a single 0.5K image and asserts non-empty bytes. Skipped silently when the key is absent — CI runners stay green; local storyteller stack picks it up.

### No perf tests

Image generation is already in the "slow, opt-in" tier. Perf benchmarks would be flaky and provide little signal.

### Documentation

- `MIGRATIONS.md` entry: new `FluxAIModel`, `IMAGE_PROVIDER_ROUTING` env var, `FAL_KEY` env var, new `fallback_provider` / `route` kwargs on `ImageAgent.generate`/`upscale`, unconditional `cost_estimate_usd` job_meta.
- `pyproject.toml` `[ai]` extra: unchanged. No new dependency (FLUX uses `requests`).

## Rollout plan

Each step is reversible at the env-var level. No data migration. No code change required to mitigate a quality regression.

1. **Land the library change.** Routing default OFF. `cost_estimate_usd` writes start showing in job_meta — baseline measurement for current Gemini traffic.
2. **Operator-side: set `FAL_KEY`, leave routing off.** No traffic to FLUX yet.
3. **Run the eval harness** locally:
   ```
   python scripts/image_provider_eval.py --prompts scripts/_eval_prompts.json \
     --providers gemini,flux,local --out eval-<date>/
   ```
   Open `index.html`; eyeball side-by-sides on storyteller-shaped prompts. **Human review is the quality gate.**
4. **If quality validates**, flip `IMAGE_PROVIDER_ROUTING=1` on the storyteller deployment. Watch `job_meta.cost_estimate_usd` for a week.
5. **If a quality regression surfaces** in a specific call shape, the operator mitigates per-call (`route=False` at the storyteller call site) or per-instance (`fallback_provider="gemini"`). No library change required.
6. **Rollback** = `unset IMAGE_PROVIDER_ROUTING`. Instant. Cost telemetry continues working.

## Necessary follow-ups

Not in scope for v1, but required to fully realize the design's intent. Each gets its own iteration:

1. **FLUX `redux` / `kontext` endpoints for img2img (`files=` support).** Storyteller's character-reference and compositing flows currently pass `files=`; in v1 these raise `NotImplementedError` on the FLUX path, so they stay on Gemini. Adding the img2img endpoint(s) is the path to routing those calls too.
2. **Dynamic cost estimate from real Gemini billing data.** v1 uses a static `_COST_USD` table — useful for baseline-and-trend but not audit-grade. Replace the table with a parser for actual Google billing exports (per-call breakdown) so `cost_estimate_usd` becomes `cost_actual_usd`.
3. **Routing by call category** (`generate(category="character"|"scene"|"map"|"hero")`). If aspect-ratio-tier routing turns out too blunt — i.e., one of the size classes mixes high-stakes and low-stakes calls — promote routing to category-aware. Caller declares intent; routing maps category → provider.

## Optional future work

Lower-priority extensions, not committed:

- `fallback_max_cost_usd_per_day` budget guard on the ImageAgent — prevents a FLUX outage from running up a 10× bill overnight via auto-fallback. Real FLUX uptime data needed first.
- Additional alternative providers (Recraft v3, OpenAI gpt-image-1, Ideogram v3) as further routing tiers. Only worth doing if the eval shows a category FLUX doesn't cover.
- Per-call latency budget — `timeout_s` kwarg that overrides `FLUX_TIMEOUT_S` for the call.
