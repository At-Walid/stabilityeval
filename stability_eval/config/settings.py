import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

from pydantic import SecretStr
from pydantic_settings import BaseSettings

API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"
# A key supplied for one run (the dashboard's session key). A context variable, not an environment
# variable: it is never written anywhere, and other threads (other dashboard sessions) never see it.
_API_KEY_OVERRIDE: ContextVar[Optional[str]] = ContextVar("anthropic_api_key_override", default=None)


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./stabilityeval.db"
    # SecretStr keeps the key out of repr()/str(), JSON dumps, logs and pytest assertion output.
    # Read it through get_anthropic_api_key(), and only to hand it to the Anthropic SDK.
    ANTHROPIC_API_KEY: Optional[SecretStr] = None
    FIXTURES_DIR: str = "stability_eval/fixtures/mock_responses"
    RESULTS_DIR: str = "./results"
    DEFAULT_COST_CAP_USD: float = 0.50
    DEFAULT_TIMEOUT_SECONDS: int = 120
    DEFAULT_TOTAL_COST_LIMIT_USD: float = 20.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "case_sensitive": True}


settings = Settings()


def get_anthropic_api_key(env_var: str = API_KEY_ENV_VAR) -> Optional[str]:
    """The API key in plain text for the Anthropic SDK, or None when it is not configured.

    A key set with ``api_key_override`` wins; then the process environment, which wins over the
    value loaded from .env when ``settings`` was built, so later overrides (tests, per-run env
    vars) take effect. Pass the result straight to the SDK client; never print, log, or persist it.
    """
    value = _API_KEY_OVERRIDE.get() or os.environ.get(env_var) or settings.ANTHROPIC_API_KEY
    if isinstance(value, SecretStr):
        value = value.get_secret_value()
    return value or None


@contextmanager
def api_key_override(api_key: Optional[str]) -> Iterator[None]:
    """Use ``api_key`` for every Anthropic call made in this context (agent and transformations)."""
    token = _API_KEY_OVERRIDE.set(api_key or None)
    try:
        yield
    finally:
        _API_KEY_OVERRIDE.reset(token)


def redact_api_key(text: Optional[str], api_key: Optional[str] = None) -> Optional[str]:
    """``text`` with the API key (``api_key``, else the configured one) masked.

    Error messages are stored in the database and shown in the dashboard, so they pass through
    here first.
    """
    secret = api_key or get_anthropic_api_key()
    if not text or not secret:
        return text
    return text.replace(secret, "[REDACTED]")
