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
