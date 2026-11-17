"""Command-line entry point: `voice-agent <command>`.

Commands: version, validate-data, tools, reset-data, mcp. Later tasks add ingest, text and voice.
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
    print(f"calendar slots: {len(calendar.slots)} ({free} available)")
    print(f"appointments: {len(calendar.appointments)}")
    print(f"knowledge documents: {len(docs)}")
    print("OK: all dummy data is valid")
    return 0


def _tools() -> int:
    from .mcp_server.tools import TOOL_POLICIES

    print(f"{'tool':<22} {'sensitive':<10} {'read-only':<10} reason")
    for name, policy in TOOL_POLICIES.items():
        sensitive = "YES" if policy.sensitive else "no"
        read_only = "yes" if policy.read_only else "no"
        print(f"{name:<22} {sensitive:<10} {read_only:<10} {policy.reason}")
    return 0


def _reset_data() -> int:
    from .business import DataStore
    from .config import load_settings

    settings = load_settings()
    store = DataStore(settings.data_dir, settings.var_dir)
    store.reset()
    print(f"Demo CRM and calendar restored from {settings.data_dir} into {store.state_dir}")
    return 0


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _mcp(transport: str, host: str, port: int, allow_remote: bool = False) -> int:
    from .mcp_server import create_default_server

    if transport != "stdio" and host not in LOOPBACK_HOSTS and not allow_remote:
        print(
            f"Refusing to listen on {host}: the MCP HTTP endpoint has no authentication and exposes "
            "tools that change data. Keep it on 127.0.0.1 (the agent runs on the same machine), or "
            "pass --allow-remote only behind an authenticating proxy or private network.",
            file=sys.stderr,
        )
        return 2

    server = create_default_server()
    if transport == "stdio":
        server.run("stdio")  # stdout carries the protocol; never print here
    else:
        print(f"MCP server listening on http://{host}:{port}/mcp", file=sys.stderr)
        server.run("streamable-http", host=host, port=port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voice-agent", description="AI voice agent (demo data only)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="print the version")
    sub.add_parser("validate-data", help="check the dummy data files against their schemas")
    sub.add_parser("tools", help="list the MCP tools and which ones need human approval")
    sub.add_parser("reset-data", help="discard demo changes and restore the shipped CRM and calendar")
    mcp = sub.add_parser("mcp", help="run the MCP server")
    mcp.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    mcp.add_argument("--host", default="127.0.0.1", help="HTTP only; keep 127.0.0.1 unless behind auth")
    mcp.add_argument("--port", type=int, default=8765, help="HTTP only")
    mcp.add_argument(
        "--allow-remote", action="store_true", help="HTTP only; allow a non-loopback host (no built-in auth)"
    )
    args = parser.parse_args(argv)

    if args.command == "version":
        print(__version__)
        return 0
    if args.command == "validate-data":
        return _validate_data()
    if args.command == "tools":
        return _tools()
    if args.command == "reset-data":
        return _reset_data()
    if args.command == "mcp":
        return _mcp(args.transport, args.host, args.port, args.allow_remote)
    parser.error(f"unknown command {args.command}")  # pragma: no cover
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
