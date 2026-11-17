"""The secret scanner catches real-looking keys, the repo is clean, and the CLI works."""

from __future__ import annotations

import subprocess
import sys

import pytest

from conftest import ROOT, load_script
from voice_agent import __version__
from voice_agent.cli import main

scanner = load_script("check_secrets")

FAKE_OPENAI = "sk-proj-" + "A1b2C3d4E5f6G7h8I9j0K1l2"  # built at runtime so this file stays clean


@pytest.mark.parametrize(
    "text",
    [
        f"key = {FAKE_OPENAI}",
        "OPENAI_API_KEY=" + "abcdefghijklmnopqrstuvwx",
        "token ghp_" + "a" * 36,
        "Authorization: Bearer " + "x" * 30,
        "-----BEGIN RSA " + "PRIVATE KEY-----",
    ],
)
def test_scanner_flags_secrets(text):
    assert scanner.scan_text(text)


@pytest.mark.parametrize("text", ["OPENAI_API_KEY=", "skip-this-line", "OPENAI_API_KEY=your-key-here"])
def test_scanner_ignores_placeholders(text):
    assert scanner.scan_text(text) == []


def test_scanner_rejects_env_files():
    problems = scanner.find_problems([(".env", "X=1"), ("config/.env.local", ""), (".env.example", "")])
    assert len(problems) == 2


def test_repository_contains_no_secrets():
    assert scanner.main([]) == 0


def test_env_file_is_ignored_by_git():
    result = subprocess.run(["git", "check-ignore", ".env"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, ".env must be listed in .gitignore"


def test_cli_version(capsys):
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip() == __version__


def test_cli_validate_data(capsys):
    assert main(["validate-data"]) == 0
    assert "OK: all dummy data is valid" in capsys.readouterr().out


def test_cli_runs_as_module():
    result = subprocess.run(
        [sys.executable, "-m", "voice_agent.cli", "version"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert result.stdout.strip() == __version__


def test_cli_tools_lists_sensitivity(capsys):
    assert main(["tools"]) == 0
    out = capsys.readouterr().out
    assert "book_appointment       YES" in out and "search_leads           no" in out


def test_cli_reset_data(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_AGENT_VAR_DIR", str(tmp_path))
    assert main(["reset-data"]) == 0
    assert (tmp_path / "state" / "calendar.json").exists()
    assert "restored" in capsys.readouterr().out


def test_cli_mcp_refuses_public_host_without_flag(capsys):
    assert main(["mcp", "--transport", "streamable-http", "--host", "0.0.0.0"]) == 2  # noqa: S104
    assert "no authentication" in capsys.readouterr().err


def test_cli_ingest_ask_and_rag_eval(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_AGENT_VAR_DIR", str(tmp_path))
    monkeypatch.setenv("EMBEDDINGS_PROVIDER", "local")
    assert main(["ingest"]) == 0
    assert "Indexed 10 documents" in capsys.readouterr().out
    assert main(["ask", "Do you accept cash?", "-k", "1"]) == 0
    out = capsys.readouterr().out
    assert "source: 07-payment-and-warranty.md" in out and "Cash is not accepted" in out
    assert main(["ask", "Can you fix my roof?"]) == 0
    assert "I don't know" in capsys.readouterr().out
    assert main(["rag-eval"]) == 0
    assert "refused 10/10" in capsys.readouterr().out


def test_cli_openai_ingest_without_key_fails_clearly(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_AGENT_VAR_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setattr("voice_agent.config.dotenv_values", lambda *a, **k: {})
    assert main(["ingest", "--provider", "openai"]) == 1
    assert "OPENAI_API_KEY is not set" in capsys.readouterr().err


def test_cli_ask_with_missing_openai_index(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("VOICE_AGENT_VAR_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder-for-test")
    assert main(["ask", "hours", "--provider", "openai"]) == 1
    assert "voice-agent ingest --provider openai" in capsys.readouterr().err


def test_cli_ingest_reports_api_failures_without_the_provider_message(capsys, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from voice_agent.rag import OpenAIEmbedder

    def create(**_kwargs):
        raise RuntimeError("provider text that must not be shown: sk-leak")

    failing = OpenAIEmbedder(client=SimpleNamespace(embeddings=SimpleNamespace(create=create)))
    monkeypatch.setenv("VOICE_AGENT_VAR_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder-for-test")
    monkeypatch.setattr("voice_agent.rag.make_embedder", lambda provider, api_key=None: failing)
    assert main(["ingest", "--provider", "openai"]) == 1
    err = capsys.readouterr().err
    assert "Ingest failed: OpenAI embeddings request failed (RuntimeError)" in err
    assert "sk-leak" not in err and "provider text" not in err
