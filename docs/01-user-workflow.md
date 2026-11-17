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

## 7. Run the MCP server *(coming in Task 2)*

## 8. Load the RAG knowledge base *(coming in Task 3)*

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
| `pip` errors about Python version | Check `python --version` is 3.11 or newer |

More rows are added as features are built.
