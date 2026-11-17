# AI Voice Agent with MCP, RAG and Human-in-the-Loop

An open-source **AI voice agent for business** that answers inbound calls, qualifies leads and
books appointments. It is built with the **OpenAI Agents SDK** (Realtime speech-to-speech voice
mode plus a text-only mode), a **Model Context Protocol (MCP) server** exposing CRM and calendar
tools, **retrieval-augmented generation (RAG)** over a local business knowledge base, and
**human-in-the-loop (HITL) approval** for every sensitive action such as creating a lead,
booking or cancelling an appointment. A static **dashboard on GitHub Pages** shows calls,
lead tiers, bookings, approvals and RAG sources from sample session logs. Python, offline-testable,
no paid vector database.

> **Demo data only.** The company (Oakleaf Home Services), every lead, phone number and email in
> this repository is fictional. No real API keys are stored anywhere in the repo.

## Status

| Task | Scope | Status |
|---|---|---|
| 1. Foundation | Structure, dummy data, lint, tests, CI, docs skeleton | ✅ done |
| 2. MCP server | CRM and calendar tools with validation and sensitivity flags | ✅ done |
| 3. RAG | Local ingest, embeddings, vector store, retrieval tool with "I don't know" rule | ✅ done |
| 4. Agent + HITL | Text and Realtime voice agent, approval gate, guardrails, structured logs | planned |
| 5. Dashboard | Static GitHub Pages dashboard and deployment guides | planned |

## Quick start

```bash
git clone https://github.com/mibrahim-O2/ai-voice-agent-for-business.git
cd ai-voice-agent-for-business
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env               # then add your own OPENAI_API_KEY (optional for tests)

voice-agent validate-data          # check the dummy data
voice-agent tools                  # list MCP tools and which need human approval
voice-agent mcp                    # run the MCP server (stdio); add --transport streamable-http for HTTP
voice-agent ingest                 # build the knowledge-base index (offline by default)
voice-agent ask "Are you open on Saturday?"   # retrieval with sources, or "I don't know"
pytest                             # run the test suite (offline, no key needed)
```

Full beginner guide: [docs/01-user-workflow.md](docs/01-user-workflow.md).

## Project structure

```
src/voice_agent/   Python package
  business/        demo CRM and calendar: JSON store, validation, lead scoring
  mcp_server/      MCP server (CRM, calendar and search_knowledge tools) and the sensitivity policy
  rag/             chunking, local TF-IDF or OpenAI embeddings, local vector index, retriever
data/              fictional leads, calendar and knowledge documents (see data/README.md)
scripts/           dummy-data generator and secret scanner
tests/             pytest suite (runs offline)
docs/              user workflow, manual testing checklist, deployment guide
.github/workflows/ CI (lint, secret scan, data validation, tests)
```

## Documentation

- [docs/01-user-workflow.md](docs/01-user-workflow.md): set up and use the project locally
- [docs/02-manual-testing.md](docs/02-manual-testing.md): manual test checklist
- [docs/03-deployment.md](docs/03-deployment.md): GitHub Pages and backend deployment
- [CLAUDE.md](CLAUDE.md): project rules and commands

## Security

- `OPENAI_API_KEY` is read only from your environment or a local `.env` file, which git ignores.
- CI scans every change for anything that looks like a secret.
- The public dashboard never contains or needs an API key.

## Author

Muhammad Ibrahim ([@mibrahim-O2](https://github.com/mibrahim-O2))
