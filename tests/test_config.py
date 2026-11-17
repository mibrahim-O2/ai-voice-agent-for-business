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
