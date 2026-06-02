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
