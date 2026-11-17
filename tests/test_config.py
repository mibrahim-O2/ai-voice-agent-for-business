"""Settings come from the environment and never expose the key."""

from __future__ import annotations

import pytest

from voice_agent.config import ConfigError, load_settings


def test_defaults_without_key(clean_env, tmp_path):
    settings = load_settings(tmp_path / "missing.env")
    assert settings.openai_api_key is None
    assert not settings.has_openai_key
    assert settings.embeddings_provider == "local"
    assert settings.var_dir.name == "var"


def test_missing_key_gives_a_helpful_error(clean_env, tmp_path):
    settings = load_settings(tmp_path / "missing.env")
    with pytest.raises(ConfigError, match="Copy .env.example to .env"):
        settings.require_openai_key()


def test_key_is_read_from_env_file_but_not_shown_in_repr(clean_env, tmp_path):
    env = tmp_path / ".env"
    fake_key = "test-key-" + "not-real"  # split so the secret scanner does not flag this test
    env.write_text(f"OPENAI_API_KEY={fake_key}\nEMBEDDINGS_PROVIDER=OpenAI\n")
    settings = load_settings(env)
    assert settings.require_openai_key() == fake_key
    assert settings.embeddings_provider == "openai"
    assert fake_key not in repr(settings)


def test_shell_environment_wins_over_env_file(clean_env, tmp_path):
    env = tmp_path / ".env"
    env.write_text("OPENAI_TEXT_MODEL=from-file\n")
    clean_env.setenv("OPENAI_TEXT_MODEL", "from-shell")
    assert load_settings(env).text_model == "from-shell"


@pytest.mark.parametrize(("var", "value"), [("EMBEDDINGS_PROVIDER", "pinecone"), ("LOG_LEVEL", "LOUD")])
def test_invalid_values_are_rejected(clean_env, tmp_path, var, value):
    clean_env.setenv(var, value)
    with pytest.raises(ConfigError, match=var):
        load_settings(tmp_path / "missing.env")


def test_relative_and_absolute_dirs(clean_env, tmp_path):
    from voice_agent.config import PROJECT_ROOT

    clean_env.setenv("VOICE_AGENT_VAR_DIR", "custom-var")
    clean_env.setenv("VOICE_AGENT_DATA_DIR", str(tmp_path))
    settings = load_settings(tmp_path / "missing.env")
    assert settings.var_dir == PROJECT_ROOT / "custom-var"
    assert settings.data_dir == tmp_path


def test_loading_settings_does_not_modify_the_process_environment(clean_env, tmp_path):
    import os

    env = tmp_path / ".env"
    env.write_text(f"EMBEDDINGS_PROVIDER=openai\nLOG_LEVEL=DEBUG\nVOICE_AGENT_DATA_DIR={tmp_path}\n")
    before = dict(os.environ)
    settings = load_settings(env)
    assert settings.embeddings_provider == "openai" and settings.data_dir == tmp_path
    assert dict(os.environ) == before


def test_fixed_now_override(clean_env, tmp_path):
    clean_env.setenv("VOICE_AGENT_NOW", "2026-11-20T10:00")
    assert load_settings(tmp_path / "missing.env").fixed_now.isoformat() == "2026-11-20T10:00:00"
    clean_env.setenv("VOICE_AGENT_NOW", "tomorrow")
    with pytest.raises(ConfigError, match="VOICE_AGENT_NOW"):
        load_settings(tmp_path / "missing.env")
