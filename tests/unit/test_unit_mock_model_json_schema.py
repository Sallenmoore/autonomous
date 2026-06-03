"""MockAIModel.generate_json must accept the new json_schema / schema_name
kwargs (and any future ones) without TypeError, so JSONAgent dispatch
tests using provider='mock' don't crash. The mock ignores the kwargs by
design — schema-aware tests must construct mock data that conforms."""

from autonomous.ai.models.mock_model import MockAIModel


def _mock():
    return MockAIModel.__new__(MockAIModel)


def test_generate_json_accepts_json_schema_kwarg():
    out = MockAIModel.generate_json(
        _mock(), "prompt", json_schema={"type": "object"}
    )
    assert out is not None


def test_generate_json_accepts_schema_name_kwarg():
    out = MockAIModel.generate_json(
        _mock(), "prompt", schema_name="my_response"
    )
    assert out is not None


def test_generate_json_accepts_both_new_kwargs():
    out = MockAIModel.generate_json(
        _mock(),
        "prompt",
        json_schema={"type": "object"},
        schema_name="my_response",
    )
    assert out is not None
