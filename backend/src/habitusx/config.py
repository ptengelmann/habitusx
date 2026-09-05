"""Runtime configuration.

All settings come from the environment (or a local ``.env`` in development), prefixed
``HABITUSX_``. Nothing here reads files at import time; call :func:`get_settings` when
you need values so tests can override them cleanly.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from habitusx.errors import ConfigurationError

# backend/src/habitusx/config.py -> repository root is four levels up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY_PATH = _REPO_ROOT / "registry" / "agents.yaml"

Environment = Literal["dev", "test", "prod"]
LogFormat = Literal["console", "json"]


class Settings(BaseSettings):
    """Process-wide settings, validated once at startup."""

    model_config = SettingsConfigDict(
        env_prefix="HABITUSX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        frozen=True,
    )

    environment: Environment = "dev"
    log_level: str = "INFO"
    log_format: LogFormat | None = Field(
        default=None,
        description="Defaults to 'console' in dev/test and 'json' in prod.",
    )
    registry_path: Path = Field(
        default=DEFAULT_REGISTRY_PATH,
        description="Path to the attribution registry YAML.",
    )

    @field_validator("log_level")
    @classmethod
    def _upper_and_known(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            msg = f"HABITUSX_LOG_LEVEL must be a standard level name, got {value!r}"
            raise ValueError(msg)
        return level

    @property
    def effective_log_format(self) -> LogFormat:
        """Resolve the log format default from the environment."""
        if self.log_format is not None:
            return self.log_format
        return "json" if self.environment == "prod" else "console"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings, constructing and validating them on first use."""
    try:
        return Settings()
    except ValueError as exc:  # pydantic raises ValidationError, a ValueError subclass
        raise ConfigurationError(str(exc)) from exc
