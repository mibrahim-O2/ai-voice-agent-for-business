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

- The **local** index is rebuilt automatically whenever the documents change, even while the
  agent or MCP server is running (changes are picked up within about 2 seconds), so you can skip
  this step for local mode.
- The **OpenAI** index is never rebuilt automatically (that would spend API credit without you
  asking). After editing a document, run `voice-agent ingest --provider openai` again. Until then,
  results carry `index_stale: true` and `ask` prints a warning.

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
voice-agent rag-eval --provider openai  # one batched API request for all 28 questions
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

## 9. Run the voice agent

The same agent (same instructions, tools and safety rules) runs in two modes. Both start the MCP
server for you in the background and use the knowledge base from step 8.

### 9a. Try it with no API key: the offline demo

```bash
voice-agent demo
```

This plays 7 short **scripted** calls through the real tools, knowledge base and approval steps:
a new caller who books, a question the knowledge base can't answer, a rejected cancellation, a
prompt-injection attempt, a gas emergency, a caller who hangs up while an approval is waiting,
and a reschedule. Only the agent's words are scripted; every tool call really runs (or is really
refused) on a fresh copy of the demo data in `var/demo/`, so your own data is not touched.
Logs are in `var/demo/logs/sessions.jsonl`.

### 9b. Text mode (no microphone needed, needs your key)

```bash
voice-agent text
```

The agent greets you and says it is an AI. Type what a caller would say and press Enter; type
`quit` to hang up. Things to try:

- `How much does a diagnostic visit cost?` (answered from the knowledge base, with the source)
- `Do you install solar panels?` (the agent says it doesn't know and offers a person)
- `I'm Esme Elderby, my number is 702 555 0105. Book me the earliest slot on Wednesday.`
  (you will be asked to approve the booking, see step 10)

Model: `OPENAI_TEXT_MODEL` in `.env` (default `gpt-4.1-mini`). At the end it prints how many
model requests the call used.

### 9c. Voice mode (Realtime speech-to-speech, needs your key)

Install the audio extras once (Linux also needs PortAudio: `sudo apt install libportaudio2`):

```bash
pip install -e ".[voice]"
voice-agent voice                  # talk through your microphone, hear the agent on your speakers
```

Wear headphones so the agent doesn't hear itself. Press Ctrl+C to hang up. The transcript is
printed as you talk.

No microphone? Type what the caller says and the agent still answers in **speech**, saved to a
WAV file you can play:

```bash
voice-agent voice --type                              # audio saved to var/audio/last-call.wav
voice-agent voice --type --save-audio my-call.wav --voice verse
```

Model: `OPENAI_REALTIME_MODEL` (default `gpt-realtime`; `gpt-realtime-mini` is cheaper). Voice
mode needs a direct **WebSocket** connection to `api.openai.com`. Some company networks and
proxies block that; text mode only needs normal HTTPS.

### 9d. Logs

Every call writes structured events (one JSON object per line) to `var/logs/sessions.jsonl`:
caller turns, agent replies, tool calls and results (including which knowledge sources were
used), approval requests and decisions, guardrail warnings, hand-offs and errors. Card numbers
and anything that looks like an API key are redacted before they are written.

## 10. Approve or reject actions (human-in-the-loop)

Anything that changes data (creating or updating a lead, qualifying it, adding a note, booking
or cancelling) **pauses** before it runs and asks you, in the same terminal:

```
========================================================================
APPROVAL NEEDED (nothing has been done yet)
  Action : Book slot S-20261202-0900 (Wed 02 Dec 09:00, Tech Avery (demo), open) for lead L-005 (Esme Elderby, status new)
  Tool   : book_appointment  (books a technician's time for a customer)
  Args   : {"lead_id": "L-005", "slot_id": "S-20261202-0900"}
========================================================================
Approve? [y = approve / anything else = reject]:
```

- Type `y` to **approve**: exactly the arguments shown are run, once.
- Type anything else to **reject**, then optionally give a reason. The action does not run; the
  agent tells the caller it couldn't be done and offers a call back.
- No answer within 120 seconds counts as a rejection. So does any error in the approval step
  (it "fails closed").
- If the caller said something that looked like an attempt to manipulate the agent earlier in
  the call, a `WARNING:` line is shown with the request.
- To try the agent without changing any data, start it with `--auto-reject`
  (`voice-agent text --auto-reject`). There is deliberately no auto-approve option.

Every request and decision is logged. To review them:

```bash
voice-agent approvals              # your calls
voice-agent approvals --demo       # the demo calls: 5 approved, 1 rejected, 1 pending
```

"Pending" means the call ended (for example the caller hung up) before anyone decided, so the
action never ran.

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
| `Could not connect to the OpenAI Realtime API (… HTTP 405 …)` | Your network or proxy blocks WebSockets. Try another network, or use `voice-agent text` |
| `Microphone mode needs the optional audio packages` | `pip install -e ".[voice]"`; on Linux also `sudo apt install libportaudio2`; or use `voice-agent voice --type` |
| The agent hears itself and interrupts | Use headphones |
| An approval was rejected but I typed y | Only `y` or `yes` approves; check you answered within 120 seconds |
| `voice-agent text` says `OPENAI_API_KEY is not set` | Add your key to `.env` (step 5), or run `voice-agent demo`, which needs no key |
| `ask` says "I don't know" for a question the documents do cover | The wording is far from the document's. Rephrase, use OpenAI embeddings, or add the caller's wording to the document |
| `pip` errors about Python version | Check `python --version` is 3.11 or newer |

More rows are added as features are built.
