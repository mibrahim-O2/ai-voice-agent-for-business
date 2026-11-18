"""The static dashboard: demo snapshot is correct and current, and the site is safe to publish."""

from __future__ import annotations

import json
import re
from datetime import date

import pytest

from conftest import ROOT, load_script
from voice_agent.dashboard_snapshot import build_snapshot
from voice_agent.observability import SessionLogger

DASHBOARD = ROOT / "dashboard"
SNAPSHOT = DASHBOARD / "demo" / "snapshot.json"


@pytest.fixture(scope="module")
def snapshot():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


# ---------- the committed snapshot ----------
def test_snapshot_is_clearly_demo_data(snapshot):
    meta = snapshot["meta"]
    assert meta["demo"] is True
    assert "fictional" in meta["notice"].lower() and "scripted" in meta["notice"].lower()
    assert "fictional" in meta["company"]
    assert {s["model"] for s in snapshot["sessions"]} == {"scripted-demo"}


def test_snapshot_numbers_match_the_demo_calls(snapshot):
    k = snapshot["kpis"]
    assert k["calls_handled"] == 7
    assert k["approvals"] == {"approved": 5, "rejected": 1, "pending": 1}
    assert k["appointments_booked"] == 2 and k["appointments_cancelled"] == 1
    assert k["handoffs"] == 2 and k["guardrail_hits"] == 1
    assert k["knowledge_searches"] == 4 and k["knowledge_not_found"] == 1
    assert sum(snapshot["leads"]["by_tier"].values()) == snapshot["leads"]["total"] == 26
    assert {a["status"] for a in snapshot["approvals"]} == {"approved", "rejected", "pending"}
    assert "Services and pricing" in {s["title"] for s in snapshot["knowledge"]["sources"]}
    first = snapshot["sessions"][0]["transcript"][0]
    assert first["type"] == "agent" and first.get("greeting") and "AI assistant" in first["text"]


def test_snapshot_contains_only_fictional_contacts(snapshot):
    assert all("phone" not in row and "email" not in row for row in snapshot["leads"]["rows"])
    text = json.dumps(snapshot)
    phone_like = r"(?<![\w-])(?:\+1[\s-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)"  # not slot ids
    phones = re.findall(phone_like, text)
    assert phones  # lead rows publish no contact details; these are numbers spoken in the demo calls
    for phone in phones:
        assert re.sub(r"\D", "", phone)[-7:-2] == "55501", phone
    for email in re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text):
        assert email.endswith("@example.com"), email


def test_committed_snapshot_is_up_to_date(tmp_path, snapshot):
    """Re-record the demo and compare: fails if code or data changed without re-exporting."""
    exporter = load_script("export_demo_snapshot")
    fresh = exporter.record(tmp_path / "snapshot.json")
    fresh["meta"]["recorded_on"] = snapshot["meta"]["recorded_on"]
    assert fresh == snapshot, "run: python scripts/export_demo_snapshot.py"


# ---------- the builder ----------
def test_builder_marks_undecided_requests_as_pending_and_tags_outcomes(tmp_path):
    from voice_agent.config import DATA_DIR

    logs = tmp_path / "logs"
    log = SessionLogger(logs, mode="text", session_id="T1")
    log.log("session_start", model="scripted-demo", scene="test call")
    log.log("caller", text="hi")
    log.log("tool_call", tool="search_knowledge", call_id="a", arguments={"query": "roofs"})
    log.log("tool_result", tool="search_knowledge", call_id="a", found=False, sources=[])
    log.log("approval_requested", tool="add_note", call_id="b", summary="Add a note", warnings=[])
    snap = build_snapshot(logs, DATA_DIR, recorded_on=date(2026, 1, 2))
    assert snap["kpis"]["approvals"] == {"approved": 0, "rejected": 0, "pending": 1}
    assert snap["approvals"][0]["decided_by"] is None
    assert snap["sessions"][0]["outcomes"] == ["pending approval", "I don't know"]
    assert snap["knowledge"]["queries"] == [
        {"session_id": "T1", "query": "roofs", "found": False, "sources": []}
    ]
    assert snap["meta"]["recorded_on"] == "2026-01-02"
    assert all("ts" not in entry for entry in snap["sessions"][0]["transcript"])


# ---------- the published site ----------
def test_dashboard_contains_no_secrets():
    scanner = load_script("check_secrets")
    assert scanner.main(["--path", str(DASHBOARD)]) == 0


def test_dashboard_is_demo_only_and_never_calls_apis():
    config = (DASHBOARD / "config.js").read_text()
    assert 'mode: "demo"' in config
    for path in DASHBOARD.rglob("*"):
        if path.suffix in {".js", ".html", ".css", ".json"}:
            text = path.read_text(encoding="utf-8")
            assert "api.openai.com" not in text and "OPENAI_API_KEY" not in text, path
            assert "localhost" not in text and "127.0.0.1" not in text, path


def test_page_is_self_contained_with_a_strict_csp():
    html = (DASHBOARD / "index.html").read_text()
    assert "Content-Security-Policy" in html and "script-src 'self'" in html and "style-src 'self'" in html
    assert re.search(r"<script>(?!\s*</script>)", html) is None, "no inline scripts"
    assert "style=" not in html, "no inline styles (blocked by the CSP)"
    for ref in re.findall(r'(?:src|href)="([^"]+)"', html):
        if ref.startswith(("http://", "https://")):
            assert ref.startswith("https://github.com/mibrahim-O2/"), f"external resource: {ref}"
        elif not ref.startswith("#"):
            assert (DASHBOARD / ref).exists(), f"missing file: {ref}"
    assert "DEMO DATA" in html


def test_app_script_never_injects_html():
    app = (DASHBOARD / "assets" / "app.js").read_text()
    assert "innerHTML" not in app and "insertAdjacentHTML" not in app and "eval(" not in app
    assert "data.meta.demo !== true" in app  # refuses a snapshot not marked as demo data
