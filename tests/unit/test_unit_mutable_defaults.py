"""Regression tests for item 3: mutable-default arg fixes in the AI layer.

The bug class is ``def f(context={}): context["x"] = 1`` — the same dict is
reused across calls, so later callers silently inherit state from earlier
ones. We verify that:

1. Default args are now None / immutable in the fixed signatures.
2. The mock model honors an explicit context without mutating a shared
   default.
"""

import inspect

import pytest


@pytest.fixture(autouse=True)
def _silence_autotasks(monkeypatch):
    from unittest.mock import MagicMock

    with pytest.MonkeyPatch().context() as m:
        m.setattr(
            "autonomous.ai.models.mock_model.MockAIModel.save",
            lambda self: None,
            raising=False,
        )
        yield


def _default(func, arg_name):
    return inspect.signature(func).parameters[arg_name].default


def test_local_model_generate_json_default_is_none():
    from autonomous.ai.models.local_model import LocalAIModel

    assert _default(LocalAIModel.generate_json, "context") is None


def test_local_model_generate_text_default_is_none():
    from autonomous.ai.models.local_model import LocalAIModel

    assert _default(LocalAIModel.generate_text, "context") is None


def test_mock_model_defaults_are_none():
    from autonomous.ai.models.mock_model import MockAIModel

    assert _default(MockAIModel.generate_json, "context") is None
    assert _default(MockAIModel.generate_text, "context") is None


def test_no_shared_context_across_mock_calls():
    """Two calls with no context must not see each other's data."""
    from autonomous.ai.models.mock_model import MockAIModel

    m = MockAIModel.__new__(MockAIModel)  # avoid AutoModel init
    first = m.generate_json("hello")
    # If context defaulted to a shared {}, the next line could mutate it.
    first["leak"] = "boom"
    second = m.generate_json("hello")
    assert "leak" not in second


def test_mock_model_reads_explicit_context():
    from autonomous.ai.models.mock_model import MockAIModel

    m = MockAIModel.__new__(MockAIModel)
    response = m.generate_json("hi", context={"name": "Alice"})
    assert response == {"name": "Mock Alice"}
