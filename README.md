# RouteCause

**A citation-grounded BGP-incident investigator — it detects network routing
anomalies with deterministic analyzers, explains them with cited passages from
IETF RFCs, and refuses to answer when it can't ground a claim in a source.**

[![CI](https://github.com/dim-tsoukalas/RouteCause/actions/workflows/ci.yml/badge.svg)](https://github.com/dim-tsoukalas/RouteCause/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)
[![Live API](https://img.shields.io/badge/live-API%20%E2%86%92%20%2Fdocs-brightgreen)](https://routecause.onrender.com/docs)

[**▶ Try the live API**](https://routecause.onrender.com/docs) · [Static demo](https://dim-tsoukalas.github.io/RouteCause/) · [Quickstart](#quickstart) · [HTTP API](#http-api) · [Architecture](#architecture) · [Findings & results](docs/findings.md)

---

### What it is, in 30 seconds

When internet traffic gets misrouted — a BGP hijack, a route leak — engineers
sift through raw routing data to find the cause. RouteCause automates the first
pass: **deterministic detectors** (no LLM in the detection path) flag the
anomaly, then a **retrieval-augmented LLM** explains *why*, citing the exact RFC
clause behind every claim and abstaining when it can't ground one. The system is
built to **measure its own grounding** — citation precision/recall, adversarial
counter-evidence search, competing-hypothesis ranking — instead of trusting the
model's fluency.

**Stack:** Python · RAG (BM25 + dense hybrid retrieval, RRF fusion) · agentic
tool-calling loop · LiteLLM (hosted + local models) · NLI/entailment models for
automated citation checking · FastAPI service · Docker · OpenTelemetry tracing ·
offline evaluation harness · 123 tests.

## Quickstart

```bash
pip install -e .                                    # core runs on the stdlib alone — no extras, no API key
investigate pakistan-youtube-2008 --seek-contradictions
```

Detection, cited retrieval, and competing-hypothesis reasoning all run offline.
Add an LLM (`INVESTIGATOR_MODEL` + a provider key) only for natural-language
narration. Prefer Docker? `docker run --rm routecause` runs the same demo with
nothing installed — see [Run with Docker](#run-with-docker).

## What makes it different

Each point was found by measuring against 13 real historical incidents, not
asserted in a design doc — full write-ups in [docs/findings.md](docs/findings.md):

- **It measures its own citations.** An evaluation harness scores whether the
  cited RFC clause actually *entails* each generated claim (ALCE-style
  precision/recall, RAGChecker-style retriever-vs-generator split) — catching
  fluent narration that cites four real RFC sections all wrong (0% recall).
- **It argues against itself.** For every finding it retrieves counter-evidence
  and keeps only passages an entailment checker verifies as genuinely
  contradicting, then ranks competing hypotheses by Heuer's ACH method and
  **abstains** rather than assert when nothing clears the evidence bar.
- **Honest, reproduced results.** `evaluate.py --ach` over the real catalog
  reports **3 correct / 1 false / 9 abstained** — the one false assertion is
  diagnosed, not hidden. Trade-offs (bigger corpus, bigger NLI model, hybrid
  retrieval) are each shown to help *and* hurt, with the losing half reported.
- **Deterministic core, LLM as enrichment.** Detection never involves an LLM,
  so the model can't invent what counts as evidence — it only narrates over
  already-grounded findings.

See the full end-to-end run on the real 2008 Pakistan Telecom / YouTube hijack —
transcript and scorecard in [docs/findings.md](docs/findings.md#full-transcript-the-2008-pakistan-telecom--youtube-hijack).

## Run with Docker

No local Python needed — the image bundles the 16-RFC corpus and real incident
data, so the demo runs fully offline:

```bash
docker build -t routecause .
docker run --rm routecause                          # the 2008 Pakistan/YouTube hijack demo
docker run --rm routecause rostelecom-2020 --seek-contradictions
docker run --rm --entrypoint ask routecause "how is a BGP AS_PATH loop detected?"
docker run --rm --entrypoint pytest routecause -q   # the full test suite
```

Ready-to-run incidents: `pakistan-youtube-2008`, `rostelecom-2020`,
`indosat-2014`, `level3-comcast-2017`, `telekom-malaysia-2015`,
`google-japan-leak-2017`, `mainone-google-2018`, `twitter-rtcomm-2022`,
`celer-cbridge-2022`. Turn on narration by passing `-e INVESTIGATOR_MODEL=… -e
OPENAI_API_KEY=…` at run time (nothing is baked into the image).

**One-command smoke test** — builds the image and checks the demo, a second
incident, `ask`, and the tests:

```bash
./scripts/docker-smoke.sh          # macOS / Linux / WSL / CI
.\scripts\docker-smoke.ps1         # Windows PowerShell
```

## HTTP API

The same engine, exposed as a small FastAPI service (a thin layer over
`InvestigationEngine`, so the API and CLI can't drift). Corpus is loaded and
indexed once at startup.

**Live instance:** https://routecause.onrender.com/docs — try it in the browser.
(Free Render tier, so the first request after a while cold-starts for ~30–60s,
then it's fast.)

```bash
pip install -e ".[ingest,api]"
investigator-serve                 # -> http://127.0.0.1:8000  (interactive docs at /docs)

# or in Docker:
docker run --rm -p 8000:8000 -e HOST=0.0.0.0 --entrypoint investigator-serve routecause
```

- `GET /health` · `GET /incidents`
- `POST /investigate` — `{"incident": "pakistan-youtube-2008", "seek_contradictions": true}` → structured findings, cited explanation, ACH ranking, Markdown report.
- `POST /ask` — `{"question": "…"}` → a cited answer over the RFC corpus (or an honest abstention).

**Deploy a live copy (free):** a [`render.yaml`](render.yaml) blueprint deploys
the API as a free Docker web service (Render → *New → Blueprint → connect repo*;
no credit card). A Hugging Face Space config is in
[`deploy/huggingface/`](deploy/huggingface/).

## Observability

The LLM/agent path is instrumented — one span per investigation, one per model
completion (model, prompt/completion size, latency). Off by default; one env var
turns it on:

```bash
INVESTIGATOR_TRACING=console investigate pakistan-youtube-2008   # structured spans on stderr, zero extra deps
INVESTIGATOR_TRACING=otlp    investigator-serve                  # export to Phoenix / Langfuse / Jaeger (pip install -e ".[obs]")
```

## Install & extras

```bash
pip install -e .             # core: analyzers, BM25 retrieval, offline CLI, ACH — stdlib only
pip install -e ".[ingest]"   # mrtparse — pull real incidents from RIPE RIS / RouteViews
pip install -e ".[llm]"      # litellm — natural-language narration
pip install -e ".[nli]"      # sentence-transformers — real cross-encoder / MiniCheck checkers
pip install -e ".[api,obs]"  # FastAPI service · OpenTelemetry tracing
pip install -e ".[all]"      # everything, incl. dev (pytest)
```

`investigate` also accepts a path to any incident JSON, and
`python -m investigator.ingest` builds new incidents from raw MRT archives — see
[docs/findings.md](docs/findings.md) and `docs/design.md`.

## Architecture

Two layers, honestly separated (full detail in [`docs/design.md`](docs/design.md)):

- **Deterministic layer** (`investigator/analyzers/`) — a config-driven toolset
  registry (mirrors K8sGPT's `IAnalyzer`). Always runs, unconditionally, with no
  LLM involved. The agentic loop never gets a say in what counts as evidence.
- **Reasoning layer** (`investigator/retrieval/` + `agent.py` + `llm.py`) — a
  citation engine (LlamaIndex-style `CitationQueryEngine`) inside a bounded,
  context-budgeted agentic loop (HolmesGPT-style), orchestrated by
  `engine.py`. Offline does one search round; a real LLM may search further.

## More

- [docs/findings.md](docs/findings.md) — measured results, the full transcript, capability list, roadmap, layout
- [docs/design.md](docs/design.md) — architecture and phase-by-phase design
- [docs/corpus-expansion-results.md](docs/corpus-expansion-results.md) · [docs/hybrid-retrieval-results.md](docs/hybrid-retrieval-results.md) · [docs/rpki-toolset-results.md](docs/rpki-toolset-results.md) — honest before/after write-ups
