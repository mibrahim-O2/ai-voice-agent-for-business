"""Scan the repository (or a diff) for things that look like secrets.

Usage:
    python scripts/check_secrets.py                 # scan every tracked file
    python scripts/check_secrets.py --diff main     # scan only lines added since `main`
    python scripts/check_secrets.py --path dashboard # scan a directory (tracked or not), e.g. a built site

Exit code 0 means nothing was found; 1 means at least one finding (printed without the secret).
"""

from __future__ import annotations

import argparse
import re
import subprocess  # runs fixed git commands only, no shell
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATTERNS: dict[str, re.Pattern[str]] = {
    "OpenAI key": re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Slack token": re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    "Private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "Bearer token": re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{20,}"),
    "Assigned API key": re.compile(
        r"(?i)\b(?:OPENAI_API_KEY|API_KEY|SECRET_KEY|ACCESS_TOKEN)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}"
    ),
}

# Files that must never be tracked.
FORBIDDEN_FILES = re.compile(r"(^|/)\.env($|\.(?!example$)[^/]+$)")
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".npz", ".pdf"}


def scan_text(text: str) -> list[str]:
    """Return the names of the patterns that match anywhere in text."""
    return [name for name, pattern in PATTERNS.items() if pattern.search(text)]


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def iter_tracked() -> Iterable[tuple[str, str]]:
    for rel in _git("ls-files").splitlines():
        path = ROOT / rel
        if path.suffix.lower() in SKIP_SUFFIXES or not path.is_file():
            continue
        yield rel, path.read_text(encoding="utf-8", errors="ignore")


def iter_directory(directory: Path) -> Iterable[tuple[str, str]]:
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix.lower() not in SKIP_SUFFIXES:
            yield str(path.relative_to(directory)), path.read_text(encoding="utf-8", errors="ignore")


def iter_diff(base: str) -> Iterable[tuple[str, str]]:
    current = None
    added: dict[str, list[str]] = {}
    for line in _git("diff", "--unified=0", f"{base}...HEAD").splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif current and line.startswith("+") and not line.startswith("+++"):
            added.setdefault(current, []).append(line[1:])
    for rel, lines in added.items():
        yield rel, "\n".join(lines)


def find_problems(files: Iterable[tuple[str, str]]) -> list[str]:
    problems = []
    for rel, text in files:
        if FORBIDDEN_FILES.search(rel):
            problems.append(f"{rel}: environment file must not be committed")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for name in scan_text(line):
                problems.append(f"{rel}:{line_no}: possible {name}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan for committed secrets.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--diff", metavar="BASE", help="scan only lines added since BASE")
    group.add_argument("--path", type=Path, help="scan every file under a directory")
    args = parser.parse_args(argv)

    if args.diff:
        files, scope = iter_diff(args.diff), f"diff against {args.diff}"
    elif args.path:
        files, scope = iter_directory(args.path), str(args.path)
    else:
        files, scope = iter_tracked(), "tracked files"
    problems = find_problems(files)
    for problem in problems:
        print(problem)
    if problems:
        print(f"FAIL: {len(problems)} possible secret(s) in {scope}")
        return 1
    print(f"OK: no secrets found in {scope}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
