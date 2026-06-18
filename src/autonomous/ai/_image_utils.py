"""Shared image-config vocabulary for image-generation adapters (#149).

`resolve_image_config(aspect_ratio_input)` parses autonomous's user-facing
aspect-ratio key into a canonical `(ratio, tier)` pair. Provider adapters
translate the tier to their own wire shape (Flux's `square_hd` /
`landscape_4_3` enum; Gemini's `1K` / `2K` size string).

This was previously duplicated as `_get_image_config` on `FluxAIModel`
and `GeminiAIModel`; the 2026-06-18 multi-agent audit flagged the
duplication and #149 collapses it. The two adapters' existing unit-test
suites pin the per-provider wire-shape outputs and become the regression
check.

Lives at `autonomous.ai._image_utils` (sibling of `_extract.py`) rather
than under `models/` so non-adapter callers (e.g. ImageAgent dispatch)
can validate the canonical vocabulary without reaching into a private
sub-namespace.
"""

from __future__ import annotations

_BARE_RATIOS = ("1:1", "3:4", "4:3", "9:16", "16:9")

# Canonical autonomous aspect-ratio key → (ratio, tier).
# `tier` is "low" / "2K" / "4K" — a coarse size hint each adapter maps
# to its own wire shape.
_TABLE = {
    "Portrait":   ("3:4",  "low"),
    "Landscape":  ("16:9", "low"),
    "2K":         ("16:9", "2K"),
    "2KPortrait": ("3:4",  "2K"),
    "4K":         ("16:9", "4K"),
    "Map":        ("16:9", "4K"),
    "4KPortrait": ("3:4",  "4K"),
}


def resolve_image_config(aspect_ratio_input: str) -> tuple[str, str]:
    """Map an autonomous aspect-ratio key to a canonical `(ratio, tier)`.

    `ratio` is one of "1:1", "3:4", "4:3", "9:16", "16:9".
    `tier` is one of "low", "2K", "4K".

    Default fallback (anything not in the table or bare-ratio set) is
    `("3:4", "low")`, matching the pre-#149 behavior of both Flux and
    Gemini's `_get_image_config`.
    """
    if aspect_ratio_input in _TABLE:
        return _TABLE[aspect_ratio_input]
    if aspect_ratio_input in _BARE_RATIOS:
        return aspect_ratio_input, "low"
    return "3:4", "low"
