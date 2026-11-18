# Backend image: the voice agent, MCP server, knowledge base and demo data.
# No secrets are baked in: OPENAI_API_KEY is provided at runtime by the platform's secret store.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VOICE_AGENT_DATA_DIR=/app/data \
    VOICE_AGENT_VAR_DIR=/var/lib/voice-agent \
    EMBEDDINGS_PROVIDER=local

WORKDIR /app
COPY pyproject.toml README.md constraints.txt ./
COPY src ./src
# Exact, tested dependency versions (constraints.txt), so every build installs the same thing.
RUN pip install --upgrade pip && pip install -c constraints.txt . && rm -rf /root/.cache build
COPY data ./data

# Run as an unprivileged user; runtime state (CRM copy, index, logs) lives on a volume.
RUN useradd --create-home --uid 10001 agent \
    && mkdir -p /var/lib/voice-agent && chown agent:agent /var/lib/voice-agent
USER agent

# Fail the build if the bundled data is broken, and warm the local knowledge index.
RUN voice-agent validate-data && voice-agent ingest

# The container idles; operators connect (e.g. `fly ssh console`) and run voice-agent text,
# voice --type, demo or approvals in that terminal, where approvals are answered.
# PID 1 must handle SIGTERM, or every stop waits for the kill timeout and ends in SIGKILL.
CMD ["sh", "-c", "trap 'exit 0' TERM INT; sleep infinity & wait"]
