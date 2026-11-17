"""The dummy data must be valid, complete and clearly fictional."""

from __future__ import annotations

import json
import re
from collections import Counter

import pytest
from pydantic import ValidationError

from voice_agent.config import DATA_DIR
from voice_agent.data_models import Lead, list_knowledge_files, load_calendar, load_leads


@pytest.fixture(scope="module")
def leads():
    return load_leads()


@pytest.fixture(scope="module")
def calendar():
    return load_calendar()


def test_exactly_25_leads_with_unique_ids(leads):
    assert len(leads) == 25
    assert len({lead.id for lead in leads}) == 25
    assert len({lead.email for lead in leads}) == 25
    assert len({lead.phone for lead in leads}) == 25


def test_leads_cover_every_status(leads):
    statuses = Counter(lead.status.value for lead in leads)
    assert set(statuses) == {"new", "contacted", "qualified", "unqualified", "booked"}


def test_scored_leads_have_consistent_tiers(leads):
    for lead in leads:
        if lead.score is None:
            continue
        expected = "hot" if lead.score >= 70 else "warm" if lead.score >= 40 else "cold"
        assert lead.tier.value == expected, lead.id


def test_contact_details_are_fictional(leads):
    for lead in leads:
        assert lead.email.endswith("@example.com")
        assert re.fullmatch(r"\+1-\d{3}-555-01\d{2}", lead.phone)


def test_lead_schema_rejects_real_looking_contacts():
    base = json.loads((DATA_DIR / "leads.json").read_text())["leads"][0]
    with pytest.raises(ValidationError):
        Lead.model_validate({**base, "email": "someone@gmail.com"})
    with pytest.raises(ValidationError):
        Lead.model_validate({**base, "phone": "+1-312-867-5309"})
    with pytest.raises(ValidationError):
        Lead.model_validate({**base, "score": None})  # tier without score


def test_calendar_has_availability_and_valid_bookings(calendar):
    available = [s for s in calendar.slots if s.available]
    assert len(calendar.slots) >= 50
    assert len(available) >= 30
    for slot in calendar.slots:
        assert slot.start.weekday() < 5, "no weekend slots"
        assert 9 <= slot.start.hour < 17 and slot.start.hour != 12
    booked_slot_ids = {a.slot_id for a in calendar.appointments}
    assert booked_slot_ids.isdisjoint({s.id for s in available})


def test_appointments_reference_booked_leads(calendar, leads):
    by_id = {lead.id: lead for lead in leads}
    assert calendar.appointments, "demo needs at least one existing appointment"
    for appt in calendar.appointments:
        assert by_id[appt.lead_id].status.value == "booked"


def test_knowledge_base_has_8_to_10_short_documents():
    docs = list_knowledge_files()
    assert 8 <= len(docs) <= 10
    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---\ntitle: "), f"{path.name} needs front matter with a title"
        assert len(text.split()) < 400, f"{path.name} should be short"
        assert "fictional" in text.lower() or path.name != "01-company-overview.md"


def test_generator_is_deterministic(tmp_path, monkeypatch):
    from conftest import load_script

    gen = load_script("generate_dummy_data")
    monkeypatch.setattr(gen, "DATA_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["generate_dummy_data.py"])
    gen.main()
    for name in ("leads.json", "calendar.json"):
        assert (tmp_path / name).read_text() == (DATA_DIR / name).read_text(), name
