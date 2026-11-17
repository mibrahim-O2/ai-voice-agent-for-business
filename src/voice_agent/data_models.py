"""Typed schemas and loaders for the dummy business data in data/.

Every record is fictional. Phone numbers use the 555-01xx range reserved for fiction and
email addresses use the reserved example.com domain, which tests enforce.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import data_dir

LEAD_ID_RE = re.compile(r"^L-\d{3,}$")
SLOT_ID_RE = re.compile(r"^S-\d{8}-\d{4}$")
APPT_ID_RE = re.compile(r"^A-\d{3,}$")
# Fictional North American numbers: +1-XXX-555-01XX.
FICTIONAL_PHONE_RE = re.compile(r"^\+1-\d{3}-555-01\d{2}$")


class LeadStatus(StrEnum):
    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    UNQUALIFIED = "unqualified"
    BOOKED = "booked"


class LeadTier(StrEnum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: datetime
    author: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=1000)


class Lead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = Field(min_length=1, max_length=100)
    company: str | None = Field(default=None, max_length=120)
    email: str = Field(max_length=200)
    phone: str
    source: str = Field(min_length=1, max_length=40)
    service_interest: str = Field(min_length=1, max_length=80)
    budget_usd: int = Field(ge=0, le=1_000_000)
    timeline: str = Field(min_length=1, max_length=40)
    status: LeadStatus
    score: int | None = Field(default=None, ge=0, le=100)
    tier: LeadTier | None = None
    created_at: datetime
    notes: list[Note] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        if not LEAD_ID_RE.match(v):
            raise ValueError("lead id must look like L-001")
        return v

    @field_validator("email")
    @classmethod
    def _email_fictional(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9._+-]+@example\.com$", v):
            raise ValueError("demo emails must use the reserved example.com domain")
        return v

    @field_validator("phone")
    @classmethod
    def _phone_fictional(cls, v: str) -> str:
        if not FICTIONAL_PHONE_RE.match(v):
            raise ValueError("demo phone numbers must be fictional: +1-XXX-555-01XX")
        return v

    @model_validator(mode="after")
    def _tier_needs_score(self) -> Lead:
        if (self.tier is None) != (self.score is None):
            raise ValueError("score and tier must be set together")
        return self


class Slot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    start: datetime
    end: datetime
    staff: str = Field(min_length=1, max_length=60)
    available: bool

    @field_validator("id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        if not SLOT_ID_RE.match(v):
            raise ValueError("slot id must look like S-20261201-0900")
        return v

    @model_validator(mode="after")
    def _ordered(self) -> Slot:
        if self.end <= self.start:
            raise ValueError("slot end must be after start")
        return self


class Appointment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    lead_id: str
    slot_id: str
    service: str = Field(min_length=1, max_length=80)
    status: str = Field(pattern="^(booked|cancelled)$")
    created_at: datetime

    @field_validator("id")
    @classmethod
    def _id_format(cls, v: str) -> str:
        if not APPT_ID_RE.match(v):
            raise ValueError("appointment id must look like A-001")
        return v


class Calendar(BaseModel):
    """Appointment calendar. Slot datetimes are naive and are local times in `timezone`."""

    model_config = ConfigDict(extra="forbid")

    timezone: str
    slot_minutes: int = Field(gt=0, le=240)
    business_days: list[str]
    start_date: date
    end_date: date
    slots: list[Slot]
    appointments: list[Appointment] = Field(default_factory=list)

    @field_validator("timezone")
    @classmethod
    def _valid_zone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown IANA timezone {v!r}") from exc
        return v

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @model_validator(mode="after")
    def _consistent(self) -> Calendar:
        slot_ids = {s.id for s in self.slots}
        if len(slot_ids) != len(self.slots):
            raise ValueError("duplicate slot ids")
        booked = {a.slot_id for a in self.appointments if a.status == "booked"}
        for a in self.appointments:
            if a.slot_id not in slot_ids:
                raise ValueError(f"appointment {a.id} references unknown slot {a.slot_id}")
        for s in self.slots:
            if s.id in booked and s.available:
                raise ValueError(f"slot {s.id} has a booked appointment but is marked available")
        return self


def load_leads(path: Path | None = None) -> list[Lead]:
    raw = json.loads((path or data_dir() / "leads.json").read_text(encoding="utf-8"))
    return [Lead.model_validate(item) for item in raw["leads"]]


def load_calendar(path: Path | None = None) -> Calendar:
    raw = json.loads((path or data_dir() / "calendar.json").read_text(encoding="utf-8"))
    return Calendar.model_validate(raw)


def list_knowledge_files(directory: Path | None = None) -> list[Path]:
    return sorted((directory or data_dir() / "knowledge").glob("*.md"))
