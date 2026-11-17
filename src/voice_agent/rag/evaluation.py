"""Measure retrieval quality on the labelled questions in data/rag_eval.json.

- answer_rate: answerable questions for which retrieval returned found=true
- hit_at_k: answered questions whose passages include an expected source
- refusal_rate: out-of-knowledge questions for which retrieval returned found=false (must be 1.0)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .retriever import KnowledgeBase


@dataclass
class EvalReport:
    answerable: int = 0
    answered: int = 0
    hits: int = 0
    unanswerable: int = 0
    refused: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def answer_rate(self) -> float:
        return self.answered / self.answerable if self.answerable else 1.0

    @property
    def hit_at_k(self) -> float:
        return self.hits / self.answered if self.answered else 1.0

    @property
    def refusal_rate(self) -> float:
        return self.refused / self.unanswerable if self.unanswerable else 1.0

    def summary(self) -> str:
        return (
            f"answered {self.answered}/{self.answerable} answerable questions "
            f"(source in results for {self.hits}/{self.answered}); "
            f"refused {self.refused}/{self.unanswerable} out-of-knowledge questions"
        )


def load_eval_set(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["questions"]


def evaluate(kb: KnowledgeBase, questions: list[dict], k: int = 3) -> EvalReport:
    report = EvalReport()
    for item in questions:
        result = kb.search(item["q"], k=k)
        expected = set(item["expected"])
        sources = {p["source"] for p in result["passages"]}
        if expected:
            report.answerable += 1
            if not result["found"]:
                report.failures.append(f"not answered ({result['best_score']}): {item['q']}")
                continue
            report.answered += 1
            if sources & expected:
                report.hits += 1
            else:
                report.failures.append(f"wrong source {sorted(sources)}: {item['q']}")
        else:
            report.unanswerable += 1
            if result["found"]:
                report.failures.append(f"should not answer ({result['best_score']}): {item['q']}")
            else:
                report.refused += 1
    return report
