"""Pieces shared by text mode and voice mode, so both use the same tools, policy and instructions."""

from __future__ import annotations

import os
import sys
from typing import Any

from agents.mcp import MCPServerStdio

from ..business import DataStore
from ..config import Settings
from ..mcp_server.tools import is_sensitive
from .instructions import build_instructions

# Environment passed to the MCP subprocess. The OpenAI key is only passed when the knowledge base
# uses OpenAI embeddings; the CRM tools never need it.
_PASSTHROUGH_ENV = (
    "PATH",
    "HOME",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "PYTHONPATH",
    "VIRTUAL_ENV",
)


def tool_requires_approval(tool_name: str, tool_meta: dict | None = None) -> bool:
    """Approval policy: the shared TOOL_POLICIES table, or the server's own `sensitive` flag.

    Either one is enough to require approval (fail closed). Unknown tools always require it.
    """
    return is_sensitive(tool_name) or bool((tool_meta or {}).get("sensitive"))


async def _mcp_requires_approval(_run_context: Any, _agent: Any, tool: Any) -> bool:
    return tool_requires_approval(getattr(tool, "name", ""), getattr(tool, "meta", None))


def mcp_env(settings: Settings) -> dict[str, str]:
    env = {k: os.environ[k] for k in _PASSTHROUGH_ENV if k in os.environ}
    env.update(
        {
            "VOICE_AGENT_DATA_DIR": str(settings.data_dir),
            "VOICE_AGENT_VAR_DIR": str(settings.var_dir),
            "EMBEDDINGS_PROVIDER": settings.embeddings_provider,
            "LOG_LEVEL": "WARNING",  # keep the MCP server quiet on stderr
            "OPENAI_API_KEY": "",  # an empty value also hides any key in a local .env file
        }
    )
    if settings.fixed_now:
        env["VOICE_AGENT_NOW"] = settings.fixed_now.isoformat()
    if settings.embeddings_provider == "openai" and settings.openai_api_key:
        env["OPENAI_API_KEY"] = settings.openai_api_key
    return env


def build_mcp_server(settings: Settings) -> MCPServerStdio:
    """The business MCP server as a subprocess, with human approval required for sensitive tools."""
    return MCPServerStdio(
        params={
            "command": sys.executable,
            "args": ["-m", "voice_agent.cli", "mcp"],
            "env": mcp_env(settings),
        },
        name="oakleaf-business",
        cache_tools_list=True,
        client_session_timeout_seconds=30,
        require_approval=_mcp_requires_approval,
        use_structured_content=False,
    )


class Lookups:
    """Read-only lookups that make approval summaries human-readable (names and slot times)."""

    def __init__(self, settings: Settings) -> None:
        fixed = settings.fixed_now
        self.store = DataStore(settings.data_dir, settings.var_dir, clock=(lambda: fixed) if fixed else None)

    def describe_lead(self, lead_id: str) -> str | None:
        lead_id = (lead_id or "").strip().upper()
        lead = next((x for x in self.store.leads() if x.id == lead_id), None)
        return f"{lead.name}, status {lead.status.value}" if lead else "no such lead"

    def describe_slot(self, slot_id: str) -> str | None:
        slot_id = (slot_id or "").strip().upper()
        slot = next((s for s in self.store.calendar().slots if s.id == slot_id), None)
        if slot is None:
            return "no such slot"
        state = "open" if slot.available else "NOT available"
        return f"{slot.start:%a %d %b %H:%M}, {slot.staff}, {state}"

    def instructions(self) -> str:
        return build_instructions(self.store.now(), self.store.calendar().timezone)
