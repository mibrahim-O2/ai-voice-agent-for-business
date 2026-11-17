"""A tiny local vector store: chunk metadata in JSON, vectors in a .npy file, one folder per provider.

    var/index/<provider>/manifest.json   embedder name and state, source hashes, chunk metadata
    var/index/<provider>/vectors.npy     float32 matrix, one unit-length row per chunk

The manifest records a hash of every source document. If the knowledge base changes, the index is
reported as stale: the local index is then rebuilt automatically (it is free and fast), and the
OpenAI index asks you to run `voice-agent ingest --provider openai`, so that no API calls happen
without you asking for them.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from .documents import Chunk, chunk_documents, load_documents
from .embeddings import Embedder

FORMAT_VERSION = 1


class IndexError_(RuntimeError):  # noqa: N801 - avoid shadowing the builtin IndexError
    """The index is missing, stale or unreadable."""


@dataclass
class VectorIndex:
    embedder: Embedder
    chunks: list[Chunk] = field(default_factory=list)
    vectors: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=np.float32))
    source_hashes: dict[str, str] = field(default_factory=dict)
    built_at: str = ""

    # ---------- build ----------
    @classmethod
    def build(cls, knowledge_dir: Path, embedder: Embedder) -> VectorIndex:
        docs = load_documents(knowledge_dir)
        chunks = chunk_documents(docs)
        texts = [c.embedding_text() for c in chunks]
        embedder.fit(texts)
        vectors = embedder.embed(texts)
        return cls(
            embedder=embedder,
            chunks=chunks,
            vectors=vectors,
            source_hashes={d.source: d.sha256 for d in docs},
            built_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        )

    # ---------- persistence ----------
    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        manifest = {
            "format_version": FORMAT_VERSION,
            "embedder": self.embedder.name,
            "embedder_state": self.embedder.state(),
            "built_at": self.built_at,
            "source_hashes": self.source_hashes,
            "chunks": [c.to_dict() for c in self.chunks],
        }
        # vectors first, manifest last: a manifest on disk always has matching vectors
        _atomic_write_bytes(directory / "vectors.npy", _npy_bytes(self.vectors))
        _atomic_write_bytes(directory / "manifest.json", json.dumps(manifest).encode("utf-8"))

    @classmethod
    def load(cls, directory: Path, embedder: Embedder) -> VectorIndex:
        manifest_path, vectors_path = directory / "manifest.json", directory / "vectors.npy"
        if not manifest_path.exists() or not vectors_path.exists():
            raise IndexError_(f"no index in {directory}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            vectors = np.load(vectors_path, allow_pickle=False)
        except (OSError, ValueError) as exc:
            raise IndexError_(f"index in {directory} is unreadable: {exc}") from exc
        if manifest.get("format_version") != FORMAT_VERSION:
            raise IndexError_("index format has changed; rebuild it")
        if manifest.get("embedder") != embedder.name:
            raise IndexError_(f"index was built with {manifest.get('embedder')}, not {embedder.name}")
        embedder.load_state(manifest["embedder_state"])
        chunks = [Chunk(**c) for c in manifest["chunks"]]
        if vectors.shape[0] != len(chunks):
            raise IndexError_("index vectors and chunks do not match; rebuild it")
        return cls(embedder, chunks, vectors, manifest["source_hashes"], manifest.get("built_at", ""))

    def is_stale(self, knowledge_dir: Path) -> bool:
        current = {d.source: d.sha256 for d in load_documents(knowledge_dir)}
        return current != self.source_hashes

    # ---------- search ----------
    def search(self, query: str, k: int) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        q = self.embedder.embed([query])[0]
        scores = self.vectors @ q
        order = np.argsort(-scores, kind="stable")[:k]
        return [(self.chunks[i], float(scores[i])) for i in order]


def _npy_bytes(array: np.ndarray) -> bytes:
    import io

    buf = io.BytesIO()
    np.save(buf, array.astype(np.float32), allow_pickle=False)
    return buf.getvalue()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
