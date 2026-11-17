"""Command-line entry point: `voice-agent <command>`.

Commands: version, validate-data, tools, reset-data, mcp, ingest, ask, rag-eval.
Task 4 adds text and voice.
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


def _open_kb(provider: str | None):
    from .config import load_settings
    from .rag import KnowledgeBase

    settings = load_settings()
    provider = provider or settings.embeddings_provider
    kb = KnowledgeBase.open(
        settings.data_dir / "knowledge",
        settings.var_dir / "index",
        provider=provider,
        api_key=settings.openai_api_key if provider == "openai" else None,
    )
    return settings, provider, kb


def _ingest(provider: str | None) -> int:
    from .config import ConfigError, load_settings
    from .rag import VectorIndex, make_embedder
    from .rag.documents import DocumentError

    settings = load_settings()
    provider = provider or settings.embeddings_provider
    try:
        api_key = settings.require_openai_key() if provider == "openai" else None
        embedder = make_embedder(provider, api_key=api_key)
        index = VectorIndex.build(settings.data_dir / "knowledge", embedder)
    except (ConfigError, DocumentError) as exc:
        print(f"Ingest failed: {exc}", file=sys.stderr)
        return 1
    directory = settings.var_dir / "index" / provider
    index.save(directory)
    print(f"Indexed {len(index.source_hashes)} documents as {len(index.chunks)} chunks with {embedder.name}")
    if provider == "openai":
        print(f"OpenAI embedding requests made: {embedder.calls}")
    print(f"Saved to {directory}")
    return 0


def _ask(question: str, provider: str | None, k: int) -> int:
    from .rag import KnowledgeBaseError

    try:
        _, provider, kb = _open_kb(provider)
        result = kb.search(question, k=k)
    except (KnowledgeBaseError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not result["found"]:
        print(
            f"I don't know: nothing relevant in the knowledge base (best score {result['best_score']}, "
            f"needs {result['min_score']})."
        )
        return 0
    for n, p in enumerate(result["passages"], start=1):
        print(f"[{n}] {p['title']} > {p['section']}  (source: {p['source']}, score {p['score']})")
        print("    " + p["text"].replace("\n", "\n    "))
    return 0


def _rag_eval(provider: str | None) -> int:
    from .rag import KnowledgeBaseError
    from .rag.evaluation import evaluate, load_eval_set

    try:
        settings, provider, kb = _open_kb(provider)
    except KnowledgeBaseError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    report = evaluate(kb, load_eval_set(settings.data_dir / "rag_eval.json"))
    print(f"[{provider}, min_score {kb.min_score}] {report.summary()}")
    for failure in report.failures:
        print(f"  - {failure}")
    return 0 if report.refusal_rate == 1.0 else 1


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
    ingest = sub.add_parser("ingest", help="build the knowledge-base index (RAG)")
    ingest.add_argument("--provider", choices=["local", "openai"], help="default: EMBEDDINGS_PROVIDER")
    ask = sub.add_parser("ask", help="search the knowledge base and print passages with sources")
    ask.add_argument("question")
    ask.add_argument("--provider", choices=["local", "openai"])
    ask.add_argument("-k", type=int, default=3, help="passages to return (1-5)")
    rag_eval = sub.add_parser("rag-eval", help="measure retrieval on data/rag_eval.json")
    rag_eval.add_argument("--provider", choices=["local", "openai"])
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
    if args.command == "ingest":
        return _ingest(args.provider)
    if args.command == "ask":
        return _ask(args.question, args.provider, args.k)
    if args.command == "rag-eval":
        return _rag_eval(args.provider)
    parser.error(f"unknown command {args.command}")  # pragma: no cover
    return 2  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
