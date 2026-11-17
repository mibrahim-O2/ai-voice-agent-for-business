# 01: User workflow (run it on your own computer)

This guide takes you from nothing to a running AI voice agent on your own machine. It is written
for beginners: copy each command exactly. Sections marked *(coming in Task N)* are filled in when
that part of the project is built.

> Everything in this project uses **fictional demo data**. You only need your own OpenAI API key
> for live text mode, voice mode and OpenAI embeddings. The tests run without a key.

## 1. Prerequisites

| You need | Why | Check it |
|---|---|---|
| Python 3.11 or newer | runs the project | `python --version` (or `python3 --version`) |
| Git | downloads the code | `git --version` |
| An OpenAI account and API key (optional at first) | live agent and voice mode | https://platform.openai.com/api-keys |
| A microphone and speakers/headphones (voice mode only) | talk to the agent | your system sound settings |

On Windows, use PowerShell and replace `python3` with `python` where needed.

## 2. Get the code

```bash
git clone https://github.com/mibrahim-O2/ai-voice-agent-for-business.git
cd ai-voice-agent-for-business
```

## 3. Create a virtual environment

A virtual environment keeps this project's packages separate from the rest of your computer.

```bash
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows PowerShell
```

Your prompt now starts with `(.venv)`. Run `source .venv/bin/activate` again in every new terminal.

## 4. Install the dependencies

```bash
pip install --upgrade pip
pip install -e ".[dev]"
```

This installs the project and the `voice-agent` command.

## 5. Add your OpenAI API key

```bash
cp .env.example .env             # Windows: copy .env.example .env
```

Open `.env` in a text editor and paste your key after `OPENAI_API_KEY=`, with no spaces or
quotes. Your key starts with `sk-`; the dots below stand for the rest of your key:

```
OPENAI_API_KEY=sk-...
```

- `.env` is ignored by git, so your key is never committed. **Never** put your key in any other file.
- Leave `EMBEDDINGS_PROVIDER=local` to build the knowledge base offline, or set it to `openai`.

## 6. Check that everything works

```bash
voice-agent validate-data        # should end with: OK: all dummy data is valid
pytest                           # all tests should pass
```

## 7. Run the MCP server

The **MCP server** (Model Context Protocol) gives the agent its business tools: a demo CRM
(leads) and a demo calendar. You normally do not start it yourself: the voice agent starts it
automatically in the background. You can still run and inspect it on its own.

### 7a. See the tools and which ones need approval

```bash
voice-agent tools
```

| Tool | What it does | Needs human approval? |
|---|---|---|
| `search_leads` | find leads by name, company, email, phone digits or id; filter by status/tier | no (read-only) |
| `get_lead` | one lead with notes and appointments | no (read-only) |
| `list_available_slots` | open one-hour slots in the future, optionally between two dates | no (read-only) |
| `create_lead` | create a new lead | **yes** |
| `update_lead` | change fields on a lead | **yes** |
| `qualify_lead` | score 0–100, set tier (hot ≥ 70, warm ≥ 40, cold) and save it | **yes** |
| `add_note` | add a note to a lead | **yes** |
| `book_appointment` | book an open slot for a lead | **yes** |
| `cancel_appointment` | cancel a booking (a $40 late fee is reported if < 24 h before) | **yes** |

Every tool that changes data is "sensitive". The approval step itself is added in Task 4.

### 7b. Start the server

```bash
voice-agent mcp                                   # stdio: for MCP clients that start it themselves
voice-agent mcp --transport streamable-http       # HTTP on http://127.0.0.1:8765/mcp
```

The HTTP endpoint has **no login**, so it only listens on your own computer (`127.0.0.1`). It
refuses other addresses unless you add `--allow-remote`, which you should only do behind a proxy
that adds authentication.

To try it in a graphical tool, run the official MCP Inspector (needs Node.js) and choose
**Streamable HTTP** with the URL `http://127.0.0.1:8765/mcp`:

```bash
npx @modelcontextprotocol/inspector
```

### 7c. Where your changes go, and how to undo them

The files in `data/` are never changed. On first use they are copied to `var/state/`, and all
bookings, new leads and notes are saved there. Several processes can safely use it at the same
time (for example the HTTP server and an agent session), because every change takes a file lock.
To start again from the original demo data:

```bash
voice-agent reset-data
```

### 7d. Demo rules for contact details

To keep the demo free of real personal data, the tools only accept **fictional** contact details:

- phone numbers in the range `555-0100` to `555-0199`, in any common format, for example
  `(312) 555-0142` or `+1 312 555 0142`,
- email addresses at `example.com`, for example `ada@example.com`.

Anything else is rejected with a clear message.

## 8. Load the RAG knowledge base

The agent answers questions about the business (hours, prices, policies) from 10 short documents
in `data/knowledge/`. This is **RAG** (retrieval-augmented generation): before answering, the
agent searches these documents and must answer only from what it finds, naming the source.

### 8a. Build the index

```bash
voice-agent ingest                      # offline, free, no key needed (EMBEDDINGS_PROVIDER=local)
voice-agent ingest --provider openai    # optional: OpenAI embeddings (needs your key, ~1 API call)
```

This splits each document into chunks, turns each chunk into a vector ("embedding") and saves them
in `var/index/<provider>/`. No external database is used.

- The **local** index is rebuilt automatically whenever the documents change, so you can skip
  this step for local mode.
- The **OpenAI** index is never rebuilt automatically (that would spend API credit without you
  asking). Run `voice-agent ingest --provider openai` again after editing a document.

### 8b. Ask the knowledge base a question

```bash
voice-agent ask "How much does a diagnostic visit cost?"
voice-agent ask "Do you install solar panels?"
```

The first prints passages with their source file and a similarity score. The second prints
`I don't know: nothing relevant in the knowledge base`, because the documents don't cover it.
**The agent never invents an answer:** when nothing scores above the threshold, the tool returns
`found: false` and the agent says it doesn't know and offers a human.

### 8c. Check retrieval quality

```bash
voice-agent rag-eval                    # local
voice-agent rag-eval --provider openai  # makes one API call per question (28 small calls)
```

It runs the 28 labelled questions in `data/rag_eval.json` (18 the documents answer, 10 they don't)
and reports how many were answered with the right source and how many were correctly refused.
Expected result for local mode:
`answered 17/18 … refused 10/10`. The one miss ("financing for a new furnace") gets "I don't
know", which is the safe way to fail.

### 8d. Add or change a document

1. Create `data/knowledge/11-your-topic.md` starting with front matter:

   ```
   ---
   title: Your topic
   category: policy
   ---
   # Your topic
   Short paragraphs. Keep each document under about 400 words.
   ```

2. Run `voice-agent ingest` (and `--provider openai` if you use it).
3. Run `voice-agent rag-eval`, and add a question for the new document to `data/rag_eval.json`.

Keep everything fictional: no real names, phone numbers or companies.

## 9. Run the voice agent *(coming in Task 4)*

### 9a. Text mode (no microphone needed)

### 9b. Voice mode (Realtime speech-to-speech)

## 10. Approve or reject actions (human-in-the-loop) *(coming in Task 4)*

## 11. View the dashboard *(coming in Task 5)*

## 12. Troubleshooting

| Problem | Fix |
|---|---|
| `python: command not found` | Use `python3`, or install Python 3.11+ from python.org |
| `voice-agent: command not found` | Activate the virtual environment (step 3), then reinstall (step 4) |
| `OPENAI_API_KEY is not set` | Create `.env` from `.env.example` and add your key (step 5) |
| `Data validation failed` | You edited a file in `data/`; run `git checkout data/` to restore it |
| A tool says `this demo only accepts fictional phone numbers` | Use a number like `+1-312-555-0142` (see 7d) |
| `list_available_slots` returns no slots and a `notice` | The demo dates have passed. Run `python scripts/generate_dummy_data.py --start 2027-01-04` (any future Monday), then `voice-agent reset-data` |
| `slot … is no longer available` | Someone booked it; list the slots again |
| `lead … already has upcoming appointment` | One upcoming booking per lead. To reschedule, cancel the old appointment, then book the new slot |
| `Refusing to listen on 0.0.0.0` | The HTTP MCP server is local-only by default; see 7b |
| `Address already in use` when starting the HTTP server | Another server is on port 8765; add `--port 8766` |
| `The openai index cannot be used … Run: voice-agent ingest --provider openai` | Build the OpenAI index first (step 8a), or set `EMBEDDINGS_PROVIDER=local` |
| `EMBEDDINGS_PROVIDER is 'openai' but OPENAI_API_KEY is not set` | Add your key to `.env`, or switch to `EMBEDDINGS_PROVIDER=local` |
| `ask` says "I don't know" for a question the documents do cover | The wording is far from the document's. Rephrase, use OpenAI embeddings, or add the caller's wording to the document |
| `pip` errors about Python version | Check `python --version` is 3.11 or newer |

More rows are added as features are built.
