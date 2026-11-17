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

## B. MCP tools *(steps added in Task 2)*

## C. RAG answers *(steps added in Task 3)*

Will include: a question the knowledge base answers (with the source shown), and a question it
cannot answer (the agent must say it does not know).

## D. Human-in-the-loop *(steps added in Task 4)*

Will include: the approve path and the reject path for a booking.

## E. Text mode and voice mode *(steps added in Task 4)*

## F. Error cases *(steps added in Tasks 2 to 4)*

| # | Step | Expected result | Pass/Fail |
|---|---|---|---|
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
