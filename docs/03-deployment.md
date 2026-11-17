# 03: Deployment

This project has two deployable parts:

1. **The static dashboard**: plain HTML, CSS and JavaScript showing demo data. It is hosted on
   **GitHub Pages**, has no backend and contains no secrets.
2. **The backend** (MCP server, RAG and the voice/text agent): a Python service that needs your
   OpenAI API key. It is hosted on a real platform (Part B).

## Part A: Dashboard on GitHub Pages *(completed in Task 5)*

Planned approach (based on the reference project):

1. A GitHub Actions workflow `.github/workflows/pages.yml` copies `dashboard/` into a site folder.
2. Before publishing, it checks that the site is in demo mode and scans it for secrets
   (`python scripts/check_secrets.py --path _site`).
3. It deploys with the official `actions/upload-pages-artifact` and `actions/deploy-pages` actions.
4. In the repository settings, **Settings → Pages → Build and deployment → Source** is set to
   **GitHub Actions**.
5. Expected URL: `https://mibrahim-o2.github.io/ai-voice-agent-for-business/`

Step-by-step instructions and the live URL are added in Task 5.

## Part B: Backend on a real platform *(completed in Task 5)*

Will cover: the chosen platform and why, step-by-step setup, environment variables, cost, limits,
and how the API key stays secret.

### MCP server notes for deployment (from Task 2)

- The voice agent starts the MCP server itself over **stdio**, inside the same container, so the
  MCP server does not need its own public port.
- If you run the HTTP transport (`voice-agent mcp --transport streamable-http`), it has **no
  authentication** and exposes tools that change data. It listens on `127.0.0.1` only and refuses
  public addresses unless you pass `--allow-remote`. Only do that behind an authenticating proxy
  or on a private network.
- Demo state (new leads, bookings, notes) is written to `VOICE_AGENT_VAR_DIR/state/`. On platforms
  with an ephemeral disk it resets on every redeploy, which is fine for a demo. Mount a volume to keep it.
- For a non-editable install (for example `pip install .` in a Docker image), set
  `VOICE_AGENT_DATA_DIR` to the absolute path of the `data/` folder.

### Knowledge base (RAG) notes for deployment (from Task 3)

- With `EMBEDDINGS_PROVIDER=local` (the default) nothing needs to happen at deploy time: the index
  is built in about a second on first use and stored in `VOICE_AGENT_VAR_DIR/index/`.
- With `EMBEDDINGS_PROVIDER=openai`, run `voice-agent ingest --provider openai` once after each
  deploy (for example in the start command). It makes one embeddings request for the whole
  knowledge base (fractions of a cent with `text-embedding-3-small`), and each question costs one
  more small request. If the index is missing, the CRM tools keep working and the knowledge tool
  returns a clear "unavailable" error. It never builds the index silently.
- The relevance thresholds (0.115 local, 0.38 OpenAI) are calibrated on `data/rag_eval.json`.
  Re-run `voice-agent rag-eval` after changing documents.

### Agent and voice notes for deployment (from Task 4)

- **Text mode** only needs outbound HTTPS to `api.openai.com`.
- **Voice mode (Realtime)** needs an outbound **WebSocket** (`wss://api.openai.com/v1/realtime`).
  Check that the platform and any proxy allow WebSocket upgrades. (They were blocked in the cloud
  sandbox used to build this project, so live voice was tested on a local machine.)
- **Approvals** are answered in the terminal in this version. A hosted deployment needs an
  approval channel a reviewer can reach (for example a small web page, Slack or SMS). It should
  plug into the same `Approver` interface in `src/voice_agent/hitl.py`.
- **Logs** (`var/logs/sessions.jsonl`) contain what callers said. Treat them as personal data:
  keep them on a private volume, limit who can read them, and delete them on a schedule.
  Card numbers and key-like strings are redacted automatically.
- **Tracing** to the OpenAI dashboard is turned off in code (`tracing_disabled=True`), so call
  content is not sent anywhere except the model request itself.

## Part C: Keeping the API key secret (applies to every deployment)

- The key lives only in `.env` on your machine, or in the hosting platform's secret settings.
- `.env` is in `.gitignore`. Only `.env.example` (with an empty key) is committed.
- The dashboard is static and public. It never calls OpenAI and never contains a key.
- CI runs `scripts/check_secrets.py` on every pull request. Run it yourself before merging:
  `python scripts/check_secrets.py --diff main`.
- The MCP subprocess is started with `OPENAI_API_KEY` set to empty unless it needs OpenAI
  embeddings, so tools that don't need the key never see it.
- OpenAI error messages (which can contain a partly masked key) are never printed or logged.
- If a key ever leaks, revoke it immediately at https://platform.openai.com/api-keys and create a new one.

## Part D: Telephony and voice costs *(completed in Task 5)*

Will cover: what it costs to connect a real phone number (telephony provider per-minute rates and
number rental) and OpenAI Realtime audio pricing, with a worked example per call minute.
