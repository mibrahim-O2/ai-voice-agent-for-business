"""Structured session logs: one JSON object per line in <var_dir>/logs/sessions.jsonl.

Every caller turn, agent reply, tool call, tool result, approval request, approval decision,
guardrail hit and error is an event:

    {"ts": "...", "session_id": "...", "mode": "text", "seq": 3, "type": "tool_call", ...}

Values are redacted before they are written: anything that looks like an API key, a bearer token
or a payment card number is replaced, and long text is truncated. The OpenAI key itself is never
passed to the logger, but redaction also protects against a caller reading one out.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_TEXT = 2000

_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsk-[A-Za-z0-9_\-*]{6,}"), "[REDACTED_KEY]"),
    (
        re.compile(r"\b(?:ghp|gho|ghs|ghu|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"),
        "[REDACTED_KEY]",
    ),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-]{16,}"), "Bearer [REDACTED]"),
    # 13-19 digits, optionally separated by spaces or dashes: payment card numbers
    (re.compile(r"\b(?:\d[ -]?){12,18}\d\b"), "[REDACTED_CARD]"),
]

EVENT_TYPES = frozenset(
    {
        "session_start",
        "session_end",
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
)


def redact_text(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + f"... [truncated {len(text) - MAX_TEXT} chars]"
    return text


def redact(value: Any) -> Any:
    """Recursively redact strings inside dicts and lists."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {str(k): redact(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    if value is None or isinstance(value, bool | int | float):
        return value
    return redact_text(str(value))


class SessionLogger:
    """Appends redacted events for one call/session. Safe to use from several threads."""

    def __init__(self, log_dir: Path, mode: str, session_id: str | None = None) -> None:
        self.session_id = session_id or f"S{datetime.now(UTC):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"
        self.mode = mode
        self.path = log_dir / "sessions.jsonl"
        log_dir.mkdir(parents=True, exist_ok=True)
        self._seq = 0
        self._lock = threading.Lock()
        self.events: list[dict] = []  # in-memory copy, used by tests and the CLI summary

    def log(self, event_type: str, **fields: Any) -> dict:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {event_type!r}")
        with self._lock:
            self._seq += 1
            event = {
                "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "session_id": self.session_id,
                "mode": self.mode,
                "seq": self._seq,
                "type": event_type,
                **redact(fields),
            }
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            self.events.append(event)
            return event


def read_events(log_dir: Path, session_id: str | None = None) -> list[dict]:
    """Read events back (skipping malformed lines), optionally for one session."""
    path = log_dir / "sessions.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and (session_id is None or event.get("session_id") == session_id):
            events.append(event)
    return events
