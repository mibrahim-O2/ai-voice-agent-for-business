"""Generate the fictional demo data in data/leads.json and data/calendar.json.

The output is deterministic (fixed random seed), so re-running it produces the same files.
Every person and company is invented. Phone numbers use the 555-01xx range reserved for
fiction, and email addresses use the reserved example.com domain.

Usage:
    python scripts/generate_dummy_data.py                    # default start date
    python scripts/generate_dummy_data.py --start 2027-01-04 # shift the calendar window
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SEED = 20261117
TIMEZONE = "America/Chicago"
DEFAULT_START = date(2026, 12, 1)
BUSINESS_DAYS = 10
SLOT_HOURS = [9, 10, 11, 13, 14, 15, 16]  # 12:00 is lunch
STAFF = ["Tech Avery (demo)", "Tech Jordan (demo)"]

FIRST = [
    "Ada",
    "Bram",
    "Cleo",
    "Dario",
    "Esme",
    "Faris",
    "Greta",
    "Hugo",
    "Ines",
    "Jonah",
    "Kaia",
    "Lior",
    "Mina",
    "Nico",
    "Oona",
    "Pavel",
    "Quinn",
    "Rosa",
    "Silas",
    "Tova",
    "Ugo",
    "Vera",
    "Wren",
    "Xavi",
    "Yara",
]
LAST = [
    "Ashgrove",
    "Brightwater",
    "Calloway",
    "Dunmore",
    "Elderby",
    "Fenwick",
    "Gallowmere",
    "Hartwell",
    "Ivers",
    "Juniper",
    "Kettering",
    "Larkspur",
    "Merriweather",
    "Northcott",
    "Oakhurst",
    "Pemberly",
    "Quarrington",
    "Rookwood",
    "Stonebridge",
    "Thistlewood",
    "Underhill",
    "Vantress",
    "Whitlock",
    "Yarrowby",
    "Zephyrine",
]
COMPANIES = [
    None,
    "Fernhollow Bakery (demo)",
    "Pebblebrook Dental (demo)",
    None,
    "Copperleaf Cafe (demo)",
    None,
    "Mossgate Apartments (demo)",
    None,
    "Tidewell Fitness (demo)",
    None,
]
SOURCES = ["website_form", "inbound_call", "referral", "google_ads", "facebook_ads"]
SERVICES = [
    "AC repair",
    "Furnace installation",
    "Plumbing repair",
    "Water heater installation",
    "Electrical inspection",
    "Duct cleaning",
    "Annual maintenance plan",
]
TIMELINES = ["this_week", "this_month", "next_quarter", "just_researching"]
AREA_CODES = ["312", "415", "512", "617", "702", "808"]


def make_leads(rng: random.Random, start: date) -> list[dict]:
    leads = []
    created_base = datetime.combine(start - timedelta(days=30), time(9, 0))
    for i in range(25):
        first, last = FIRST[i], LAST[i]
        status = rng.choices(
            ["new", "contacted", "qualified", "unqualified", "booked"], weights=[8, 6, 5, 3, 3]
        )[0]
        score = tier = None
        if status in ("qualified", "unqualified", "booked"):
            score = rng.randint(65, 95) if status != "unqualified" else rng.randint(10, 39)
            tier = "hot" if score >= 70 else "warm" if score >= 40 else "cold"
        created = created_base + timedelta(days=i, hours=rng.randint(0, 8))
        notes = []
        if status != "new":
            notes.append(
                {
                    "at": (created + timedelta(hours=2)).isoformat(),
                    "author": "demo-agent",
                    "text": f"Caller asked about {SERVICES[i % len(SERVICES)]}.",
                }
            )
        leads.append(
            {
                "id": f"L-{i + 1:03d}",
                "name": f"{first} {last}",
                "company": COMPANIES[i % len(COMPANIES)],
                "email": f"{first.lower()}.{last.lower()}@example.com",
                "phone": f"+1-{AREA_CODES[i % len(AREA_CODES)]}-555-01{i + 1:02d}",
                "source": rng.choice(SOURCES),
                "service_interest": SERVICES[i % len(SERVICES)],
                "budget_usd": rng.choice([150, 300, 500, 1200, 2500, 4800, 7500]),
                "timeline": rng.choice(TIMELINES),
                "status": status,
                "score": score,
                "tier": tier,
                "created_at": created.isoformat(),
                "notes": notes,
            }
        )
    return leads


def business_days(start: date, count: int) -> list[date]:
    days, d = [], start
    while len(days) < count:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def make_calendar(rng: random.Random, start: date, leads: list[dict]) -> dict:
    days = business_days(start, BUSINESS_DAYS)
    slots = []
    for d in days:
        for n, hour in enumerate(SLOT_HOURS):
            st = datetime.combine(d, time(hour, 0))
            slots.append(
                {
                    "id": f"S-{d:%Y%m%d}-{hour:02d}00",
                    "start": st.isoformat(),
                    "end": (st + timedelta(hours=1)).isoformat(),
                    "staff": STAFF[(n + d.day) % len(STAFF)],
                    "available": True,
                }
            )
    appointments = []
    booked_leads = [lead for lead in leads if lead["status"] == "booked"]
    chosen = rng.sample(range(len(slots)), k=len(booked_leads))
    for n, (lead, slot_index) in enumerate(zip(booked_leads, sorted(chosen), strict=True)):
        slot = slots[slot_index]
        slot["available"] = False
        appointments.append(
            {
                "id": f"A-{n + 1:03d}",
                "lead_id": lead["id"],
                "slot_id": slot["id"],
                "service": lead["service_interest"],
                "status": "booked",
                "created_at": lead["created_at"],
            }
        )
    # A few slots are blocked for staff time off / internal work.
    for slot_index in rng.sample([i for i, s in enumerate(slots) if s["available"]], k=6):
        slots[slot_index]["available"] = False
    return {
        "timezone": TIMEZONE,
        "slot_minutes": 60,
        "business_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "start_date": days[0].isoformat(),
        "end_date": days[-1].isoformat(),
        "slots": slots,
        "appointments": appointments,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    args = parser.parse_args()

    rng = random.Random(SEED)
    leads = make_leads(rng, args.start)
    calendar = make_calendar(rng, args.start, leads)
    note = "Fictional demo data. No real people, companies or phone numbers."
    (DATA_DIR / "leads.json").write_text(
        json.dumps({"_note": note, "leads": leads}, indent=2) + "\n", encoding="utf-8"
    )
    (DATA_DIR / "calendar.json").write_text(json.dumps(calendar, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(leads)} leads and {len(calendar['slots'])} slots to {DATA_DIR}")


if __name__ == "__main__":
    main()
