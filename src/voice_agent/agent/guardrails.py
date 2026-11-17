"""Guardrails shared by text and voice mode.

- Caller text is untrusted: it is wrapped in a <caller_message> envelope with its angle brackets
  escaped, so a caller cannot close the envelope or fake a system message.
- A heuristic detector flags likely prompt-injection attempts. A hit does not block the call (the
  caller may still have a real request); it is logged, marked on the envelope, and shown to the
  human approver for the rest of the session.
- `request_human` lets the agent escalate to a person at any time.
"""

from __future__ import annotations

import html
import re

from agents import RunContextWrapper, function_tool

from ..observability import SessionLogger

MAX_CALLER_CHARS = 2000

_INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (all |any |the |your )?(previous |prior )?(instructions|rules)",
    r"(reveal|show|print|repeat) (me )?(your|the) (system )?(prompt|instructions)",
    r"\byou are now\b",
    r"\b(developer|admin|god|jailbreak) mode\b",
    r"\bsystem prompt\b",
    r"(auto[- ]?approve|approve (it|this|everything) (yourself|automatically)|skip (the )?approval)",
    r"</?\s*(system|caller_message|assistant|developer)\b",
    r"\bact as\b.*\b(admin|manager|developer)\b",
]
_INJECTION_RE = re.compile("|".join(f"(?:{p})" for p in _INJECTION_PATTERNS), re.IGNORECASE)


def detect_injection(text: str) -> list[str]:
    """Return the suspicious fragments found in caller text (empty list if none)."""
    return [m.group(0) for m in _INJECTION_RE.finditer(text or "")][:5]


def wrap_caller_text(text: str, suspected_injection: bool = False) -> str:
    """Put caller text in an envelope the model is told to treat as data."""
    text = (text or "").strip()
    if len(text) > MAX_CALLER_CHARS:
        text = text[:MAX_CALLER_CHARS] + " [truncated]"
    flag = ' suspected_injection="true"' if suspected_injection else ""
    return f"<caller_message{flag}>{html.escape(text, quote=False)}</caller_message>"


HANDOFF_REPLY = (
    "A team member has been notified with your summary and will call the caller back during "
    "business hours (Monday to Friday, 8 a.m. to 6 p.m. Central). Tell the caller this."
)


class AgentContext:
    """Per-session context passed to local tools."""

    def __init__(self, logger: SessionLogger) -> None:
        self.logger = logger
        self.handoffs: list[dict] = []


@function_tool
def request_human(ctx: RunContextWrapper[AgentContext], reason: str, summary: str) -> str:
    """Escalate the call to a human team member.

    Args:
        reason: Why a human is needed, for example "caller asked for a person" or "emergency".
        summary: Two or three sentences summarising the caller's situation and what they need.
    """
    record = {"reason": reason[:300], "summary": summary[:1000]}
    ctx.context.handoffs.append(record)
    ctx.context.logger.log("handoff", **record)
    return HANDOFF_REPLY
