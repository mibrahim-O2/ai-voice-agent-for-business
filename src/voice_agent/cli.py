"""Command-line entry point: `voice-agent <command>`.

Task 1 ships `version` and `validate-data`. Later tasks add `mcp`, `ingest`, `text` and `voice`.
"""

from __future__ import annotations

import argparse
import sys

from pydantic import ValidationError

from . import __version__
from .data_models import list_knowledge_files, load_calendar, load_leads


def _validate_data() -> int:
    try:
        leads = load_leads()
        calendar = load_calendar()
    except (OSError, ValueError, ValidationError) as exc:
        print(f"Data validation failed: {exc}", file=sys.stderr)
        return 1
    docs = list_knowledge_files()
    free = sum(1 for s in calendar.slots if s.available)
    print(f"leads: {len(leads)}")
    print(f"calendar slots: {len(calendar.slots)} ({free} available), appointments: {len(calendar.appointments)}")
    print(f"knowledge documents: {len(docs)}")
    print("OK: all dummy data is valid")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voice-agent", description="AI voice agent (demo data only)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="print the version")
    sub.add_parser("validate-data", help="check the dummy data files against their schemas")
    args = parser.parse_args(argv)

    if args.command == "version":
        print(__version__)
        return 0
    if args.command == "validate-data":
        return _validate_data()
    parser.error(f"unknown command {args.command}")  # pragma: no cover
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
