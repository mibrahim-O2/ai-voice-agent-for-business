# Dummy data

**Everything in this folder is fictional.** The company, people, businesses, prices and towns
are invented for the demo.

| File | What it contains |
|---|---|
| `leads.json` | 25 leads (CRM records) with status, budget, timeline, and score and tier for qualified leads |
| `calendar.json` | Two weeks of one-hour appointment slots (Mon–Fri, 9:00–17:00, no 12:00 slot), with a few existing appointments and blocked slots |
| `rag_eval.json` | 28 labelled questions for the knowledge base: 18 it answers (with the expected source) and 10 it must refuse |
| `knowledge/*.md` | 10 short documents for the RAG knowledge base: overview, hours, services and pricing, service area, booking, cancellation, payment and warranty, emergencies, FAQ, privacy |

Rules the tests enforce:

- phone numbers follow `+1-XXX-555-01XX` (the 555-01xx range is reserved for fiction),
- email addresses use the reserved `example.com` domain,
- every file validates against the schemas in `src/voice_agent/data_models.py`.

`leads.json` and `calendar.json` are produced by `scripts/generate_dummy_data.py` (fixed seed).
To move the calendar to new dates, run `python scripts/generate_dummy_data.py --start YYYY-MM-DD`.
The test that checks the generator is deterministic compares against the default start date, so
commit regenerated data only together with a matching change to `DEFAULT_START`.

At runtime the MCP tools never modify these files. They work on a copy in
`var/state/` (git-ignored); `voice-agent reset-data` restores it.
