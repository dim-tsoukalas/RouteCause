# Render web-service image for RouteCause.
#
# Separate from the root Dockerfile on purpose: the root image defaults to the
# CLI demo (ENTRYPOINT investigate), while a web host needs the container to
# launch the API server. Render builds this with the repo root as context, so
# the bundled corpus + incident data (data/) are included.
#
# ingest + api + llm: litellm enables narration via Groq's free tier (set
# INVESTIGATOR_MODEL + GROQ_API_KEY in render.yaml / the Render dashboard).
# Still no local model — Groq runs remotely — so this stays within the free
# 512 MB tier. Runs offline automatically if no key is set.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0

WORKDIR /app

COPY pyproject.toml README.md ./
COPY investigator ./investigator
RUN pip install --no-cache-dir -e ".[ingest,api,llm]"
COPY data ./data

RUN useradd -m -u 1000 app && chown -R app:app /app
USER app

# Render injects $PORT at runtime; investigator-serve reads HOST/PORT from env.
CMD ["investigator-serve"]
