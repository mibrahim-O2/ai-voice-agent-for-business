"""MCP server exposing the demo CRM and calendar tools."""

from .server import build_server, create_default_server
from .tools import SENSITIVE_TOOLS, TOOL_POLICIES, is_sensitive

__all__ = ["SENSITIVE_TOOLS", "TOOL_POLICIES", "build_server", "create_default_server", "is_sensitive"]
