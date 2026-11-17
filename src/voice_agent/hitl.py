"""Human-in-the-loop approval for sensitive tool calls.

Flow (identical in text and voice mode):

    agent wants to call a sensitive tool  ->  the run pauses (nothing has executed yet)
        -> ApprovalGate.review(): build a summary, log `approval_requested`
        -> an Approver (a person at the console, or a scripted policy in tests) decides
        -> log `approval_decision` (who, approved/rejected, reason)
        -> approve: the SDK runs exactly the arguments that were shown
           reject:  the tool never runs; the agent is told why and offers a human instead

The gate fails closed: an approver error, a timeout or an unknown tool is a rejection.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from .mcp_server.tools import TOOL_POLICIES, is_sensitive
from .observability import SessionLogger

DEFAULT_TIMEOUT_SECONDS = 120.0
REJECTION_MESSAGE = (
    "A human reviewer did not approve this action, so it was NOT carried out. Tell the caller "
    "plainly that you could not complete it, do not try again with the same request, and offer to "
    "have a team member call them back."
)


@dataclass(frozen=True)
class ApprovalRequest:
    tool_name: str
    arguments: dict[str, Any]
    call_id: str
    summary: str
    reason: str  # why this tool needs approval (from TOOL_POLICIES)
    session_id: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Decision:
    approved: bool
    decided_by: str
    reason: str = ""


class Approver(Protocol):
    async def decide(self, request: ApprovalRequest) -> Decision: ...


# ---------- summaries ----------
def _describe_slot(slot_id: str, lookup: Callable[[str], str | None] | None) -> str:
    detail = lookup(slot_id) if lookup else None
    return f"{slot_id} ({detail})" if detail else slot_id


def summarise(
    tool_name: str,
    args: dict[str, Any],
    describe_lead: Callable[[str], str | None] | None = None,
    describe_slot: Callable[[str], str | None] | None = None,
) -> str:
    """One plain-English line a reviewer can approve or reject without reading JSON."""

    def lead(lead_id: Any) -> str:
        detail = describe_lead(str(lead_id)) if describe_lead else None
        return f"{lead_id} ({detail})" if detail else str(lead_id)

    a = args
    if tool_name == "create_lead":
        contact = a.get("phone") or a.get("email") or "no contact"
        return f"Create a new lead: {a.get('name')!r}, {a.get('service_interest')}, contact {contact}"
    if tool_name == "update_lead":
        changes = ", ".join(f"{k}={v!r}" for k, v in a.items() if k != "lead_id")
        return f"Update lead {lead(a.get('lead_id'))}: {changes or 'no fields'}"
    if tool_name == "qualify_lead":
        return f"Score and save the qualification (tier) for lead {lead(a.get('lead_id'))}"
    if tool_name == "add_note":
        return f"Add a note to lead {lead(a.get('lead_id'))}: {a.get('text')!r}"
    if tool_name == "book_appointment":
        service = f" for {a['service']}" if a.get("service") else ""
        slot = _describe_slot(str(a.get("slot_id")), describe_slot)
        return f"Book slot {slot}{service} for lead {lead(a.get('lead_id'))}"
    if tool_name == "cancel_appointment":
        return f"Cancel appointment {a.get('appointment_id')} (reason: {a.get('reason')!r})"
    return f"Run {tool_name} with {json.dumps(a, ensure_ascii=False)}"


# ---------- approvers ----------
class ScriptedApprover:
    """Decides from a list of booleans (or a function). For tests and the offline demo."""

    def __init__(self, decisions: list[bool] | Callable[[ApprovalRequest], bool], name: str = "scripted"):
        self._decisions = decisions
        self.name = name
        self.seen: list[ApprovalRequest] = []

    async def decide(self, request: ApprovalRequest) -> Decision:
        self.seen.append(request)
        if callable(self._decisions):
            approved = bool(self._decisions(request))
        else:
            if not self._decisions:
                return Decision(False, self.name, "no scripted decision left")
            approved = self._decisions.pop(0)
        return Decision(approved, self.name, "scripted approval" if approved else "scripted rejection")


class ConsoleApprover:
    """Asks the person at the terminal. No answer within the timeout counts as a rejection."""

    def __init__(self, reviewer: str = "console-operator", input_fn: Callable[[str], str] = input) -> None:
        self.reviewer = reviewer
        self._input = input_fn

    async def decide(self, request: ApprovalRequest) -> Decision:
        lines = [
            "",
            "=" * 72,
            "APPROVAL NEEDED (nothing has been done yet)",
            f"  Action : {request.summary}",
            f"  Tool   : {request.tool_name}  ({request.reason})",
            f"  Args   : {json.dumps(request.arguments, ensure_ascii=False)}",
        ]
        lines += [f"  WARNING: {w}" for w in request.warnings]
        lines.append("=" * 72)
        print("\n".join(lines), file=sys.stderr, flush=True)
        answer = await asyncio.to_thread(self._input, "Approve? [y = approve / anything else = reject]: ")
        approved = answer.strip().lower() in {"y", "yes"}
        reason = ""
        if not approved:
            reason = await asyncio.to_thread(self._input, "Reason for rejecting (optional): ")
        return Decision(approved, self.reviewer, reason.strip())


# ---------- the gate ----------
class ApprovalGate:
    def __init__(
        self,
        approver: Approver,
        logger: SessionLogger,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        describe_lead: Callable[[str], str | None] | None = None,
        describe_slot: Callable[[str], str | None] | None = None,
    ) -> None:
        self.approver = approver
        self.logger = logger
        self.timeout_seconds = timeout_seconds
        self.describe_lead = describe_lead
        self.describe_slot = describe_slot
        self.session_warnings: list[str] = []  # e.g. a suspected prompt injection earlier in the call

    @staticmethod
    def parse_arguments(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        try:
            parsed = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            return {"_unparsed": str(raw)}
        return parsed if isinstance(parsed, dict) else {"_value": parsed}

    def needs_approval(self, tool_name: str) -> bool:
        return is_sensitive(tool_name)

    async def review(self, tool_name: str, raw_arguments: Any, call_id: str) -> Decision:
        args = self.parse_arguments(raw_arguments)
        policy = TOOL_POLICIES.get(tool_name)
        request = ApprovalRequest(
            tool_name=tool_name,
            arguments=args,
            call_id=call_id,
            summary=summarise(tool_name, args, self.describe_lead, self.describe_slot),
            reason=policy.reason if policy else "unknown tool: approval required",
            session_id=self.logger.session_id,
            warnings=list(self.session_warnings),
        )
        self.logger.log(
            "approval_requested",
            tool=tool_name,
            call_id=call_id,
            arguments=args,
            summary=request.summary,
            reason=request.reason,
            warnings=request.warnings,
        )
        started = datetime.now()
        try:
            decision = await asyncio.wait_for(self.approver.decide(request), timeout=self.timeout_seconds)
        except TimeoutError:
            decision = Decision(False, "system", f"no decision within {self.timeout_seconds:.0f}s")
        except Exception as exc:  # noqa: BLE001 - any approver failure must reject (fail closed)
            decision = Decision(False, "system", f"approver failed ({type(exc).__name__})")
        self.logger.log(
            "approval_decision",
            tool=tool_name,
            call_id=call_id,
            approved=decision.approved,
            decided_by=decision.decided_by,
            reason=decision.reason,
            summary=request.summary,
            wait_ms=int((datetime.now() - started).total_seconds() * 1000),
        )
        return decision

    def rejection_message(self, decision: Decision) -> str:
        return REJECTION_MESSAGE + (f" Reviewer's reason: {decision.reason}" if decision.reason else "")
