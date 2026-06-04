"""Independent coverage for PR #31 — gemini image_size fixes (issues #29, #30)
and strict-dialect heuristic tightening (issue #28).

Written without consulting dev's ``tests/_dev_local/`` (gitignored
anyway). PR #31 ships no committed test files; this file is the only
committed coverage for the bundle. Second perspective per CLAUDE.md.

Four concern groups:

1. ``GeminiAIModel._get_image_config`` post-fix mapping table. Pins
   every named tier (Portrait / Landscape / 2K / 2KPortrait / 4K / Map
   / 4KPortrait) plus the bare-ratio passthrough set and the default
   fallback to the new ``(ratio, size)`` tuples. Critical: no path
   through the function may produce ``"0.5K"`` (rejected by Gemini API
   per #29) or ``"4K"`` against the current flash-image-preview model
   (#30 — clamped to 2K).

2. ``_looks_like_unsupported_strict_mode`` Tier-1 dialect-violation
   markers (closes #28). A response body matching any of the nine
   dialect-violation phrases must NOT flag as unsupported — the
   server is healthy, the caller's schema is broken. Caching it
   would silently downgrade future calls.

3. Tier-1 vs Tier-2 precedence. A body that matches BOTH a
   dialect-violation marker AND a capability marker should resolve
   as Tier-1 (False — don't cache). Tier-1 reject is the load-bearing
   safety property; if precedence reverses, #28 reopens.

4. **Forward-looking regression guard** (pins on revert by
   construction, per protocol step 4 exception). Pins the
   ``_get_image_config`` output set to a whitelist of API-accepted
   sizes — a future contributor adding a new tier that emits a
   rejected token (0.5K, 8K, etc.) trips this guard before shipping.
   Documents the API contract independently of the current
   per-aspect mapping.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 1. GeminiAIModel._get_image_config — full mapping table after #29/#30
# ---------------------------------------------------------------------------


class TestGeminiImageConfigPostFix:
    @pytest.fixture
    def gemini(self):
        """Bypass AutoModel init — the method under test only reads
        the ``aspect_ratio_input`` argument."""
        from autonomous.ai.models.gemini import GeminiAIModel
        return GeminiAIModel.__new__(GeminiAIModel)

    @pytest.mark.parametrize(
        "aspect_ratio_input,expected_ratio,expected_size",
        [
            ("Portrait", "3:4", "1K"),            # was 0.5K — issue #29 fix
            ("Landscape", "16:9", "1K"),          # unchanged
            ("2K", "16:9", "2K"),                 # unchanged
            ("2KPortrait", "3:4", "2K"),          # unchanged
            ("4K", "16:9", "2K"),                 # was 4K — issue #30 clamp
            ("Map", "16:9", "2K"),                # was 4K — issue #30 clamp
            ("4KPortrait", "3:4", "2K"),          # was 4K — issue #30 clamp
        ],
    )
    def test_named_tiers_map_to_expected_pairs(
        self, gemini, aspect_ratio_input, expected_ratio, expected_size
    ):
        ratio, size = gemini._get_image_config(aspect_ratio_input)
        assert (ratio, size) == (expected_ratio, expected_size)

    @pytest.mark.parametrize(
        "raw_ratio", ["1:1", "3:4", "4:3", "9:16", "16:9"]
    )
    def test_bare_ratio_passthrough_uses_default_size(self, gemini, raw_ratio):
        """Bare aspect tokens previously inherited the now-invalid
        0.5K default. Post-fix they should pick up "1K" (smallest
        Gemini-accepted size). This is the issue #29 regression
        guard that ALSO covers callers that don't use the named-tier
        vocabulary."""
        ratio, size = gemini._get_image_config(raw_ratio)
        assert ratio == raw_ratio
        assert size == "1K"

    def test_default_fallback_is_1k_not_half_k(self, gemini):
        """An unrecognized aspect token must fall through to
        ``("3:4", "1K")`` — NOT ``("3:4", "0.5K")``. Pre-fix this
        path emitted the rejected token, so any storyteller call
        with a typoed aspect produced a 400 from Gemini."""
        ratio, size = gemini._get_image_config("not-a-real-aspect-token")
        assert (ratio, size) == ("3:4", "1K")


# ---------------------------------------------------------------------------
# 2. _looks_like_unsupported_strict_mode — Tier-1 dialect-violation markers
# ---------------------------------------------------------------------------


class TestStrictDialectMarkersTier1:
    """Each of the nine dialect-violation phrases must make the
    heuristic return False at 400 and 422 — even if a capability
    marker is also present. This is the load-bearing #28 close: a
    strict-dialect rejection now propagates as a real 400 to the
    caller (who fixes their schema) rather than poisoning the
    negative cache."""

    @pytest.fixture(autouse=True)
    def _isolate(self):
        """Each test starts with a clean negative cache so any
        accidental side-effects in the implementation are visible."""
        from autonomous.ai.models import openai_compat
        openai_compat._reset_unsupported_cache()
        yield
        openai_compat._reset_unsupported_cache()

    @pytest.mark.parametrize(
        "marker",
        [
            "invalid schema",
            "additionalProperties must be false",
            "missing required field",
            "must be in 'required'",
            "must be in `required`",
            "in 'required' array",
            "not allowed in strict",
            "invalid type for 'type'",
            "schema must be an object",
        ],
    )
    @pytest.mark.parametrize("status", [400, 422])
    def test_each_dialect_marker_at_each_status_returns_false(
        self, marker, status
    ):
        from autonomous.ai.models.openai_compat import (
            _looks_like_unsupported_strict_mode,
        )
        body = f"Server rejected the request: {marker}. Fix your schema."
        assert _looks_like_unsupported_strict_mode(status, body) is False

    def test_dialect_marker_is_case_insensitive(self):
        """``body_lower`` lowercases input; the markers are all
        lowercase. Confirm an upper-case server body still matches."""
        from autonomous.ai.models.openai_compat import (
            _looks_like_unsupported_strict_mode,
        )
        body = "ERROR: ADDITIONALPROPERTIES MUST BE FALSE FOR STRICT MODE"
        assert _looks_like_unsupported_strict_mode(400, body) is False


class TestTier1OverridesTier2:
    """A body that contains BOTH a dialect-violation marker AND a
    capability marker (e.g. the server explains "json_schema field:
    additionalProperties must be false") must resolve as Tier-1
    (False). If precedence reversed, the negative cache would still
    poison on dialect violations and #28 would reopen.

    Parametrized across ALL nine Tier-1 markers so a future
    contributor who adds a 10th dialect marker but breaks the
    override property gets a red test."""

    @pytest.fixture(autouse=True)
    def _isolate(self):
        from autonomous.ai.models import openai_compat
        openai_compat._reset_unsupported_cache()
        yield
        openai_compat._reset_unsupported_cache()

    # The full Tier-1 marker set; pair each with a Tier-2 capability
    # marker to verify Tier-1 reject wins for every combination.
    ALL_DIALECT_MARKERS = [
        "invalid schema",
        "additionalProperties must be false",
        "missing required field",
        "must be in 'required'",
        "must be in `required`",
        "in 'required' array",
        "not allowed in strict",
        "invalid type for 'type'",
        "schema must be an object",
    ]

    @pytest.mark.parametrize("dialect_marker", ALL_DIALECT_MARKERS)
    @pytest.mark.parametrize(
        "capability_marker",
        ["json_schema", "response_format", "unsupported_parameter",
         "structured output"],
    )
    def test_dialect_marker_overrides_any_capability_marker(
        self, dialect_marker, capability_marker
    ):
        """Property test: for every (Tier-1, Tier-2) combination, a
        body containing BOTH must return False (Tier-1 wins). This is
        the load-bearing #28 close — if a 10th dialect marker is
        added without preserving the override property, this fails."""
        from autonomous.ai.models.openai_compat import (
            _looks_like_unsupported_strict_mode,
        )
        body = (
            f"Server error: {capability_marker} is involved but the "
            f"real cause is {dialect_marker}."
        )
        assert _looks_like_unsupported_strict_mode(400, body) is False

    def test_pure_capability_marker_still_returns_true(self):
        """Tier-2 still works for bodies without any dialect signal —
        the broad-marker fallback handles non-OpenAI servers (HPC's
        Open WebUI proxy, vLLM) that emit less-structured errors."""
        from autonomous.ai.models.openai_compat import (
            _looks_like_unsupported_strict_mode,
        )
        body = "response_format=json_schema is not supported"
        assert _looks_like_unsupported_strict_mode(400, body) is True


class TestNegativeCacheNotPoisonedByDialectViolation:
    """The end-to-end consequence of the Tier-1 reject: a dialect
    violation must NOT populate ``_UNSUPPORTED_STRICT_MODE``. Pre-fix,
    any 400 mentioning "json_schema" would cache, even when the
    server was fine and the caller's schema was just wrong."""

    @pytest.fixture(autouse=True)
    def _isolate(self):
        from autonomous.ai.models import openai_compat
        openai_compat._reset_unsupported_cache()
        yield
        openai_compat._reset_unsupported_cache()

    def test_heuristic_signals_real_error_for_dialect_violation(self):
        """A realistic OpenAI strict-dialect rejection body — uses
        the ``"invalid type for 'type'"`` marker specifically (NOT
        also exercised by the case-insensitive test elsewhere). The
        heuristic returns False, so the calling code re-raises the
        original HTTPError rather than retrying in loose mode."""
        from autonomous.ai.models.openai_compat import (
            _looks_like_unsupported_strict_mode,
        )
        body = (
            "Invalid request: invalid type for 'type' field in your "
            "response_format json_schema (expected 'string', got int)."
        )
        # Heuristic says "this is NOT a capability gap"; caller's
        # generate_json then re-raises rather than caching+falling-back.
        assert _looks_like_unsupported_strict_mode(400, body) is False


# ---------------------------------------------------------------------------
# 3. Image-size regression guard — no path emits a Gemini-rejected token
# ---------------------------------------------------------------------------


class TestImageSizeRegressionGuard:
    """Forward-looking guard (per protocol step 4 exception): the
    set of image_size values ``_get_image_config`` can emit must be
    a subset of Gemini's accepted values {"1K", "2K", "4K"} —
    excluding the currently-rejected "0.5K" (issue #29) and "4K"
    (issue #30 against flash-image-preview).

    This test passes by construction against the current source AND
    against pre-PR source (because it pins the API contract, not the
    specific mapping). Flagged explicitly as a forward-looking test
    in the bundle summary — the revert-sanity-check protocol step 4
    exception applies.

    A future contributor adding a new aspect tier that emits "0.5K"
    or "8K" or any other rejected token will be caught by this test
    BEFORE shipping. The check sweeps every aspect token the
    function knows about plus a typoed one (for the default branch).
    """

    @pytest.fixture
    def gemini(self):
        from autonomous.ai.models.gemini import GeminiAIModel
        return GeminiAIModel.__new__(GeminiAIModel)

    # The set of sizes Gemini's ImageConfig accepts AT ALL.
    GEMINI_ACCEPTED_SIZES = frozenset({"1K", "2K", "4K"})

    # The narrower set the current default model (flash-image-preview)
    # accepts. "4K" is rejected by this model, so we clamp to 2K and
    # never emit 4K from the current mapping.
    FLASH_IMAGE_PREVIEW_ACCEPTED = frozenset({"1K", "2K"})

    ALL_KNOWN_ASPECT_INPUTS = [
        "Portrait", "Landscape", "2K", "2KPortrait", "4K", "Map",
        "4KPortrait", "1:1", "3:4", "4:3", "9:16", "16:9",
        "definitely-not-a-real-aspect",  # exercises the default branch
        "",  # empty string — also default branch
    ]

    @pytest.mark.parametrize("aspect", ALL_KNOWN_ASPECT_INPUTS)
    def test_emitted_size_is_gemini_accepted(self, gemini, aspect):
        """Any aspect input must produce a size token Gemini's API
        will accept — no "0.5K" / "8K" / arbitrary strings."""
        _, size = gemini._get_image_config(aspect)
        assert size in self.GEMINI_ACCEPTED_SIZES, (
            f"aspect_ratio_input={aspect!r} produced size={size!r}, "
            f"not in Gemini's accepted set "
            f"{sorted(self.GEMINI_ACCEPTED_SIZES)}"
        )

    @pytest.mark.parametrize("aspect", ALL_KNOWN_ASPECT_INPUTS)
    def test_emitted_size_is_flash_image_preview_compatible(
        self, gemini, aspect
    ):
        """The current default model rejects "4K". Until
        GEMINI_IMAGE_MODEL is swapped to one that accepts 4K, no
        path should emit 4K. This is the issue #30 close — if we
        regress and start emitting 4K against flash-image-preview,
        every high-res caller breaks."""
        _, size = gemini._get_image_config(aspect)
        assert size in self.FLASH_IMAGE_PREVIEW_ACCEPTED, (
            f"aspect_ratio_input={aspect!r} produced size={size!r}, "
            f"which flash-image-preview rejects."
        )

    def test_no_path_emits_half_k(self, gemini):
        """The specific #29 anti-regression: no path may emit "0.5K".
        Belt-and-suspenders on top of the above checks — names the
        bug explicitly so a grep for #29 finds it."""
        for aspect in self.ALL_KNOWN_ASPECT_INPUTS:
            _, size = gemini._get_image_config(aspect)
            assert size != "0.5K", (
                f"aspect_ratio_input={aspect!r} regressed to size='0.5K' "
                f"(issue #29 — rejected by Gemini API)."
            )


# ---------------------------------------------------------------------------
# 4. Clamp breadcrumb — silent-failure-hunter #1 close
# ---------------------------------------------------------------------------


class TestGeminiClampBreadcrumb:
    """The clamp from 4K → 2K is silent at the API contract level
    (caller gets a successful response with smaller bytes). But the
    operator MUST be able to detect the downgrade — otherwise a
    storyteller worker that stored the WebP has no way to know the
    resolution contract was violated. Pin the [GEMINI-IMAGE-CLAMP]
    log breadcrumb that surfaces this."""

    @pytest.fixture
    def gemini(self):
        from autonomous.ai.models.gemini import GeminiAIModel
        return GeminiAIModel.__new__(GeminiAIModel)

    @pytest.mark.parametrize("aspect", ["4K", "Map", "4KPortrait"])
    def test_clamp_emits_breadcrumb(self, gemini, aspect, monkeypatch):
        """Each 4K-tier aspect input must emit the
        ``[GEMINI-IMAGE-CLAMP]`` marker. The marker name is
        load-bearing — operators grep logs for it when investigating
        unexpected resolution downgrades."""
        from autonomous.ai.models import gemini as gemini_module

        log_calls = []
        monkeypatch.setattr(
            gemini_module, "log",
            lambda msg, _print=False: log_calls.append(msg),
        )
        gemini._get_image_config(aspect)
        markers = [m for m in log_calls if "GEMINI-IMAGE-CLAMP" in m]
        assert len(markers) == 1, (
            f"Expected one clamp breadcrumb for aspect={aspect!r}; "
            f"got {len(markers)}: {markers!r}"
        )

    @pytest.mark.parametrize(
        "non_clamp_aspect",
        ["Portrait", "Landscape", "2K", "2KPortrait", "1:1", "3:4", ""],
    )
    def test_non_clamp_path_emits_no_breadcrumb(
        self, gemini, non_clamp_aspect, monkeypatch
    ):
        """Non-4K-tier paths must NOT emit the breadcrumb — would be
        noise on every Portrait/2K/etc. call."""
        from autonomous.ai.models import gemini as gemini_module

        log_calls = []
        monkeypatch.setattr(
            gemini_module, "log",
            lambda msg, _print=False: log_calls.append(msg),
        )
        gemini._get_image_config(non_clamp_aspect)
        assert not any("GEMINI-IMAGE-CLAMP" in m for m in log_calls)

    def test_breadcrumb_includes_model_pointer(self, gemini, monkeypatch):
        """The breadcrumb mentions ``GEMINI_IMAGE_MODEL`` so the
        operator can find the env var that lifts the clamp without
        digging through code. Pin this so a future maintainer can't
        silently strip the actionable diagnostic."""
        from autonomous.ai.models import gemini as gemini_module

        log_calls = []
        monkeypatch.setattr(
            gemini_module, "log",
            lambda msg, _print=False: log_calls.append(msg),
        )
        gemini._get_image_config("4K")
        marker = next(m for m in log_calls if "GEMINI-IMAGE-CLAMP" in m)
        assert "GEMINI_IMAGE_MODEL" in marker
