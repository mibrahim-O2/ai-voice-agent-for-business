"""Load knowledge documents (Markdown with a small front-matter block) and split them into chunks.

Chunking is structure-aware: each `#`/`##` section is split into paragraphs (a table or a list
counts as one paragraph), and paragraphs are packed into chunks of at most MAX_CHUNK_CHARS. Each
chunk remembers its document title, section heading and source file, so answers can cite it.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_CHUNK_CHARS = 600
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")


class DocumentError(ValueError):
    """A knowledge document is malformed."""


@dataclass(frozen=True)
class Document:
    source: str  # file name, e.g. "02-business-hours.md"
    title: str
    category: str
    body: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(f"{self.title}\n{self.category}\n{self.body}".encode()).hexdigest()


@dataclass(frozen=True)
class Chunk:
    id: str  # "<source>#<n>"
    source: str
    title: str
    section: str
    text: str

    def embedding_text(self) -> str:
        """What gets embedded: the location in the document gives short chunks useful context."""
        return f"{self.title} > {self.section}\n{self.text}"

    def to_dict(self) -> dict:
        return asdict(self)


def load_document(path: Path) -> Document:
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = _FRONT_MATTER.match(raw)
    if not match:
        raise DocumentError(f"{path.name}: missing front matter (--- title: ... ---)")
    meta = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    if not meta.get("title"):
        raise DocumentError(f"{path.name}: front matter needs a title")
    body = raw[match.end() :].strip()
    if not body:
        raise DocumentError(f"{path.name}: document body is empty")
    return Document(
        source=path.name, title=meta["title"], category=meta.get("category", "general"), body=body
    )


def load_documents(directory: Path) -> list[Document]:
    paths = sorted(directory.glob("*.md"))
    if not paths:
        raise DocumentError(f"no .md documents found in {directory}")
    return [load_document(p) for p in paths]


def _sections(doc: Document) -> list[tuple[str, list[str]]]:
    """Split a body into (heading, paragraphs). Text before the first heading uses the title."""
    sections: list[tuple[str, list[str]]] = []
    heading, lines = doc.title, []

    def flush() -> None:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", "\n".join(lines)) if p.strip()]
        if paragraphs:
            sections.append((heading, paragraphs))

    for line in doc.body.split("\n"):
        m = _HEADING.match(line)
        if m:
            flush()
            heading, lines = m.group(2).strip(), []
        else:
            lines.append(line)
    flush()
    return sections


def _split_long(paragraph: str, limit: int) -> list[str]:
    """Split an over-long paragraph on line, then sentence, boundaries."""
    if len(paragraph) <= limit:
        return [paragraph]
    pieces = re.split(r"(?<=\n)|(?<=[.!?])\s+", paragraph)
    out, current = [], ""
    for piece in pieces:
        if current and len(current) + len(piece) + 1 > limit:
            out.append(current.strip())
            current = ""
        current = f"{current} {piece}" if current else piece
        while len(current) > limit:  # a single piece longer than the limit
            out.append(current[:limit].strip())
            current = current[limit:]
    if current.strip():
        out.append(current.strip())
    return out


def chunk_document(doc: Document, max_chars: int = MAX_CHUNK_CHARS) -> list[Chunk]:
    chunks: list[Chunk] = []
    for heading, paragraphs in _sections(doc):
        current = ""
        pieces = [piece for p in paragraphs for piece in _split_long(p, max_chars)]
        for piece in pieces:
            if current and len(current) + len(piece) + 2 > max_chars:
                chunks.append(Chunk(f"{doc.source}#{len(chunks)}", doc.source, doc.title, heading, current))
                current = ""
            current = f"{current}\n\n{piece}" if current else piece
        if current:
            chunks.append(Chunk(f"{doc.source}#{len(chunks)}", doc.source, doc.title, heading, current))
    return chunks


def chunk_documents(docs: list[Document], max_chars: int = MAX_CHUNK_CHARS) -> list[Chunk]:
    return [chunk for doc in docs for chunk in chunk_document(doc, max_chars)]
