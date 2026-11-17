"""Runtime settings, read from environment variables (optionally via a local .env file).

The OpenAI key is only ever read from the OPENAI_API_KEY environment variable. It is never
logged, never written to disk by this project, and never included in the repr of Settings.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values

# Repo root when running from a clone (editable install). For a regular install, set
# VOICE_AGENT_DATA_DIR (and VOICE_AGENT_VAR_DIR) to absolute paths instead.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


def _resolve_dir(value: str | None, default: Path) -> Path:
    path = Path(value.strip()) if value and value.strip() else default
    return path if path.is_absolute() else PROJECT_ROOT / path


def data_dir(env: Mapping[str, str] | None = None) -> Path:
    """The dummy-data directory: VOICE_AGENT_DATA_DIR if set, else <repo>/data."""
    return _resolve_dir((env if env is not None else os.environ).get("VOICE_AGENT_DATA_DIR"), DATA_DIR)


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
    # Optional fixed "now" for the demo calendar (tests and demos after the demo dates have passed).
    fixed_now: datetime | None = None

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
    # Read .env without touching os.environ: loading settings must not have side effects on the
    # process (or leak into other code). Real environment variables win over the file.
    file_values = dotenv_values(env_file or PROJECT_ROOT / ".env")
    env: dict[str, str] = {k: v for k, v in file_values.items() if v is not None}
    env.update(os.environ)

    embeddings = env.get("EMBEDDINGS_PROVIDER", "local").strip().lower() or "local"
    if embeddings not in VALID_EMBEDDINGS:
        raise ConfigError(f"EMBEDDINGS_PROVIDER must be one of {VALID_EMBEDDINGS}, got {embeddings!r}")

    log_level = env.get("LOG_LEVEL", "INFO").strip().upper() or "INFO"
    if log_level not in VALID_LOG_LEVELS:
        raise ConfigError(f"LOG_LEVEL must be one of {VALID_LOG_LEVELS}, got {log_level!r}")

    fixed_now = None
    raw_now = env.get("VOICE_AGENT_NOW", "").strip()
    if raw_now:
        try:
            fixed_now = datetime.fromisoformat(raw_now).replace(tzinfo=None)
        except ValueError as exc:
            raise ConfigError(
                f"VOICE_AGENT_NOW must be an ISO date-time like 2026-11-20T10:00, got {raw_now!r}"
            ) from exc

    return Settings(
        openai_api_key=(env.get("OPENAI_API_KEY") or "").strip() or None,
        text_model=env.get("OPENAI_TEXT_MODEL", "").strip() or "gpt-4.1-mini",
        realtime_model=env.get("OPENAI_REALTIME_MODEL", "").strip() or "gpt-realtime",
        embeddings_provider=embeddings,
        var_dir=_resolve_dir(env.get("VOICE_AGENT_VAR_DIR"), PROJECT_ROOT / "var"),
        log_level=log_level,
        data_dir=data_dir(env),
        fixed_now=fixed_now,
    )
