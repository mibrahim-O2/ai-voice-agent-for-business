# 03: Deployment

This project has two deployable parts:

1. **The static dashboard**: plain HTML, CSS and JavaScript showing recorded **demo data**.
   It is hosted on **GitHub Pages**, has no backend, makes no API calls and contains no secrets.
   **Live:** https://mibrahim-o2.github.io/ai-voice-agent-for-business/
2. **The backend**: MCP server, knowledge base (RAG) and the text and voice agent with human
   approvals. It is a Python program that needs your OpenAI API key. Part B deploys it to
   **Fly.io**.

## Part A: Dashboard on GitHub Pages

### What gets published

The `dashboard/` folder:

- `index.html`, `assets/styles.css`, `assets/app.js`, `assets/favicon.svg` (no build step, no
  external fonts or CDNs, strict Content-Security-Policy),
- `config.js` (`mode: "demo"`, no secrets),
- `demo/snapshot.json`: the numbers, tables and transcripts, recorded from `voice-agent demo`
  by `scripts/export_demo_snapshot.py`. It is labelled as demo data, and the page refuses to
  render a snapshot that isn't.

### One-time setup (repository owner)

1. Open the repository on GitHub, then **Settings → Pages**.
2. Under **Build and deployment → Source**, choose **GitHub Actions** (not "Deploy from a
   branch"). No branch or folder needs to be picked; the workflow uploads the site itself.
3. Open **Actions → Deploy dashboard to GitHub Pages → Run workflow** (or push any change under
   `dashboard/` to `main`).
4. When the run is green, the site is live at
   **https://mibrahim-o2.github.io/ai-voice-agent-for-business/**. The URL is also shown on the
   run's `deploy` job and under **Settings → Pages**.

The workflow (`.github/workflows/pages.yml`) uses `actions/configure-pages` with
`enablement: true`, which switches Pages on automatically when the repository allows it.
If the first run fails at "Configure Pages", do step 2 by hand and run it again.

### What the workflow does on every deploy

1. Copies `dashboard/` to a `_site/` folder.
2. **Checks**: `config.js` must say `mode: "demo"`, the snapshot must have `meta.demo = true`,
   `scripts/check_secrets.py --path _site` must find no secrets, and no file may mention
   `api.openai.com`.
3. Uploads `_site/` with `actions/upload-pages-artifact` and publishes it with
   `actions/deploy-pages`.

### Updating the dashboard data

```bash
python scripts/export_demo_snapshot.py     # re-records dashboard/demo/snapshot.json (offline, no key)
pytest tests/test_dashboard.py             # includes a check that the snapshot is up to date
git add dashboard/demo/snapshot.json && git commit -m "Refresh dashboard snapshot"
```

Merging to `main` redeploys automatically. To preview locally:
`cd dashboard && python -m http.server 8000`, then open http://localhost:8000.

## Part B: Backend on Fly.io

### Why Fly.io

| Need | Fly.io | Alternatives considered |
|---|---|---|
| Runs our `Dockerfile` unchanged | Yes, builds and runs any Docker image | Render, Railway and Cloud Run also do |
| Outbound **WebSocket** for Realtime voice | Yes | Most hosts do; some proxies don't |
| A **terminal** for the human approver (`voice-agent text`, approvals) | `fly ssh console` gives a shell inside the running machine | Render's free tier has no shell; Cloud Run is request-only, so a terminal session is not possible |
| Keep logs, CRM copy and index across restarts | **Volumes** ($0.15/GB/month) | Render free and Cloud Run have no persistent disk |
| Keep the API key secret | `fly secrets set`: encrypted, injected as an environment variable at runtime, never in the image | All of them have a secret store |
| Cost | About **$3.69/month** for a `shared-cpu-1x` 512 MB machine left running, less if stopped when not in use | Oracle Cloud "Always Free" VM is $0 but needs more setup (OS, firewall, updates) |

Fly.io is the cheapest option here that gives a real terminal, persistent storage and WebSockets
with almost no server administration. Prices are taken from Fly's pricing page (checked
November 2026, see Sources): check it before you deploy.

### What gets deployed

- `Dockerfile` (repository root): Python 3.12 slim, the package installed normally, the demo
  data in `/app/data`, runs as an unprivileged user `agent`, and checks the data and builds the
  local knowledge index **while building**. The container idles (`sleep infinity`); you work in
  it over SSH. **No secret is in the image**: `.dockerignore` excludes `.env`, and CI checks
  that the built image has no `OPENAI_API_KEY` and no `.env`.
- `fly.toml` (repository root): app name, region, environment variables, the volume
  mount at `/var/lib/voice-agent`, and the VM size.
- CI builds the same image on every pull request and runs the demo calls inside it.

### Step by step

1. **Install the Fly CLI and log in** (the Fly site asks for a card; usage under a few dollars is cheap):

   ```bash
   curl -L https://fly.io/install.sh | sh        # macOS: brew install flyctl
   fly auth signup                               # or: fly auth login
   ```

2. **Pick a unique app name** and create the app (from the repository root):

   ```bash
   fly apps create your-voice-agent-name
   ```

   Then put the same name on the `app = "…"` line in `fly.toml`.

3. **Create the volume** for logs, the CRM working copy and the knowledge index (1 GB is plenty):

   ```bash
   fly volumes create voice_agent_data --region ord --size 1
   ```

4. **Store your OpenAI key as a Fly secret.** Type it at the prompt, so it doesn't end up in your
   shell history:

   ```bash
   read -rs OPENAI_API_KEY && printf 'OPENAI_API_KEY=%s\n' "$OPENAI_API_KEY" | fly secrets import && unset OPENAI_API_KEY
   fly secrets list                              # shows the name and a digest, never the value
   ```

5. **Deploy** (Fly builds the image from the `Dockerfile`):

   ```bash
   fly deploy
   ```

6. **Use it.** Open a terminal inside the machine. Approvals are answered right there:

   ```bash
   fly ssh console
   voice-agent demo                    # offline demo calls (no key used)
   voice-agent text                    # live agent; approve or reject in this terminal
   voice-agent voice --type            # Realtime voice; audio saved on the volume
   voice-agent approvals               # what was approved, rejected or left pending
   exit
   ```

   Download a recorded voice reply:
   `fly ssh sftp get /var/lib/voice-agent/audio/last-call.wav`.

7. **Stop paying when you're not using it:** `fly scale count 0` (start again with
   `fly scale count 1`). The volume (and its small charge) remains until you delete it.
   Remove everything with `fly apps destroy your-voice-agent-name`.

### Environment variables

| Variable | Where it is set | Value |
|---|---|---|
| `OPENAI_API_KEY` | **`fly secrets` only** | your key (never in `fly.toml`, the image or git) |
| `OPENAI_TEXT_MODEL` | `fly.toml` `[env]` | `gpt-4.1-mini` |
| `OPENAI_REALTIME_MODEL` | `fly.toml` `[env]` | `gpt-realtime-mini` (cheaper) or `gpt-realtime` |
| `EMBEDDINGS_PROVIDER` | `fly.toml` `[env]` | `local` (free). With `openai`, run `voice-agent ingest --provider openai` once over SSH |
| `VOICE_AGENT_DATA_DIR` | `Dockerfile` | `/app/data` (needed because the package is installed normally) |
| `VOICE_AGENT_VAR_DIR` | `Dockerfile` | `/var/lib/voice-agent` (the volume) |
| `VOICE_AGENT_NOW` | optional, `fly.toml` | e.g. `2026-11-20T10:00` to keep the demo calendar in the future |
| `LOG_LEVEL` | `fly.toml` | `INFO` |

### Cost (estimates, November 2026)

| Item | Price | Monthly |
|---|---|---|
| Fly machine, `shared-cpu-1x` 512 MB, running all month | $3.69 | $3.69 |
| Fly volume, 1 GB | $0.15/GB | $0.15 |
| OpenAI text mode (`gpt-4.1-mini`) | 5–10 model requests per call in our tests; fractions of a cent per call | pay per use |
| OpenAI voice mode | see Part D | pay per use |

Set a monthly **usage limit** in the OpenAI dashboard (Settings → Limits) before going live.

### Limits of this deployment

- **No phone line yet.** Callers can't dial in. The agent runs in a terminal (text, or Realtime
  voice from typed input). Part D describes the telephony piece.
- **Approvals need a person on the SSH terminal.** A hosted product would add a web, Slack or
  SMS approval channel behind the same `Approver` interface (`src/voice_agent/hitl.py`).
- **One machine, one volume, one region.** The JSON store is safe for several processes on that
  machine, not for several machines. Scaling out needs a real database.
- **Live microphone audio** needs a local machine: run `voice-agent voice` on your laptop
  (docs/01, step 9c).

## Notes from earlier tasks

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
  sandbox used to build this project, so live Realtime voice could not be tested there. It is
  covered by automated tests with a scripted Realtime model, and by manual steps E8–E10 in
  02-manual-testing.md, to run on a machine with normal internet access.)
- **Approvals** are answered in the terminal in this version. A hosted deployment needs an
  approval channel a reviewer can reach (for example a small web page, Slack or SMS). It should
  plug into the same `Approver` interface in `src/voice_agent/hitl.py`.
- **Logs** (`var/logs/sessions.jsonl`) contain what callers said. Treat them as personal data:
  keep them on a private volume, limit who can read them, and delete them on a schedule.
  Card numbers and key-like strings are redacted automatically.
- **Tracing** to the OpenAI dashboard is turned off in code (`tracing_disabled=True`), so call
  content is not sent anywhere except the model request itself.

## Part C: Keeping the API key secret (applies to every deployment)

- The key lives only in `.env` on your own machine, or in the hosting platform's secret store
  (`fly secrets`). It is never in git, the Docker image, `fly.toml`, the dashboard or the logs.
- `.env` is in `.gitignore`, and `.dockerignore` keeps it out of the image. Only `.env.example`
  (with an empty key) is committed.
- The dashboard is static and public. It never calls OpenAI and never contains a key. The Pages
  workflow scans the published files before every deploy.
- CI runs `scripts/check_secrets.py` on every pull request. Run it yourself before merging:
  `python scripts/check_secrets.py --diff main`.
- The MCP subprocess is started with `OPENAI_API_KEY` set to empty unless it needs OpenAI
  embeddings, so tools that don't need the key never see it.
- OpenAI error messages (which can contain a partly masked key) are never printed or logged;
  only the error type and HTTP status are.
- Don't paste the output of `env` or `fly ssh console -C env` anywhere: it would show the key.
- If a key ever leaks, revoke it immediately at https://platform.openai.com/api-keys, create a
  new one and update it with `fly secrets import` (as in step 4).

## Part D: Telephony and voice costs

**Not built in this project:** connecting a real phone number. There are two common ways to
add it:

1. **SIP:** OpenAI's Realtime API can accept calls over SIP from a telephony provider's SIP
   trunk. The agent's instructions, tools and approval gate stay the same; a small web service
   accepts the incoming-call webhook and attaches the agent to the call.
2. **Twilio Media Streams:** Twilio streams the call audio over a WebSocket to your server, which
   forwards it to the Realtime API and back.

Either way, a deployment would also need a remote approval channel (see Part B, limits) and a
plan for what the agent says while a human is deciding.

### What a call would cost (estimates, November 2026, prices change often)

| Item | Price |
|---|---|
| US local phone number (Twilio) | about **$1.15 / month** |
| Inbound call minutes (Twilio, US local) | about **$0.0085 / minute** |
| OpenAI `gpt-realtime-mini` audio | **$10** per 1M input tokens, **$20** per 1M output tokens (text tokens are cheaper) |
| OpenAI `gpt-realtime` audio | **$32** per 1M input tokens, **$64** per 1M output tokens |

OpenAI does not publish a per-minute price; it depends on how much each side talks and how long
the conversation history grows. Independent estimates put `gpt-realtime-mini` around
**$0.02–0.05 per minute** of conversation, and the full model about three times that.

**Worked example (estimate):** 300 calls a month, 3 minutes each, with `gpt-realtime-mini`:

| Item | Calculation | Monthly |
|---|---|---|
| Phone number | 1 × $1.15 | $1.15 |
| Call minutes | 900 min × $0.0085 | $7.65 |
| Realtime audio | 900 min × ~$0.03 | ~$27 |
| Fly.io machine + volume | | $3.84 |
| **Total** | | **~$40 / month** (~$0.13 per call) |

With the full `gpt-realtime` model, the audio line is roughly three times higher (~$80).
Set an OpenAI usage limit, keep calls short (the agent hands over to a person instead of long
back-and-forth), and check the current prices before you commit.

### Sources (checked November 2026)

- Fly.io resource pricing: https://fly.io/docs/about/pricing/
- OpenAI `gpt-realtime-mini` model and prices: https://developers.openai.com/api/docs/models/gpt-realtime-2.1-mini
- OpenAI Realtime pricing ($32 / $64 per 1M audio tokens): https://www.layer3labs.io/guides/openai-realtime-api-pricing
- Realtime cost per minute (estimates): https://www.eesel.ai/blog/gpt-realtime-mini-pricing ,
  https://www.forasoft.com/blog/article/openai-realtime-api-pricing
- Twilio voice pricing (US): https://www.idtexpress.com/blog/twilio-pricing-explained-how-to-reduce-voice-costs/ ,
  https://www.cartesia.ai/learn/twilio-pricing
