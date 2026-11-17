"""Runtime settings, read from environment variables (optionally via a local .env file).

The OpenAI key is only ever read from the OPENAI_API_KEY environment variable. It is never
logged, never written to disk by this project, and never included in the repr of Settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

VALID_EMBEDDINGS = ("local", "openai")
VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


class ConfigError(ValueError):
    """Raised when a setting is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None = field(default=None, repr=False)
    text_model: str = "gpt-4.1-mini"
    realtime_model: str = "gpt-realtime"
    embeddings_provider: str = "local"
    var_dir: Path = PROJECT_ROOT / "var"
    log_level: str = "INFO"
    data_dir: Path = DATA_DIR

    @property
    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key)

    def require_openai_key(self) -> str:
        """Return the key, or raise a clear error telling the user how to set it."""
        if not self.openai_api_key:
            raise ConfigError(
                "OPENAI_API_KEY is not set. Copy .env.example to .env and add your own key, "
                "or export OPENAI_API_KEY in your shell. Offline text mode and the tests do not need it."
            )
        return self.openai_api_key


def load_settings(env_file: str | os.PathLike[str] | None = None) -> Settings:
    """Build Settings from the environment. A .env file fills in variables that are not already set."""
    load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)

    embeddings = os.getenv("EMBEDDINGS_PROVIDER", "local").strip().lower() or "local"
    if embeddings not in VALID_EMBEDDINGS:
        raise ConfigError(f"EMBEDDINGS_PROVIDER must be one of {VALID_EMBEDDINGS}, got {embeddings!r}")

    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
    if log_level not in VALID_LOG_LEVELS:
        raise ConfigError(f"LOG_LEVEL must be one of {VALID_LOG_LEVELS}, got {log_level!r}")

    var_dir = Path(os.getenv("VOICE_AGENT_VAR_DIR", "var").strip() or "var")
    if not var_dir.is_absolute():
        var_dir = PROJECT_ROOT / var_dir

    return Settings(
        openai_api_key=(os.getenv("OPENAI_API_KEY") or "").strip() or None,
        text_model=os.getenv("OPENAI_TEXT_MODEL", "").strip() or "gpt-4.1-mini",
        realtime_model=os.getenv("OPENAI_REALTIME_MODEL", "").strip() or "gpt-realtime",
        embeddings_provider=embeddings,
        var_dir=var_dir,
        log_level=log_level,
    )
