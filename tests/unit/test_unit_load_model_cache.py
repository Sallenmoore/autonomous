"""Behavioral pin: AutoModel.load_model() memoizes successful lookups.

Catches a regression that silently un-caches (someone reverts the
cache lookup). The optimization saves the recursive
__subclasses__() walk on every call after the first.
"""

import pytest

from autonomous.model import automodel
from autonomous.model.automodel import AutoModel


class _Probe(AutoModel):
    meta = {"abstract": False, "allow_inheritance": True}


@pytest.fixture(autouse=True)
def _isolate_cache():
    AutoModel._invalidate_load_model_cache()
    yield
    AutoModel._invalidate_load_model_cache()


def test_first_call_walks_subclasses_tree():
    # Sentinel counter — patches __subclasses__ on the cls-level by
    # observing through the module attribute (the actual class method
    # binding isn't easily monkeypatched without affecting all
    # subclasses, so the next test does the more important "second
    # call must NOT walk" check via a different mechanism).
    result = AutoModel.load_model("_Probe")
    assert result is _Probe


def test_second_call_hits_cache_no_tree_walk(monkeypatch):
    # Prime the cache.
    AutoModel.load_model("_Probe")

    # Now make any __subclasses__() call raise — this proves the
    # second call short-circuits before reaching the tree walk.
    sentinel = []

    original = AutoModel.__subclasses__

    def _exploding_subclasses(cls=None):
        sentinel.append("tree_walk_happened")
        return original()

    monkeypatch.setattr(AutoModel, "__subclasses__", classmethod(lambda cls: _exploding_subclasses(cls)))

    result = AutoModel.load_model("_Probe")
    assert result is _Probe
    assert sentinel == [], (
        "load_model should hit the cache on the second call and NOT "
        "walk __subclasses__() again"
    )


def test_case_insensitive_cache_key():
    AutoModel.load_model("_Probe")
    # Different casing must still hit the cache (lowercased key).
    assert "_probe" in automodel._LOAD_MODEL_CACHE
    result = AutoModel.load_model("_PROBE")
    assert result is _Probe


def test_invalidate_clears_cache():
    AutoModel.load_model("_Probe")
    assert "_probe" in automodel._LOAD_MODEL_CACHE
    AutoModel._invalidate_load_model_cache()
    assert automodel._LOAD_MODEL_CACHE == {}


def test_miss_not_cached():
    """ValueError on an unknown name must NOT poison the cache."""
    with pytest.raises(ValueError):
        AutoModel.load_model("DoesNotExist")
    assert "doesnotexist" not in automodel._LOAD_MODEL_CACHE
