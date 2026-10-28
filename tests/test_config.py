import pytest

from citywheels.config import NOW, ConfigError, load_llm_settings


def test_now_is_fixed() -> None:
    assert NOW.isoformat() == "2026-06-10T09:00:00+02:00"


def test_load_settings_defaults_to_gemini() -> None:
    settings = load_llm_settings(env={"GEMINI_API_KEY": "x"})

    assert settings.provider == "gemini"
    assert settings.model == "gemini-3.8-flash"
    assert settings.api_key == "x"


def test_model_override() -> None:
    settings = load_llm_settings(env={"GEMINI_API_KEY": "x", "LLM_MODEL": "gemini-3.5-flash-lite"})

    assert settings.model == "gemini-3.5-flash-lite"


def test_empty_values_are_treated_as_unset() -> None:
    env = {"GEMINI_API_KEY": "x", "LLM_PROVIDER": "", "LLM_MODEL": ""}

    settings = load_llm_settings(env=env)

    assert settings.provider == "gemini"
    assert settings.model == "gemini-3.8-flash"


def test_explicit_provider_beats_environment() -> None:
    env = {"LLM_PROVIDER": "gemini", "XAI_API_KEY": "k"}

    assert load_llm_settings("grok", env).provider == "grok"


def test_missing_key_raises_config_error() -> None:
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        load_llm_settings(env={})


def test_unknown_provider_raises() -> None:
    with pytest.raises(ConfigError, match="nope"):
        load_llm_settings("nope", {})
