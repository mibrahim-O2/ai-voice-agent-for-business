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

## Part C: Keeping the API key secret (applies to every deployment)

- The key lives only in `.env` on your machine, or in the hosting platform's secret settings.
- `.env` is in `.gitignore`. Only `.env.example` (with an empty key) is committed.
- The dashboard is static and public. It never calls OpenAI and never contains a key.
- CI runs `scripts/check_secrets.py` on every pull request. Run it yourself before merging:
  `python scripts/check_secrets.py --diff main`.
- If a key ever leaks, revoke it immediately at https://platform.openai.com/api-keys and create a new one.

## Part D: Telephony and voice costs *(completed in Task 5)*

Will cover: what it costs to connect a real phone number (telephony provider per-minute rates and
number rental) and OpenAI Realtime audio pricing, with a worked example per call minute.
