"""Shared test fixtures."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    """Import a module from scripts/ by file name (scripts/ is not a package)."""
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"scripts_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def clean_env(monkeypatch):
    """Remove every setting this project reads, so tests do not see the developer's own .env."""
    for var in (
        "OPENAI_API_KEY",
        "OPENAI_TEXT_MODEL",
        "OPENAI_REALTIME_MODEL",
        "EMBEDDINGS_PROVIDER",
        "VOICE_AGENT_VAR_DIR",
        "VOICE_AGENT_DATA_DIR",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


# ---------- business layer fixtures ----------
FIXED_NOW = __import__("datetime").datetime(2026, 11, 20, 10, 0)


@pytest.fixture
def store(tmp_path):
    """A DataStore on a temporary working copy, with the clock fixed before the demo calendar."""
    from voice_agent.business import DataStore
    from voice_agent.config import DATA_DIR

    return DataStore(DATA_DIR, tmp_path / "var", clock=lambda: FIXED_NOW)


@pytest.fixture
def service(store):
    from voice_agent.business import BusinessService

    return BusinessService(store)
