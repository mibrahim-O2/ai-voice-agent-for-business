"""MCP server exposing the demo CRM and calendar as tools.

Run it with `voice-agent mcp` (stdio, for an MCP client such as the voice agent) or
`voice-agent mcp --transport streamable-http --port 8765` (HTTP).

Each tool's annotations say whether it is read-only or destructive, and its `_meta` carries
`{"sensitive": true|false}`. Sensitive tools must be approved by a human before they run; the
approval gate lives in the agent (Task 4), because the MCP server cannot pause for a person.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from ..business import BusinessError, BusinessService, DataStore
from ..config import Settings, load_settings
from .tools import TOOL_POLICIES

Status = Literal["new", "contacted", "qualified", "unqualified", "booked"]
Tier = Literal["hot", "warm", "cold"]
Timeline = Literal["this_week", "this_month", "next_quarter", "just_researching"]
Service = Literal[
    "AC repair",
    "Furnace installation",
    "Plumbing repair",
    "Water heater installation",
    "Electrical inspection",
    "Duct cleaning",
    "Annual maintenance plan",
]
Source = Literal["inbound_call", "website_form", "referral", "google_ads", "facebook_ads"]
LeadId = Annotated[str, Field(description="Lead id, for example L-001", max_length=12)]

INSTRUCTIONS = (
    "Business tools for Oakleaf Home Services (a fictional demo company). Read tools are safe. "
    "Tools whose _meta has sensitive=true change customer data or bookings and must be approved by "
    "a human before they are called. All data is fictional."
)


def _register(server: MCPServer, name: str, description: str) -> Callable:
    """Register a tool with annotations and metadata taken from TOOL_POLICIES."""
    policy = TOOL_POLICIES[name]

    def decorator(fn: Callable[..., dict]) -> Callable[..., dict]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
            try:
                return fn(*args, **kwargs)
            except BusinessError as exc:
                raise ToolError(str(exc)) from exc

        server.add_tool(
            wrapper,
            name=name,
            description=description,
            annotations=ToolAnnotations(
                title=name.replace("_", " ").capitalize(),
                read_only_hint=policy.read_only,
                destructive_hint=policy.destructive,
                idempotent_hint=policy.read_only,
                open_world_hint=False,
            ),
            meta={"sensitive": policy.sensitive, "approval": "required" if policy.sensitive else "none"},
            structured_output=True,
        )
        return wrapper

    return decorator


def build_server(svc: BusinessService) -> MCPServer:
    server = MCPServer(name="oakleaf-business", instructions=INSTRUCTIONS)

    @_register(
        server,
        "search_leads",
        "Search leads by name, company, email, phone digits or id; filter by status/tier.",
    )
    def search_leads(
        query: Annotated[str | None, Field(description="Text to look for", max_length=100)] = None,
        status: Status | None = None,
        tier: Tier | None = None,
        limit: Annotated[int, Field(ge=1, le=25)] = 10,
    ) -> dict[str, Any]:
        return svc.search_leads(query=query, status=status, tier=tier, limit=limit)

    @_register(server, "get_lead", "Get one lead with its notes and appointments.")
    def get_lead(lead_id: LeadId) -> dict[str, Any]:
        return svc.get_lead(lead_id)

    @_register(
        server,
        "create_lead",
        "SENSITIVE (needs approval). Create a new lead. Needs a name, the service, and a phone or email. "
        "Demo rule: phone numbers must be fictional (555-0100 to 555-0199) and emails must be @example.com.",
    )
    def create_lead(
        name: Annotated[str, Field(min_length=1, max_length=100)],
        service_interest: Service,
        phone: Annotated[str | None, Field(max_length=30)] = None,
        email: Annotated[str | None, Field(max_length=200)] = None,
        company: Annotated[str | None, Field(max_length=120)] = None,
        budget_usd: Annotated[int | None, Field(ge=0, le=1_000_000)] = None,
        timeline: Timeline | None = None,
        source: Source = "inbound_call",
    ) -> dict[str, Any]:
        return svc.create_lead(
            name=name,
            service_interest=service_interest,
            phone=phone,
            email=email,
            company=company,
            budget_usd=budget_usd,
            timeline=timeline,
            source=source,
        )

    @_register(server, "update_lead", "SENSITIVE (needs approval). Change fields on an existing lead.")
    def update_lead(
        lead_id: LeadId,
        status: Literal["new", "contacted", "qualified", "unqualified"] | None = None,
        service_interest: Service | None = None,
        budget_usd: Annotated[int | None, Field(ge=0, le=1_000_000)] = None,
        timeline: Timeline | None = None,
        company: Annotated[str | None, Field(max_length=120)] = None,
        phone: Annotated[str | None, Field(max_length=30)] = None,
        email: Annotated[str | None, Field(max_length=200)] = None,
    ) -> dict[str, Any]:
        return svc.update_lead(
            lead_id,
            status=status,
            service_interest=service_interest,
            budget_usd=budget_usd,
            timeline=timeline,
            company=company,
            phone=phone,
            email=email,
        )

    @_register(
        server,
        "qualify_lead",
        "SENSITIVE (needs approval). Score a lead 0-100 from budget, timeline, service fit and contact "
        "details, set its tier (hot >= 70, warm >= 40, cold) and save it. Returns the reasons.",
    )
    def qualify_lead(lead_id: LeadId) -> dict[str, Any]:
        return svc.qualify_lead(lead_id)

    @_register(server, "add_note", "SENSITIVE (needs approval). Add a short note to a lead.")
    def add_note(
        lead_id: LeadId,
        text: Annotated[str, Field(min_length=1, max_length=1000)],
        author: Annotated[str, Field(min_length=1, max_length=60)] = "voice-agent",
    ) -> dict[str, Any]:
        return svc.add_note(lead_id, text, author)

    @_register(
        server,
        "list_available_slots",
        "List open one-hour appointment slots in the future, optionally between two dates (YYYY-MM-DD).",
    )
    def list_available_slots(
        date_from: Annotated[str | None, Field(description="First date, YYYY-MM-DD", max_length=10)] = None,
        date_to: Annotated[str | None, Field(description="Last date, YYYY-MM-DD", max_length=10)] = None,
        staff: Annotated[str | None, Field(max_length=60)] = None,
        limit: Annotated[int, Field(ge=1, le=20)] = 10,
    ) -> dict[str, Any]:
        return svc.list_available_slots(date_from=date_from, date_to=date_to, staff=staff, limit=limit)

    @_register(
        server,
        "book_appointment",
        "SENSITIVE (needs approval). Book an available slot for a lead. Marks the lead as booked.",
    )
    def book_appointment(
        lead_id: LeadId,
        slot_id: Annotated[str, Field(description="Slot id, for example S-20261201-0900", max_length=20)],
        service: Service | None = None,
    ) -> dict[str, Any]:
        return svc.book_appointment(lead_id, slot_id, service)

    @_register(
        server,
        "cancel_appointment",
        "SENSITIVE (needs approval). Cancel an appointment and free its slot. Cancelling less than "
        "24 hours before the start incurs a $40 late fee (reported in the result).",
    )
    def cancel_appointment(
        appointment_id: Annotated[str, Field(description="Appointment id, for example A-001", max_length=12)],
        reason: Annotated[str, Field(min_length=1, max_length=300)],
    ) -> dict[str, Any]:
        return svc.cancel_appointment(appointment_id, reason)

    return server


def create_default_server(settings: Settings | None = None) -> MCPServer:
    settings = settings or load_settings()
    store = DataStore(settings.data_dir, settings.var_dir)
    return build_server(BusinessService(store))
