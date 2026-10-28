"""Project constants and LLM provider settings."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Fixed clock so answers and tests are reproducible; never read the system time.
NOW = datetime.fromisoformat("2026-06-10T09:00:00+02:00")

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICIES_DIR = REPO_ROOT / "data" / "policies"
BOOKINGS_PATH = REPO_ROOT / "data" / "bookings.json"

STAFF_EMAIL = "help@citywheels.example"
STAFF_PHONE = "+48 000 000 000"

DEFAULT_PROVIDER = "gemini"


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    api_key_env: str
    default_model: str


# Both expose an OpenAI-compatible endpoint, so one client covers them.
PROVIDERS: dict[str, ProviderConfig] = {
    "gemini": ProviderConfig(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key_env="GEMINI_API_KEY",
        default_model="gemini-2.5-flash",
    ),
    "grok": ProviderConfig(
        base_url="https://api.x.ai/v1",
        api_key_env="XAI_API_KEY",
        default_model="grok-3-mini",
    ),
}


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    base_url: str
    api_key: str
    model: str


class ConfigError(Exception):
    """Raised when the LLM configuration is unusable."""


def load_llm_settings(
    provider: str | None = None, env: Mapping[str, str] = os.environ
) -> LLMSettings:
    """Resolve settings from the argument, then the environment, then defaults.

    Empty values count as unset so a copied `.env.example` behaves like no `.env`.
    The caller loads `.env`; keeping that out of here keeps this testable.
    """
    name = provider or env.get("LLM_PROVIDER") or DEFAULT_PROVIDER
    config = PROVIDERS.get(name)
    if config is None:
        known = ", ".join(sorted(PROVIDERS))
        raise ConfigError(f"Unknown LLM provider '{name}'. Choose one of: {known}.")

    api_key = env.get(config.api_key_env)
    if not api_key:
        raise ConfigError(f"Missing API key: set {config.api_key_env} for provider '{name}'.")

    return LLMSettings(
        provider=name,
        base_url=config.base_url,
        api_key=api_key,
        model=env.get("LLM_MODEL") or config.default_model,
    )
