"""Embedders turn text into unit-length vectors, so cosine similarity is a dot product.

- LocalEmbedder: offline and deterministic. It uses TF-IDF over hashed word unigrams and bigrams,
  with IDF learned from the knowledge base at ingest time. Words the knowledge base never uses get
  the highest IDF, so a question about something the business doesn't cover ("roof repair") scores
  low even when it shares a common word ("repair") with the documents. Word pairs (bigrams) only
  count when the knowledge base contains them: they reward exact phrases but never add noise.
- OpenAIEmbedder: `text-embedding-3-small` through the OpenAI API (needs OPENAI_API_KEY).
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Any, Protocol

import numpy as np

STOPWORDS = frozenset(
    """
    a about above after again all am an and any are as at be because been before being below
    between both but by can could did do does doing down during each few for from further had
    has have having he her here hers him his how i if in into is it its itself just me more most
    my no nor not now of off on once only or other our ours out over own same she should so some
    such than that the their theirs them then there these they this those through to too under
    until up very was we were what when where which while who whom why will with would you your
    yours yourself please hi hello thanks thank tell know want like get got also may might real
    actual
    """.split()  # noqa: SIM905 - a word list reads better as text
)

_TOKEN = re.compile(r"[a-z0-9]+")

# A small, explicit vocabulary bridge for words that callers say but documents spell differently.
# Applied to documents and queries alike (after stemming), so it never favours one side.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "weekday": ("monday", "friday"),
    "weekend": ("saturday", "sunday"),
    "sold": ("sell",),
    "cost": ("price",),
    "much": ("price",),
    "charge": ("price",),
    "open": ("hour",),
    "close": ("hour",),
    "human": ("person",),
    "people": ("person",),
    "robot": ("ai",),
    "bot": ("ai",),
    "artificial": ("ai",),
    "reschedule": ("cancel",),
    "refund": ("payment",),
    "pay": ("payment",),
    "leak": ("water", "leak"),
}


def _stem(word: str) -> str:
    """A deliberately tiny stemmer: enough to match 'repairs'/'repair', 'services'/'service' and
    'booking'/'booked'/'book'. It never shortens words below four letters."""
    if len(word) <= 4:
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("sses"):
        return word[:-2]
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)]
            if len(word) > 4 and word[-1] == word[-2] and word[-1] not in "ls":  # stopp(ed) -> stop
                word = word[:-1]
            return word
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    tokens = []
    for raw in _TOKEN.findall(text.lower()):
        if raw in STOPWORDS:
            continue
        stem = _stem(raw)
        tokens.append(stem)
        tokens.extend(s for s in SYNONYMS.get(stem, ()) if s != stem)
    return tokens


def features(text: str) -> Counter[str]:
    tokens = tokenize(text)
    feats = Counter(tokens)
    feats.update(f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False))
    return feats


def _bucket(feature: str, dim: int) -> int:
    digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
    return int.from_bytes(digest, "little") % dim


def _normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


class EmbeddingError(RuntimeError):
    """An embedding request failed. The message never includes the provider's error text, which
    can contain a partly masked API key."""


class Embedder(Protocol):
    name: str
    #: Minimum cosine similarity for a passage to count as relevant (calibrated per embedder).
    default_min_score: float

    def fit(self, texts: list[str]) -> None: ...
    def embed(self, texts: list[str]) -> np.ndarray: ...
    def state(self) -> dict[str, Any]: ...
    def load_state(self, state: dict[str, Any]) -> None: ...


class LocalEmbedder:
    name = "local-tfidf-v1"
    # Calibrated on data/rag_eval.json: every out-of-scope question scores <= 0.091 and all but one
    # answerable question >= 0.14. Erring high is deliberate: a missed answer becomes "I don't know"
    # (safe), whereas a low threshold would let the agent answer from an unrelated passage.
    default_min_score = 0.115

    def __init__(self, dim: int = 16384) -> None:
        self.dim = dim
        self.idf: np.ndarray | None = None
        self.max_idf = 1.0

    def fit(self, texts: list[str]) -> None:
        if not texts:
            raise ValueError("cannot fit on an empty corpus")
        df = np.zeros(self.dim, dtype=np.float64)
        for text in texts:
            for bucket in {_bucket(f, self.dim) for f in features(text)}:
                df[bucket] += 1
        n = len(texts)
        self.idf = np.log((1 + n) / (1 + df)) + 1.0  # unseen features get the highest weight
        self.max_idf = float(math.log(1 + n) + 1.0)

    def embed(self, texts: list[str]) -> np.ndarray:
        if self.idf is None:
            raise RuntimeError("LocalEmbedder.fit() must run before embed()")
        unseen = self.idf >= self.max_idf - 1e-9  # buckets no knowledge chunk uses
        matrix = np.zeros((len(texts), self.dim), dtype=np.float64)
        for row, text in enumerate(texts):
            for feature, count in features(text).items():
                bucket = _bucket(feature, self.dim)
                if "_" in feature and unseen[bucket]:
                    continue  # an unknown word pair carries no evidence either way
                matrix[row, bucket] += 1.0 + math.log(count)
        return _normalise(matrix * self.idf)

    def state(self) -> dict[str, Any]:
        """Only the buckets the corpus uses are stored; every other bucket has max_idf."""
        if self.idf is None:
            return {"dim": self.dim, "max_idf": self.max_idf, "idf": {}}
        used = np.flatnonzero(self.idf < self.max_idf - 1e-9)
        return {
            "dim": self.dim,
            "max_idf": self.max_idf,
            "idf": {str(i): round(float(self.idf[i]), 6) for i in used},
        }

    def load_state(self, state: dict[str, Any]) -> None:
        try:
            self.dim = int(state["dim"])
            self.max_idf = float(state["max_idf"])
            idf = np.full(self.dim, self.max_idf, dtype=np.float64)
            for key, value in state["idf"].items():
                idf[int(key)] = float(value)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ValueError("corrupt local embedder state") from exc
        self.idf = idf


class OpenAIEmbedder:
    name = "openai-text-embedding-3-small"
    # Calibrated live on data/rag_eval.json (2026-11): out-of-scope questions scored <= 0.366
    # ("Do you repair cars?"), answerable ones >= 0.364, all but one >= 0.395. Semantic embeddings
    # place "repair cars" close to "repairs", so the threshold is only a first filter: the agent's
    # instructions also require it to check that a passage actually answers the question.
    default_min_score = 0.38
    model = "text-embedding-3-small"
    batch_size = 96

    def __init__(self, client: Any | None = None, api_key: str | None = None) -> None:
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
        self.client = client
        self.calls = 0  # API requests made, so callers can report usage

    def fit(self, texts: list[str]) -> None:  # nothing to learn locally
        return None

    def embed(self, texts: list[str]) -> np.ndarray:
        rows: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = [t.replace("\n", " ") for t in texts[start : start + self.batch_size]]
            self.calls += 1
            try:
                response = self.client.embeddings.create(model=self.model, input=batch)
            except Exception as exc:  # noqa: BLE001 - any client failure becomes one safe error
                status = getattr(exc, "status_code", None)
                detail = f"{type(exc).__name__}" + (f", HTTP {status}" if status else "")
                hint = " Check OPENAI_API_KEY." if status in (401, 403) else ""
                # `from None`: the original exception (and its message) must not be chained into logs
                raise EmbeddingError(f"OpenAI embeddings request failed ({detail}).{hint}") from None
            rows.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
        return _normalise(np.asarray(rows, dtype=np.float64))

    def state(self) -> dict[str, Any]:
        return {"model": self.model}

    def load_state(self, state: dict[str, Any]) -> None:
        if state.get("model") != self.model:
            raise ValueError(f"index was built with {state.get('model')!r}, not {self.model!r}")


def make_embedder(provider: str, api_key: str | None = None, client: Any | None = None) -> Embedder:
    if provider == "local":
        return LocalEmbedder()
    if provider == "openai":
        return OpenAIEmbedder(client=client, api_key=api_key)
    raise ValueError(f"unknown embeddings provider {provider!r}; use 'local' or 'openai'")
