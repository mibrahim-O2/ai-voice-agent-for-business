"""The policy for every MCP tool: is it sensitive (needs human approval), read-only, destructive?

This table is the single source of truth. The MCP server publishes it in each tool's annotations
and `_meta`, and the human-in-the-loop gate (Task 4) uses `SENSITIVE_TOOLS` to decide what must
be approved. A test checks that every tool that changes data is marked sensitive.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolPolicy:
    sensitive: bool  # requires human approval before it runs
    read_only: bool  # never changes data
    destructive: bool  # removes or reverses something (for example a booking)
    reason: str  # why it is (or is not) sensitive, shown to reviewers


TOOL_POLICIES: dict[str, ToolPolicy] = {
    "search_leads": ToolPolicy(False, True, False, "read-only lookup"),
    "get_lead": ToolPolicy(False, True, False, "read-only lookup"),
    "list_available_slots": ToolPolicy(False, True, False, "read-only lookup"),
    "search_knowledge": ToolPolicy(False, True, False, "read-only search of the company knowledge base"),
    "create_lead": ToolPolicy(True, False, False, "creates a customer record"),
    "update_lead": ToolPolicy(True, False, False, "changes a customer record"),
    "qualify_lead": ToolPolicy(True, False, False, "writes a score, tier and status to the customer record"),
    "add_note": ToolPolicy(True, False, False, "writes to the customer record"),
    "book_appointment": ToolPolicy(True, False, False, "books a technician's time for a customer"),
    "cancel_appointment": ToolPolicy(True, False, True, "cancels a customer's booking and may incur a fee"),
}

SENSITIVE_TOOLS: frozenset[str] = frozenset(name for name, p in TOOL_POLICIES.items() if p.sensitive)


def is_sensitive(tool_name: str) -> bool:
    """Unknown tools are treated as sensitive (fail closed)."""
    policy = TOOL_POLICIES.get(tool_name)
    return True if policy is None else policy.sensitive
