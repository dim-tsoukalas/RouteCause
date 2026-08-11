# RouteCause — citation-grounded BGP-incident investigator.
#
# Build:   docker build -t routecause .
# Run:     docker run --rm routecause                     # runs the flagship 2008 hijack demo, offline
#          docker run --rm routecause rostelecom-2020 --seek-contradictions
#          docker run --rm --entrypoint ask routecause "how is a BGP AS_PATH loop detected?"
#          docker run --rm --entrypoint pytest routecause -q
#
# Serve the HTTP API (docs at http://localhost:8000/docs):
#          docker run --rm -p 8000:8000 -e HOST=0.0.0.0 \
#                     --entrypoint investigator-serve routecause
#
# Optional LLM narration (no key needed for the offline demo above):
#          docker run --rm -e INVESTIGATOR_MODEL=openai/gpt-4o-mini -e OPENAI_API_KEY=$OPENAI_API_KEY \
#                     routecause pakistan-youtube-2008 --seek-contradictions
#
# EXTRAS controls which optional dependency groups are installed at build time.
# Default "ingest,llm,dev,api,obs" gives real-incident ingestion + LLM narration
# + the pytest suite + the HTTP service + OpenTelemetry tracing. The `ingest`
# group is required: the default-enabled RPKI analyzer imports it at startup.
# Add "nli" for the cross-encoder / MiniCheck entailment checkers (pulls in
# torch — multi-GB):
#          docker build --build-arg EXTRAS=ingest,llm,dev,api,obs,nli .

FROM python:3.11-slim AS base

ARG EXTRAS=ingest,llm,dev,api,obs

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependency layer first, so edits to source don't bust the pip cache.
COPY pyproject.toml README.md ./
COPY investigator ./investigator
RUN pip install --no-cache-dir -e ".[${EXTRAS}]"

# Bundled corpus (16 RFCs) + real incident data + tests.
COPY data ./data
COPY tests ./tests

# Run as a non-root user.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

# The HTTP service (investigator-serve) listens here when that entrypoint is used.
EXPOSE 8000

# `docker run routecause [args]` == `investigate [args]`; default args run the
# flagship demo. Override --entrypoint for `ask`, `pytest`, or evaluation.
ENTRYPOINT ["investigate"]
CMD ["pakistan-youtube-2008", "--seek-contradictions"]
