"""Deterministic lead scoring: budget, timeline, service fit and contact details (0 to 100).

Every point is explained in `reasons`, so a human reviewer can check the score.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..data_models import Lead, LeadTier

SERVICES = (
    "AC repair",
    "Furnace installation",
    "Plumbing repair",
    "Water heater installation",
    "Electrical inspection",
    "Duct cleaning",
    "Annual maintenance plan",
)
TIMELINES = ("this_week", "this_month", "next_quarter", "just_researching")

HOT_THRESHOLD = 70
WARM_THRESHOLD = 40

_TIMELINE_POINTS = {"this_week": 30, "this_month": 22, "next_quarter": 12, "just_researching": 3}


@dataclass(frozen=True)
class Qualification:
    score: int
    tier: LeadTier
    reasons: list[str]


def tier_for(score: int) -> LeadTier:
    if score >= HOT_THRESHOLD:
        return LeadTier.HOT
    if score >= WARM_THRESHOLD:
        return LeadTier.WARM
    return LeadTier.COLD


def _budget_points(budget: int) -> int:
    if budget >= 2500:
        return 40
    if budget >= 1000:
        return 30
    if budget >= 300:
        return 20
    if budget > 0:
        return 10
    return 0


def score_lead(lead: Lead) -> Qualification:
    reasons = []

    budget = _budget_points(lead.budget_usd)
    reasons.append(f"budget ${lead.budget_usd}: +{budget}")

    timeline = _TIMELINE_POINTS.get(lead.timeline, 0)
    reasons.append(f"timeline {lead.timeline}: +{timeline}")

    fit = 15 if lead.service_interest in SERVICES else 0
    reasons.append(f"service '{lead.service_interest}' {'is' if fit else 'is not'} offered: +{fit}")

    contact = 15 if lead.email and lead.phone else 8
    reasons.append(f"contact details: +{contact}")

    score = min(100, budget + timeline + fit + contact)
    return Qualification(score=score, tier=tier_for(score), reasons=reasons)
