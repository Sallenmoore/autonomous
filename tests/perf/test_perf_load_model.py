"""Benchmark AutoModel.load_model() — cold (cache miss) vs. warm (cache hit).

Cold path walks ``AutoModel.__subclasses__()`` recursively. Warm path
is a single dict lookup. The win is structural (O(n) vs O(1)) so the
benchmark exists to detect regressions, not to measure ±5% changes.
"""

import pytest

from autonomous.model.automodel import AutoModel


@pytest.fixture(autouse=True)
def _reset_cache():
    AutoModel._invalidate_load_model_cache()
    yield
    AutoModel._invalidate_load_model_cache()


class _Dummy(AutoModel):
    meta = {"abstract": False, "allow_inheritance": True}


def test_load_model_cold(benchmark):
    """Cache miss every time — walks the subclasses tree."""
    def _cold_call():
        AutoModel._invalidate_load_model_cache()
        return AutoModel.load_model("_Dummy")

    result = benchmark(_cold_call)
    assert result is _Dummy


def test_load_model_warm(benchmark):
    """Cache hit after the first call — should be a dict lookup."""
    # Prime the cache once before the timed loop.
    AutoModel.load_model("_Dummy")

    result = benchmark(AutoModel.load_model, "_Dummy")
    assert result is _Dummy
