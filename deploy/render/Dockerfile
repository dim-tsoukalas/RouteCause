# Render web-service image for RouteCause.
#
# Separate from the root Dockerfile on purpose: the root image defaults to the
# CLI demo (ENTRYPOINT investigate), while a web host needs the container to
# launch the API server. Render builds this with the repo root as context, so
# the bundled corpus + incident data (data/) are included.
#
# Lean by design (ingest + api only) to fit Render's free 512 MB tier; the demo
# runs offline. To enable narration, add the `llm` extra here and set
# INVESTIGATOR_MODEL + a provider key in the Render dashboard.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0

WORKDIR /app

COPY pyproject.toml README.md ./
COPY investigator ./investigator
RUN pip install --no-cache-dir -e ".[ingest,api]"
COPY data ./data

RUN useradd -m -u 1000 app && chown -R app:app /app
USER app

# Render injects $PORT at runtime; investigator-serve reads HOST/PORT from env.
CMD ["investigator-serve"]
