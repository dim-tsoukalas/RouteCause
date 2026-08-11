# Hugging Face Docker Space for RouteCause.
#
# This is a SELF-CONTAINED Dockerfile for a Space — it clones the GitHub repo
# at build time (so the bundled 16-RFC corpus + incident data come along) and
# starts the FastAPI server on the port HF expects (7860).
#
# You do NOT build this locally. Put this file + the sibling README.md at the
# ROOT of a new Hugging Face Space (SDK: Docker); HF builds and runs it. See
# deploy/huggingface/README.md's setup steps.

FROM python:3.11-slim

# git is only needed to pull the repo (which carries data/).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Clone the project (default branch = main). Change the ref if yours differs.
RUN git clone --depth 1 https://github.com/dim-tsoukalas/RouteCause.git /app
WORKDIR /app

# ingest (required at startup) + api (the server) + llm (so an API-key secret
# can enable narration later without a rebuild).
RUN pip install --no-cache-dir -e ".[ingest,api,llm]"

# HF Docker Spaces route traffic to port 7860; our server reads HOST/PORT.
ENV HOST=0.0.0.0 \
    PORT=7860 \
    PYTHONUNBUFFERED=1
EXPOSE 7860

# Non-root (HF runs as uid 1000).
RUN useradd -m -u 1000 user && chown -R user:user /app
USER user

CMD ["investigator-serve"]
