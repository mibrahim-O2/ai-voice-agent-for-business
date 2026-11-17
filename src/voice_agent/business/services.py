"""CRM and calendar operations behind the MCP tools.

Everything here is transport-independent: it validates input, applies business rules, persists
through DataStore and returns plain JSON-serialisable dicts. Text from callers is treated as
untrusted data: it is length-limited, stripped of control characters and stored, never executed.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

from ..data_models import FICTIONAL_PHONE_RE, Appointment, Lead, LeadStatus, LeadTier, Note
from .errors import Conflict, InvalidInput, NotFound
from .qualification import SERVICES, TIMELINES, score_lead
from .store import DataStore

MAX_SEARCH_RESULTS = 25
MAX_SLOT_RESULTS = 20
MAX_SLOT_RANGE_DAYS = 31
LATE_CANCEL_HOURS = 24
LATE_CANCEL_FEE_USD = 40
SOURCES = ("inbound_call", "website_form", "referral", "google_ads", "facebook_ads")

_EMAIL_RE = re.compile(r"^[a-z0-9._+-]+@example\.com$")
_ID_PATTERNS = {
    "lead_id": re.compile(r"^L-\d{3,6}$"),
    "slot_id": re.compile(r"^S-\d{8}-\d{4}$"),
    "appointment_id": re.compile(r"^A-\d{3,6}$"),
}


# ---------- input cleaning ----------
def clean_text(value: str | None, field: str, *, max_len: int, required: bool = False) -> str | None:
    """Normalise untrusted text: drop control characters, collapse whitespace, enforce length."""
    if value is None:
        if required:
            raise InvalidInput(f"{field} is required")
        return None
    if not isinstance(value, str):
        raise InvalidInput(f"{field} must be text")
    text = "".join(ch for ch in value if unicodedata.category(ch)[0] != "C" or ch in " \t\n")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        if required:
            raise InvalidInput(f"{field} must not be empty")
        return None
    if len(text) > max_len:
        raise InvalidInput(f"{field} must be at most {max_len} characters")
    return text


def check_id(value: str, kind: str) -> str:
    value = (value or "").strip().upper()
    if not _ID_PATTERNS[kind].match(value):
        examples = {"lead_id": "L-001", "slot_id": "S-20261201-0900", "appointment_id": "A-001"}
        raise InvalidInput(f"{kind} {value!r} is not valid; expected a value like {examples[kind]}")
    return value


def normalise_phone(value: str | None) -> str | None:
    """Accept common formats and return +1-AAA-555-01NN. Only fictional numbers are allowed in the demo."""
    if value is None or not value.strip():
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise InvalidInput("phone must be a 10-digit North American number, for example +1-312-555-0142")
    phone = f"+1-{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    if not FICTIONAL_PHONE_RE.match(phone):
        raise InvalidInput(
            "this demo only accepts fictional phone numbers in the 555-0100 to 555-0199 range, "
            "for example +1-312-555-0142"
        )
    return phone


def normalise_email(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    email = value.strip().lower()
    if len(email) > 200 or not _EMAIL_RE.match(email):
        raise InvalidInput(
            "this demo only accepts fictional email addresses at example.com, e.g. ada@example.com"
        )
    return email


def _choice(value: str | None, field: str, options: tuple[str, ...]) -> str | None:
    if value is None:
        return None
    for option in options:
        if value.strip().lower() == option.lower():
            return option
    raise InvalidInput(f"{field} must be one of: {', '.join(options)}")


def _budget(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1_000_000:
        raise InvalidInput("budget_usd must be a whole number from 0 to 1000000")
    return value


def _parse_date(value: str | None, field: str) -> date | None:
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise InvalidInput(f"{field} must be a date like 2026-12-01") from exc


def lead_summary(lead: Lead) -> dict:
    return {
        "id": lead.id,
        "name": lead.name,
        "company": lead.company,
        "status": lead.status.value,
        "service_interest": lead.service_interest,
        "tier": lead.tier.value if lead.tier else None,
        "score": lead.score,
    }


class BusinessService:
    """All CRM and calendar operations. Methods that change data are listed in WRITE_OPERATIONS."""

    WRITE_OPERATIONS = frozenset(
        {"create_lead", "update_lead", "qualify_lead", "book_appointment", "cancel_appointment", "add_note"}
    )

    def __init__(self, store: DataStore) -> None:
        self.store = store

    # ---------- helpers ----------
    def _find_lead(self, leads: list[Lead], lead_id: str) -> Lead:
        for lead in leads:
            if lead.id == lead_id:
                return lead
        raise NotFound(f"no lead with id {lead_id}")

    def _replace_lead(self, leads: list[Lead], updated: Lead) -> list[Lead]:
        return [updated if lead.id == updated.id else lead for lead in leads]

    def _note(self, text: str, author: str = "voice-agent") -> Note:
        return Note(at=self.store.now().replace(microsecond=0), author=author, text=text)

    # ---------- leads ----------
    def search_leads(
        self, query: str | None = None, status: str | None = None, tier: str | None = None, limit: int = 10
    ) -> dict:
        q = clean_text(query, "query", max_len=100)
        status_v = _choice(status, "status", tuple(s.value for s in LeadStatus))
        tier_v = _choice(tier, "tier", tuple(t.value for t in LeadTier))
        if not 1 <= limit <= MAX_SEARCH_RESULTS:
            raise InvalidInput(f"limit must be between 1 and {MAX_SEARCH_RESULTS}")

        matches = []
        for lead in self.store.leads():
            if status_v and lead.status.value != status_v:
                continue
            if tier_v and (lead.tier is None or lead.tier.value != tier_v):
                continue
            if q:
                haystack = " ".join(
                    filter(
                        None,
                        [lead.id, lead.name, lead.company, lead.email, lead.phone, lead.service_interest],
                    )
                ).lower()
                digits = re.sub(r"\D", "", q)
                phone_hit = len(digits) >= 4 and digits in re.sub(r"\D", "", lead.phone or "")
                if q.lower() not in haystack and not phone_hit:
                    continue
            matches.append(lead_summary(lead))
        return {"count": len(matches), "leads": matches[:limit], "truncated": len(matches) > limit}

    def get_lead(self, lead_id: str) -> dict:
        lead_id = check_id(lead_id, "lead_id")
        lead = self._find_lead(self.store.leads(), lead_id)
        appts = [
            a.model_dump(mode="json") for a in self.store.calendar().appointments if a.lead_id == lead_id
        ]
        return {"lead": lead.model_dump(mode="json"), "appointments": appts}

    def create_lead(
        self,
        name: str,
        service_interest: str,
        phone: str | None = None,
        email: str | None = None,
        company: str | None = None,
        budget_usd: int | None = None,
        timeline: str | None = None,
        source: str = "inbound_call",
    ) -> dict:
        name_v = clean_text(name, "name", max_len=100, required=True)
        service_v = _choice(service_interest, "service_interest", SERVICES)
        phone_v = normalise_phone(phone)
        email_v = normalise_email(email)
        if not phone_v and not email_v:
            raise InvalidInput("a phone number or an email address is required")
        company_v = clean_text(company, "company", max_len=120)
        budget_v = _budget(budget_usd) or 0
        timeline_v = _choice(timeline, "timeline", TIMELINES) or "just_researching"
        source_v = _choice(source, "source", SOURCES)

        with self.store.lock:
            leads = self.store.leads()
            for lead in leads:
                if (phone_v and lead.phone == phone_v) or (email_v and lead.email == email_v):
                    raise Conflict(f"a lead with this phone or email already exists: {lead.id}")
            next_num = max(int(lead.id[2:]) for lead in leads) + 1 if leads else 1
            lead = Lead(
                id=f"L-{next_num:03d}",
                name=name_v,
                company=company_v,
                email=email_v,
                phone=phone_v,
                source=source_v,
                service_interest=service_v,
                budget_usd=budget_v,
                timeline=timeline_v,
                status=LeadStatus.NEW,
                created_at=self.store.now().replace(microsecond=0),
            )
            self.store.save_leads([*leads, lead])
        return {"created": True, "lead": lead.model_dump(mode="json")}

    def update_lead(
        self,
        lead_id: str,
        status: str | None = None,
        service_interest: str | None = None,
        budget_usd: int | None = None,
        timeline: str | None = None,
        company: str | None = None,
        phone: str | None = None,
        email: str | None = None,
    ) -> dict:
        lead_id = check_id(lead_id, "lead_id")
        changes: dict = {}
        if status is not None:
            status_v = _choice(status, "status", tuple(s.value for s in LeadStatus))
            if status_v == LeadStatus.BOOKED.value:
                raise InvalidInput("status 'booked' is set by book_appointment, not update_lead")
            changes["status"] = LeadStatus(status_v)
        if service_interest is not None:
            changes["service_interest"] = _choice(service_interest, "service_interest", SERVICES)
        if budget_usd is not None:
            changes["budget_usd"] = _budget(budget_usd)
        if timeline is not None:
            changes["timeline"] = _choice(timeline, "timeline", TIMELINES)
        if company is not None:
            changes["company"] = clean_text(company, "company", max_len=120)
        if phone is not None:
            changes["phone"] = normalise_phone(phone)
        if email is not None:
            changes["email"] = normalise_email(email)
        if not changes:
            raise InvalidInput("nothing to update: pass at least one field to change")

        with self.store.lock:
            leads = self.store.leads()
            lead = self._find_lead(leads, lead_id)
            data = {**lead.model_dump(), **changes}
            try:
                updated = Lead.model_validate(data)
            except ValueError as exc:
                raise InvalidInput(str(exc).splitlines()[-1].strip()) from exc
            self.store.save_leads(self._replace_lead(leads, updated))
        return {"updated": True, "changed_fields": sorted(changes), "lead": updated.model_dump(mode="json")}

    def qualify_lead(self, lead_id: str) -> dict:
        lead_id = check_id(lead_id, "lead_id")
        with self.store.lock:
            leads = self.store.leads()
            lead = self._find_lead(leads, lead_id)
            result = score_lead(lead)
            status = lead.status
            if status != LeadStatus.BOOKED:
                status = LeadStatus.UNQUALIFIED if result.tier == LeadTier.COLD else LeadStatus.QUALIFIED
            note = self._note(f"Qualified: score {result.score}, tier {result.tier.value}.")
            updated = lead.model_copy(
                update={
                    "score": result.score,
                    "tier": result.tier,
                    "status": status,
                    "notes": [*lead.notes, note],
                }
            )
            self.store.save_leads(self._replace_lead(leads, updated))
        return {
            "lead_id": lead_id,
            "score": result.score,
            "tier": result.tier.value,
            "status": status.value,
            "reasons": result.reasons,
        }

    def add_note(self, lead_id: str, text: str, author: str = "voice-agent") -> dict:
        lead_id = check_id(lead_id, "lead_id")
        text_v = clean_text(text, "text", max_len=1000, required=True)
        author_v = clean_text(author, "author", max_len=60, required=True)
        with self.store.lock:
            leads = self.store.leads()
            lead = self._find_lead(leads, lead_id)
            note = self._note(text_v, author_v)
            self.store.save_leads(
                self._replace_lead(leads, lead.model_copy(update={"notes": [*lead.notes, note]}))
            )
        return {"added": True, "lead_id": lead_id, "note": note.model_dump(mode="json")}

    # ---------- calendar ----------
    def list_available_slots(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        staff: str | None = None,
        limit: int = 10,
    ) -> dict:
        start = _parse_date(date_from, "date_from")
        end = _parse_date(date_to, "date_to")
        staff_v = clean_text(staff, "staff", max_len=60)
        if not 1 <= limit <= MAX_SLOT_RESULTS:
            raise InvalidInput(f"limit must be between 1 and {MAX_SLOT_RESULTS}")
        if start and end:
            if end < start:
                raise InvalidInput("date_to must be on or after date_from")
            if (end - start).days > MAX_SLOT_RANGE_DAYS:
                raise InvalidInput(f"the date range can be at most {MAX_SLOT_RANGE_DAYS} days")

        calendar = self.store.calendar()
        now = self.store.now()
        slots = []
        for slot in calendar.slots:
            if not slot.available or slot.start <= now:
                continue
            if start and slot.start.date() < start:
                continue
            if end and slot.start.date() > end:
                continue
            if staff_v and staff_v.lower() not in slot.staff.lower():
                continue
            slots.append(
                {
                    "slot_id": slot.id,
                    "start": slot.start.isoformat(),
                    "end": slot.end.isoformat(),
                    "staff": slot.staff,
                }
            )
        result = {
            "timezone": calendar.timezone,
            "count": len(slots),
            "slots": slots[:limit],
            "truncated": len(slots) > limit,
        }
        if not any(s.start > now for s in calendar.slots):
            result["notice"] = (
                "the demo calendar has no future dates; "
                "regenerate it with scripts/generate_dummy_data.py --start"
            )
        return result

    def book_appointment(self, lead_id: str, slot_id: str, service: str | None = None) -> dict:
        lead_id = check_id(lead_id, "lead_id")
        slot_id = check_id(slot_id, "slot_id")
        with self.store.lock:
            leads = self.store.leads()
            lead = self._find_lead(leads, lead_id)
            service_v = _choice(service, "service", SERVICES) or lead.service_interest
            calendar = self.store.calendar()
            slot = next((s for s in calendar.slots if s.id == slot_id), None)
            if slot is None:
                raise NotFound(f"no slot with id {slot_id}")
            if slot.start <= self.store.now():
                raise InvalidInput(f"slot {slot_id} is in the past")
            if not slot.available:
                raise Conflict(f"slot {slot_id} is no longer available; call list_available_slots again")

            next_num = max((int(a.id[2:]) for a in calendar.appointments), default=0) + 1
            appt = Appointment(
                id=f"A-{next_num:03d}",
                lead_id=lead_id,
                slot_id=slot_id,
                service=service_v,
                status="booked",
                created_at=self.store.now().replace(microsecond=0),
            )
            new_slots = [
                s.model_copy(update={"available": False}) if s.id == slot_id else s for s in calendar.slots
            ]
            new_calendar = calendar.model_copy(
                update={"slots": new_slots, "appointments": [*calendar.appointments, appt]}
            )
            note = self._note(f"Booked {service_v} for {slot.start:%Y-%m-%d %H:%M} ({appt.id}).")
            updated = lead.model_copy(update={"status": LeadStatus.BOOKED, "notes": [*lead.notes, note]})
            self.store.save_calendar(new_calendar)
            self.store.save_leads(self._replace_lead(leads, updated))
        return {
            "booked": True,
            "appointment": appt.model_dump(mode="json"),
            "start": slot.start.isoformat(),
            "end": slot.end.isoformat(),
            "staff": slot.staff,
            "timezone": calendar.timezone,
        }

    def cancel_appointment(self, appointment_id: str, reason: str) -> dict:
        appointment_id = check_id(appointment_id, "appointment_id")
        reason_v = clean_text(reason, "reason", max_len=300, required=True)
        with self.store.lock:
            calendar = self.store.calendar()
            appt = next((a for a in calendar.appointments if a.id == appointment_id), None)
            if appt is None:
                raise NotFound(f"no appointment with id {appointment_id}")
            if appt.status == "cancelled":
                raise Conflict(f"appointment {appointment_id} is already cancelled")
            slot = next(s for s in calendar.slots if s.id == appt.slot_id)
            now = self.store.now()
            late = slot.start - now < timedelta(hours=LATE_CANCEL_HOURS)

            cancelled = appt.model_copy(update={"status": "cancelled"})
            appts = [cancelled if a.id == appointment_id else a for a in calendar.appointments]
            release = slot.start > now
            slots = [
                s.model_copy(update={"available": True}) if s.id == slot.id and release else s
                for s in calendar.slots
            ]
            leads = self.store.leads()
            lead = self._find_lead(leads, appt.lead_id)
            still_booked = any(a.lead_id == lead.id and a.status == "booked" for a in appts)
            status = lead.status
            if lead.status == LeadStatus.BOOKED and not still_booked:
                status = LeadStatus.QUALIFIED
            note = self._note(f"Cancelled {appointment_id}: {reason_v}")
            self.store.save_calendar(calendar.model_copy(update={"slots": slots, "appointments": appts}))
            self.store.save_leads(
                self._replace_lead(
                    leads, lead.model_copy(update={"status": status, "notes": [*lead.notes, note]})
                )
            )
        return {
            "cancelled": True,
            "appointment_id": appointment_id,
            "slot_released": release,
            "late_cancellation": late,
            "late_fee_usd": LATE_CANCEL_FEE_USD if late else 0,
        }
