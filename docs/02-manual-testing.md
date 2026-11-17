# 02: Manual testing checklist

Run this checklist **after the whole project is complete** (after Task 5). Automated tests cover
the logic offline; this checklist checks the real experience: the live OpenAI model, your
microphone, the approval prompts and the deployed dashboard.

**How to use it:** do each step in order, compare with the expected result, and write `PASS` or
`FAIL` (with a short note) in the last column. Set up the project first with
[01-user-workflow.md](01-user-workflow.md).

Tester: ____________ Date: ____________ Commit: ____________ OS: ____________

## A. Setup and data

| # | Step | Expected result | Pass/Fail |
|---|---|---|---|
| A1 | Run `voice-agent validate-data` | Prints 25 leads, 70 calendar slots, 10 knowledge documents and `OK: all dummy data is valid` | |
| A2 | Run `pytest` | All tests pass, no network or key needed | |
| A3 | Run `python scripts/check_secrets.py` | `OK: no secrets found in tracked files` | |
| A4 | Run `git check-ignore .env` | Prints `.env` (your key file is ignored by git) | |

## B. MCP tools

Start from clean data: `voice-agent reset-data`. In a second terminal run
`voice-agent mcp --transport streamable-http`, then open the MCP Inspector
(`npx @modelcontextprotocol/inspector`), choose **Streamable HTTP**, enter
`http://127.0.0.1:8765/mcp` and click **Connect**. Use **Tools → List Tools**, pick a tool, fill
in the arguments and click **Run Tool**. The steps assume a date before 2026-12-01; for later dates,
regenerate the calendar first (see 01-user-workflow, troubleshooting).

| # | Step | Expected result | Pass/Fail |
|---|---|---|---|
| B1 | Run `voice-agent tools` | 9 tools; the 6 write tools show `YES` under sensitive, the 3 read tools show `no` | |
| B2 | Inspector: List Tools | 9 tools; each sensitive tool's description starts with `SENSITIVE` | |
| B3 | `search_leads` with `query` = `calloway` | 1 lead, `L-003`, Cleo Calloway | |
| B4 | `search_leads` with `status` = `booked` | `count` 3, every lead `booked` | |
| B5 | `get_lead` with `lead_id` = `L-003` | Lead details, notes and one `booked` appointment | |
| B6 | `list_available_slots` with `date_from` = `date_to` = `2026-12-02` | Only slots on 2026-12-02, timezone `America/Chicago` | |
| B7 | `create_lead`: name `Manual Tester`, service `AC repair`, phone `(312) 555-0177` | New lead `L-026`, phone saved as `+1-312-555-0177`, status `new` | |
| B8 | `update_lead`: `L-026`, budget_usd `2500`, timeline `this_week` | `changed_fields` = budget_usd, timeline | |
| B9 | `qualify_lead`: `L-026` | Score 40+30+15+8 = 93, tier `hot`, four reasons listed | |
| B10 | `add_note`: `L-026`, text `Prefers mornings` | `added: true` | |
| B11 | `book_appointment`: `L-026` and a `slot_id` from B6 | New appointment `A-004`; `get_lead L-026` shows status `booked` | |
| B12 | `list_available_slots` again for 2026-12-02 | The slot from B11 is gone | |
| B13 | `cancel_appointment`: `A-004`, reason `test` | `cancelled: true`, `slot_released: true`, late fee 0 | |
| B14 | Run `voice-agent reset-data`, then `get_lead L-026` | `not_found`: the demo data is back to the original | |

## C. RAG answers *(steps added in Task 3)*

Will include: a question the knowledge base answers (with the source shown), and a question it
cannot answer (the agent must say it does not know).

## D. Human-in-the-loop *(steps added in Task 4)*

Will include: the approve path and the reject path for a booking.

## E. Text mode and voice mode *(steps added in Task 4)*

## F. Error cases

| # | Step | Expected result | Pass/Fail |
|---|---|---|---|
| F2 | `get_lead` with `L-999` | Error `not_found: no lead with id L-999` | |
| F3 | `get_lead` with `hello` | Error `invalid_input: … expected a value like L-001` | |
| F4 | `create_lead` with phone `312-867-5309` | Error: only fictional numbers in 555-0100 to 555-0199 | |
| F5 | `create_lead` with email `someone@gmail.com` | Error: only `@example.com` addresses | |
| F6 | `create_lead` with neither phone nor email | Error: a phone number or an email address is required | |
| F7 | `create_lead` with phone `+1-312-555-0101` (already L-001) | Error `conflict: … already exists: L-001` | |
| F8 | `search_leads` with `limit` = `500` | Validation error naming `limit` | |
| F9 | `list_available_slots` with `date_from` = `next tuesday` | Error: must be a date like 2026-12-01 | |
| F10 | `book_appointment` twice on the same slot (two different leads) | Second call: `conflict: slot … is no longer available` | |
| F11 | `update_lead` with only `lead_id` | Error: nothing to update | |
| F12 | `voice-agent mcp --transport streamable-http --host 0.0.0.0` | Refuses to start and explains why (no authentication) | |
| F13 | Book a slot for `L-026`, then book a second slot for `L-026` | Second call: `conflict: lead L-026 already has upcoming appointment …; to reschedule, cancel it first` | |
| F14 | `cancel_appointment` for an appointment whose start time has passed (use a demo date that is already in the past, or skip if none) | Error: already started or taken place; no late fee | |
| F1 | Empty `OPENAI_API_KEY` in `.env`, then start live text mode | A clear message: `OPENAI_API_KEY is not set. Copy .env.example to .env…`; no crash trace | |

## G. Dashboard *(steps added in Task 5)*

## Summary

| Section | Passed | Failed | Notes |
|---|---|---|---|
| A. Setup | | | |
| B. MCP tools | | | |
| C. RAG | | | |
| D. HITL | | | |
| E. Text and voice | | | |
| F. Errors | | | |
| G. Dashboard | | | |
