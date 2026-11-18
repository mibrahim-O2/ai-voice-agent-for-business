"""Build the dashboard's data file (dashboard/demo/snapshot.json) from recorded demo sessions.

The snapshot is not hand-written. `scripts/export_demo_snapshot.py` runs `voice-agent demo`
(scripted calls through the real MCP tools, knowledge base and approval gate) on fresh demo data,
then this module turns the session log and the resulting CRM/calendar state into the numbers,
tables and transcripts the static dashboard shows.

The output is deterministic for a given demo run: wall-clock timestamps are left out (the demo
runs in a fraction of a second, so they carry no meaning), and everything is sorted.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from .observability import read_events

SNAPSHOT_VERSION = 1
NOTICE = (
    "Scripted sample calls for a fictional company (Oakleaf Home Services). "
    "No real people, phone numbers or customers. The agent's words are scripted; the tools, "
    "knowledge search and approval steps ran for real when this snapshot was recorded."
)
TRANSCRIPT_TYPES = {
    "caller",
    "agent",
    "tool_call",
    "tool_result",
    "approval_requested",
    "approval_decision",
    "guardrail",
    "handoff",
    "error",
}


def _transcript_entry(event: dict) -> dict:
    kind = event["type"]
    entry: dict[str, Any] = {"seq": event["seq"], "type": kind}
    if kind in ("caller", "agent"):
        entry["text"] = event.get("text", "")
        if event.get("greeting"):
            entry["greeting"] = True
    elif kind == "tool_call":
        entry.update(tool=event.get("tool"), arguments=event.get("arguments", {}))
        entry["requires_approval"] = bool(event.get("requires_approval"))
    elif kind == "tool_result":
        entry["tool"] = event.get("tool")
        for key in (
            "found",
            "sources",
            "booked",
            "cancelled",
            "created",
            "tier",
            "score",
            "rejected",
            "is_error",
        ):
            if key in event:
                entry[key] = event[key]
    elif kind == "approval_requested":
        entry.update(tool=event.get("tool"), summary=event.get("summary"), warnings=event.get("warnings", []))
    elif kind == "approval_decision":
        entry.update(
            tool=event.get("tool"),
            approved=bool(event.get("approved")),
            decided_by=event.get("decided_by"),
            reason=event.get("reason", ""),
        )
    elif kind == "guardrail":
        entry.update(kind=event.get("kind"), matches=event.get("matches", []))
    elif kind == "handoff":
        entry.update(reason=event.get("reason"), summary=event.get("summary"))
    elif kind == "error":
        entry["detail"] = event.get("detail") or event.get("error", "")
    return entry


def _outcomes(events: list[dict]) -> list[str]:
    tags = []
    results = [e for e in events if e["type"] == "tool_result"]
    if any(e.get("booked") for e in results):
        tags.append("booked")
    if any(e.get("cancelled") for e in results):
        tags.append("cancelled")
    if any(e["type"] == "approval_decision" and not e.get("approved") for e in events):
        tags.append("rejected")
    requested = {e.get("call_id") for e in events if e["type"] == "approval_requested"}
    decided = {e.get("call_id") for e in events if e["type"] == "approval_decision"}
    if requested - decided:
        tags.append("pending approval")
    if any(e["type"] == "handoff" for e in events):
        tags.append("handed to human")
    if any(e["type"] == "guardrail" for e in events):
        tags.append("guardrail")
    if any(e.get("tool") == "search_knowledge" and e.get("found") is False for e in results):
        tags.append("I don't know")
    return tags or ["answered"]


def build_snapshot(log_dir: Path, state_dir: Path, recorded_on: date | None = None) -> dict:
    events = read_events(log_dir)
    sessions: dict[str, list[dict]] = {}
    for event in events:
        sessions.setdefault(event["session_id"], []).append(event)
    for evs in sessions.values():
        evs.sort(key=lambda e: e["seq"])

    leads = json.loads((state_dir / "leads.json").read_text(encoding="utf-8"))["leads"]
    calendar = json.loads((state_dir / "calendar.json").read_text(encoding="utf-8"))
    lead_names = {lead["id"]: lead["name"] for lead in leads}
    slots = {s["id"]: s for s in calendar["slots"]}

    # ---- approvals: pending = requested but never decided (e.g. the caller hung up)
    approvals = []
    for sid, evs in sorted(sessions.items()):
        decisions = {e["call_id"]: e for e in evs if e["type"] == "approval_decision"}
        for request in (e for e in evs if e["type"] == "approval_requested"):
            decision = decisions.get(request["call_id"])
            status = (
                "pending" if decision is None else ("approved" if decision.get("approved") else "rejected")
            )
            approvals.append(
                {
                    "session_id": sid,
                    "tool": request.get("tool"),
                    "summary": request.get("summary"),
                    "status": status,
                    "decided_by": decision.get("decided_by") if decision else None,
                    "reason": (decision or {}).get("reason", ""),
                    "warnings": request.get("warnings", []),
                }
            )
    approval_counts = Counter(a["status"] for a in approvals)

    # ---- knowledge (RAG)
    knowledge_queries = []
    source_counts: Counter[str] = Counter()
    for sid, evs in sorted(sessions.items()):
        calls = {e["call_id"]: e for e in evs if e["type"] == "tool_call"}
        for result in (e for e in evs if e["type"] == "tool_result" and e.get("tool") == "search_knowledge"):
            query = calls.get(result["call_id"], {}).get("arguments", {}).get("query", "")
            source_counts.update(result.get("sources", []))
            knowledge_queries.append(
                {
                    "session_id": sid,
                    "query": query,
                    "found": bool(result.get("found")),
                    "sources": result.get("sources", []),
                }
            )

    results = [e for e in events if e["type"] == "tool_result"]
    session_list = []
    for sid, evs in sorted(sessions.items()):
        start = next((e for e in evs if e["type"] == "session_start"), {})
        session_list.append(
            {
                "id": sid,
                "title": start.get("scene") or sid,
                "model": start.get("model", ""),
                "caller_turns": sum(e["type"] == "caller" for e in evs),
                "tool_calls": sum(e["type"] == "tool_call" for e in evs),
                "outcomes": _outcomes(evs),
                "transcript": [_transcript_entry(e) for e in evs if e["type"] in TRANSCRIPT_TYPES],
            }
        )

    tiers = Counter(lead.get("tier") or "unscored" for lead in leads)
    statuses = Counter(lead["status"] for lead in leads)
    appointments = []
    for appt in sorted(calendar["appointments"], key=lambda a: a["id"]):
        slot = slots.get(appt["slot_id"], {})
        appointments.append(
            {
                "id": appt["id"],
                "lead_id": appt["lead_id"],
                "lead_name": lead_names.get(appt["lead_id"], ""),
                "service": appt["service"],
                "start": slot.get("start"),
                "staff": slot.get("staff"),
                "status": appt["status"],
            }
        )

    return {
        "version": SNAPSHOT_VERSION,
        "meta": {
            "demo": True,
            "notice": NOTICE,
            "company": "Oakleaf Home Services (fictional)",
            "source": "voice-agent demo (scripted calls, recorded by scripts/export_demo_snapshot.py)",
            "recorded_on": (recorded_on or date.today()).isoformat(),
            "timezone": calendar.get("timezone"),
        },
        "kpis": {
            "calls_handled": len(sessions),
            "caller_turns": sum(e["type"] == "caller" for e in events),
            "tool_calls": sum(e["type"] == "tool_call" for e in events),
            "appointments_booked": sum(1 for e in results if e.get("booked")),
            "appointments_cancelled": sum(1 for e in results if e.get("cancelled")),
            "handoffs": sum(e["type"] == "handoff" for e in events),
            "guardrail_hits": sum(e["type"] == "guardrail" for e in events),
            "knowledge_searches": len(knowledge_queries),
            "knowledge_not_found": sum(1 for q in knowledge_queries if not q["found"]),
            "approvals": {k: approval_counts.get(k, 0) for k in ("approved", "rejected", "pending")},
        },
        "leads": {
            "total": len(leads),
            "by_tier": {k: tiers.get(k, 0) for k in ("hot", "warm", "cold", "unscored")},
            "by_status": dict(sorted(statuses.items(), key=lambda kv: (-kv[1], kv[0]))),
            "rows": [
                {
                    "id": lead["id"],
                    "name": lead["name"],
                    "company": lead.get("company"),
                    "service": lead["service_interest"],
                    "status": lead["status"],
                    "tier": lead.get("tier"),
                    "score": lead.get("score"),
                    "source": lead["source"],
                }
                for lead in leads
            ],
        },
        "appointments": appointments,
        "approvals": approvals,
        "knowledge": {
            "sources": [
                {"title": t, "uses": n}
                for t, n in sorted(source_counts.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
            "queries": knowledge_queries,
        },
        "sessions": session_list,
    }


def write_snapshot(snapshot: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
