"""Tests for env-overridable Gemini model names in autonomous.ai.models.gemini.

GeminiAIModel had hardcoded class attributes for every model it talked to —
text, summary, json, stt, image, tts. When Google deprecated preview models
(observed: `gemini-2.0-flash-exp` for TTS started returning 404 NOT_FOUND),
deployments couldn't recover without a library release. Each model name is
now an env var override; defaults track Google's current stable / preview
lineup but any deployment can swap a model without a bump.
"""

import importlib

import pytest


GEMINI_MODEL_ENV_VARS = [
    ("GEMINI_TEXT_MODEL", "_text_model"),
    ("GEMINI_SUMMARY_MODEL", "_summary_model"),
    ("GEMINI_JSON_MODEL", "_json_model"),
    ("GEMINI_STT_MODEL", "_stt_model"),
    ("GEMINI_IMAGE_MODEL", "_image_model"),
    ("GEMINI_TTS_MODEL", "_tts_model"),
]


@pytest.mark.parametrize("env_var,attr", GEMINI_MODEL_ENV_VARS)
def test_gemini_model_attr_reads_from_env(monkeypatch, env_var, attr):
    """Setting the env var before module load should override the class attr."""
    sentinel = f"test-override-{env_var.lower()}"
    monkeypatch.setenv(env_var, sentinel)
    import autonomous.ai.models.gemini as gemini_module

    importlib.reload(gemini_module)
    try:
        assert getattr(gemini_module.GeminiAIModel, attr) == sentinel
    finally:
        # Reload again *without* the env override so other tests in the
        # session see the default values, not our test sentinels.
        monkeypatch.delenv(env_var, raising=False)
        importlib.reload(gemini_module)


def test_tts_default_no_longer_deprecated_flash_exp():
    """Regression: the previous default `gemini-2.0-flash-exp` started
    returning 404 NOT_FOUND. Default must be a current preview/stable model.
    """
    import autonomous.ai.models.gemini as gemini_module

    importlib.reload(gemini_module)
    assert gemini_module.GeminiAIModel._tts_model != "gemini-2.0-flash-exp"


def test_all_six_models_have_string_defaults():
    """No model should accidentally be None / empty after the env switch."""
    import autonomous.ai.models.gemini as gemini_module

    importlib.reload(gemini_module)
    for _, attr in GEMINI_MODEL_ENV_VARS:
        value = getattr(gemini_module.GeminiAIModel, attr)
        assert isinstance(value, str) and value, f"{attr} is empty: {value!r}"
