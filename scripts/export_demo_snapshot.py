"""Record the dashboard's demo data: dashboard/demo/snapshot.json.

Runs the scripted demo calls (`voice-agent demo`) on a fresh temporary copy of the demo data,
through the real MCP tools, knowledge base and approval gate, then builds the snapshot from the
session log and the resulting CRM/calendar state. No API key and no network are needed.

Usage:
    python scripts/export_demo_snapshot.py            # writes dashboard/demo/snapshot.json
    python scripts/export_demo_snapshot.py --out x.json
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import tempfile
from pathlib import Path

from voice_agent.agent.demo import run_demo
from voice_agent.config import load_settings
from voice_agent.dashboard_snapshot import build_snapshot, write_snapshot

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "dashboard" / "demo" / "snapshot.json"


def record(out: Path, quiet: bool = True) -> dict:
    with tempfile.TemporaryDirectory(prefix="voice-agent-snapshot-") as tmp:
        settings = dataclasses.replace(load_settings(), var_dir=Path(tmp), openai_api_key=None)
        log_dir = asyncio.run(run_demo(settings, out=(lambda _line: None) if quiet else print))
        snapshot = build_snapshot(log_dir, log_dir.parent / "state")
    write_snapshot(snapshot, out)
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--verbose", action="store_true", help="print the demo calls while recording")
    args = parser.parse_args()
    snapshot = record(args.out, quiet=not args.verbose)
    k = snapshot["kpis"]
    print(
        f"wrote {args.out}: {k['calls_handled']} calls, {k['appointments_booked']} bookings, "
        f"approvals {k['approvals']}"
    )


if __name__ == "__main__":
    main()
