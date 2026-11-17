"""The MCP server: tool discovery, sensitivity metadata, calls, errors, and a real stdio session."""

from __future__ import annotations

import inspect
import os
import sys

import pytest
from mcp import Client, StdioServerParameters

from voice_agent.business import BusinessService
from voice_agent.mcp_server import SENSITIVE_TOOLS, TOOL_POLICIES, build_server, is_sensitive

EXPECTED_TOOLS = {
    "search_leads",
    "get_lead",
    "create_lead",
    "update_lead",
    "qualify_lead",
    "add_note",
    "list_available_slots",
    "book_appointment",
    "cancel_appointment",
}


@pytest.fixture
def server(service):
    return build_server(service)


def with_client(test):
    """Run `test(client)` inside an in-process MCP session.

    The session is opened inside the test itself rather than in an async fixture, because anyio
    requires a session's cancel scope to be entered and exited in the same task.
    """

    async def run(server):
        async with Client(server) as client:
            await test(client)

    run.__name__, run.__doc__ = test.__name__, test.__doc__
    return run


async def call_ok(client, name, args=None):
    result = await client.call_tool(name, args or {})
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def call_err(client, name, args):
    result = await client.call_tool(name, args)
    assert result.is_error
    return result.content[0].text


# ---------- policy ----------
def test_every_write_operation_is_sensitive():
    public_methods = {
        name
        for name, _ in inspect.getmembers(BusinessService, inspect.isfunction)
        if not name.startswith("_")
    }
    assert public_methods == EXPECTED_TOOLS == set(TOOL_POLICIES)
    assert BusinessService.WRITE_OPERATIONS == SENSITIVE_TOOLS
    for name, policy in TOOL_POLICIES.items():
        assert policy.sensitive == (not policy.read_only), name


def test_unknown_tools_fail_closed():
    assert is_sensitive("drop_database")
    assert not is_sensitive("search_leads")


@with_client
async def test_tools_are_listed_with_annotations_and_meta(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    assert set(tools) == EXPECTED_TOOLS
    for name, tool in tools.items():
        policy = TOOL_POLICIES[name]
        assert tool.meta["sensitive"] is policy.sensitive
        assert tool.meta["approval"] == ("required" if policy.sensitive else "none")
        assert tool.annotations.read_only_hint is policy.read_only
        assert tool.annotations.destructive_hint is policy.destructive
        assert tool.description
        if policy.sensitive:
            assert tool.description.startswith("SENSITIVE")
    assert tools["cancel_appointment"].annotations.destructive_hint is True


@with_client
async def test_input_schemas_constrain_enums(client):
    tools = {t.name: t for t in (await client.list_tools()).tools}
    schema = tools["create_lead"].input_schema
    assert set(schema["required"]) == {"name", "service_interest"}
    assert "AC repair" in str(schema["properties"]["service_interest"])


# ---------- every tool through MCP ----------
@with_client
async def test_read_tools(client):
    assert (await call_ok(client, "search_leads", {"query": "calloway"}))["leads"][0]["id"] == "L-003"
    assert (await call_ok(client, "get_lead", {"lead_id": "L-003"}))["lead"]["name"] == "Cleo Calloway"
    slots = await call_ok(client, "list_available_slots", {"date_from": "2026-12-01", "limit": 3})
    assert len(slots["slots"]) == 3


@with_client
async def test_full_lead_lifecycle_through_mcp(client):
    lead = (
        await call_ok(
            client,
            "create_lead",
            {"name": "Mcp Caller", "service_interest": "Duct cleaning", "email": "mcp.caller@example.com"},
        )
    )["lead"]
    lead_id = lead["id"]
    await call_ok(client, "update_lead", {"lead_id": lead_id, "budget_usd": 1200, "timeline": "this_month"})
    qualified = await call_ok(client, "qualify_lead", {"lead_id": lead_id})
    assert qualified["tier"] == "hot" and qualified["score"] == 30 + 22 + 15 + 8
    await call_ok(client, "add_note", {"lead_id": lead_id, "text": "Prefers mornings."})
    slot_id = (await call_ok(client, "list_available_slots", {"limit": 1}))["slots"][0]["slot_id"]
    booking = await call_ok(client, "book_appointment", {"lead_id": lead_id, "slot_id": slot_id})
    cancel = await call_ok(
        client, "cancel_appointment", {"appointment_id": booking["appointment"]["id"], "reason": "test"}
    )
    assert cancel["cancelled"]
    final = await call_ok(client, "get_lead", {"lead_id": lead_id})
    assert final["lead"]["status"] == "qualified"
    assert [n["text"] for n in final["lead"]["notes"]][1] == "Prefers mornings."


# ---------- errors ----------
@with_client
async def test_business_errors_become_clear_tool_errors(client):
    assert "not_found: no lead with id L-404" in await call_err(client, "get_lead", {"lead_id": "L-404"})
    assert "invalid_input" in await call_err(client, "get_lead", {"lead_id": "L-1;DROP"})
    assert "at most 12" in await call_err(client, "get_lead", {"lead_id": "../../etc/passwd"})
    assert "fictional phone numbers" in await call_err(
        client, "create_lead", {"name": "Real", "service_interest": "AC repair", "phone": "312-867-5309"}
    )


@with_client
async def test_schema_violations_are_rejected_before_the_tool_runs(client):
    assert "limit" in await call_err(client, "search_leads", {"limit": 500})
    assert "service_interest" in await call_err(
        client, "create_lead", {"name": "X", "service_interest": "Roofing"}
    )
    assert "lead_id" in await call_err(client, "qualify_lead", {})
    assert "status" in await call_err(client, "update_lead", {"lead_id": "L-001", "status": "booked"})


# ---------- real stdio transport ----------
async def test_stdio_server_end_to_end(tmp_path):
    """Start `python -m voice_agent.cli mcp` as a subprocess and talk to it over stdio."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "voice_agent.cli", "mcp"],
        env={**os.environ, "VOICE_AGENT_VAR_DIR": str(tmp_path), "OPENAI_API_KEY": ""},
    )
    async with Client(params) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert names == EXPECTED_TOOLS
        found = await c.call_tool("search_leads", {"status": "booked"})
        assert found.structured_content["count"] == 3
        note = await c.call_tool("add_note", {"lead_id": "L-001", "text": "via stdio"})
        assert not note.is_error
        slots = await c.call_tool("list_available_slots", {})
        assert not slots.is_error  # may be empty once the demo dates have passed
    assert (tmp_path / "state" / "leads.json").exists()
