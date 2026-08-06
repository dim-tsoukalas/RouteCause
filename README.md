# network-investigator

A citation-grounded network-incident investigator. It analyzes BGP incident
evidence with **deterministic analyzers** (no LLM in the detection path) and
explains them using **cited passages from RFCs**, refusing to answer when it
can't ground a claim in a source.

> **Phase 1 (this repo): baseline parity.** A working, cited investigation over
> network evidence + RFCs — the common capability that HolmesGPT / K8sGPT /
> LlamaIndex-citation tools share. Competing hypotheses, adversarial
> counter-evidence retrieval, and a citation-*correctness* eval harness are the
> differentiators, layered on in later phases.

## Quickstart (runs fully offline — no API key needed)

```bash
# no install required for the core; optional extras in requirements.txt
PYTHONPATH=. python -m investigator.cli \
  investigate data/incidents/incident_moas_withdrawal.json \
  -q "Why did connectivity to 203.0.113.0/24 drop?"

# ask the RFC corpus directly (cited):
PYTHONPATH=. python -m investigator.cli ask "how is a BGP AS_PATH loop detected?"

# tests:
PYTHONPATH=. python -m pytest -q
```

## Real incidents (RIPE RIS / RouteViews)

`data/incidents/incident_moas_withdrawal.json` is synthetic (TEST-NET-3, private
ASNs) — a worked example, not evidence. For real evaluation, `investigator/ingest.py`
pulls raw MRT update streams directly from the public RIPE RIS and RouteViews
archives for a prefix + time window, filters to that prefix, and normalizes the
result into the same incident JSON shape (pure Python — `mrtparse` only, no
PyBGPStream/native toolchain, so it installs the same way on any platform):

```bash
pip install -r requirements.txt   # pulls in mrtparse

# fetch a named historical incident from data/incidents/catalog.json:
PYTHONPATH=. python -m investigator.ingest catalog pakistan-youtube-2008
PYTHONPATH=. python -m investigator.ingest catalog cloudflare-verizon-2019

# or fetch an arbitrary prefix/window directly:
PYTHONPATH=. python -m investigator.ingest fetch \
  --prefix 104.16.0.0/12 --start 2019-06-24T10:00:00Z --end 2019-06-24T13:00:00Z \
  --name cloudflare_verizon_2019 --collectors rrc00,route-views2

# then investigate it exactly like the synthetic sample:
PYTHONPATH=. python -m investigator.cli investigate data/incidents/pakistan_youtube_2008.json
```

`investigator/evaluate.py` runs every analyzer over the whole catalog and reports
expected-vs-detected, so detection is measured against documented outcomes
rather than eyeballed on one example:

```bash
PYTHONPATH=. python -m investigator.evaluate
```

The catalog's incident windows are deliberately wide and flagged for
verification (see `data/incidents/catalog.json`) — treat them as a starting
point, not authoritative ground truth, until cross-checked against a primary
source. The catalog also documents a known coverage gap: there's no route-leak
analyzer yet, so leak-type incidents correctly show as "no analyzer for this
class" rather than a false pass or fail.

Set `INVESTIGATOR_MODEL` (+ a provider key, see `.env.example`) to turn on
natural-language narration that cites the same numbered sources. Without it,
the tool runs in no-LLM mode and shows the grounded findings and sources
verbatim.

## Example output (real, from the sample incident)

```
## Observations (computed from evidence)
### [CRITICAL] MOAS — 203.0.113.0/24
- Prefix 203.0.113.0/24 was announced by 2 distinct origin ASNs
  (AS64500, AS64666). Presumed legitimate origin is AS64500.
  - Evidence:
    - rrc03@2024-05-01T10:14:30Z ANNOUNCE 203.0.113.0/24 origin=AS64666 …
### [WARNING] WithdrawalStorm — 203.0.113.0/24
- 6 withdrawals within 5 minutes (10:20:00–10:23:00), across 6 peers …

## Explanation (grounded in reference docs)
… [1] RFC 7908 §4  (MOAS / hijack considerations)

## Suggested next checks
- Confirm the legitimate origin AS against RPKI ROAs / IRR objects.
```

The MOAS anomaly correctly retrieves **RFC 7908 §4** (hijack/MOAS) as its top
grounding source.

## What it does — and deliberately does not — do (yet)

**Does:** deterministic BGP anomaly detection (MOAS/hijack, withdrawal storm,
AS_PATH loop, route leak), an agentic search loop over RFCs (the LLM may run
multiple `search_rfcs` queries before answering, `investigator/agent.py`)
with numbered `[n]` citations, abstention when no source is relevant, a
pluggable LLM backend, config-driven analyzer toolsets
(`investigator/toolsets.toml`), a CLI.

**Also does:** real-incident ingestion from RIPE RIS / RouteViews archives
(`investigator/ingest.py`), a detection-accuracy evaluation harness against a
small catalog of documented historical incidents (`investigator/evaluate.py`),
a citation-*correctness* evaluation harness (`investigator/evaluation/`,
`--score-citations`) — does the cited RFC clause actually entail the LLM's
claim, not just get mentioned — and adversarial counter-evidence retrieval
(`investigator/retrieval/contradiction.py`, `--seek-contradictions`): for
each fired analyzer finding, retrieves broadly and keeps only passages an
entailment checker verifies as genuinely contradicting it. Pluggable
entailment checking throughout: a dependency-free lexical heuristic by
default, or a real HuggingFace MNLI cross-encoder as an opt-in upgrade —
deliberately not LLM-as-judge, which would undermine the whole point of an
independent check. **Honestly reported, then re-tested:** run for real,
both checkers mislabeled an unrelated RFC section as "contradicting" a MOAS
finding. Tested whether a bigger *specialized* entailment model helps (not
an LLM-as-judge) — it does, measurably, and is now the default — but it
doesn't fully eliminate the failure mode. See `docs/design.md`'s Phase 4
section for the full before/after. See
[Real incidents](#real-incidents-ripe-ris--routeviews) above.

**Does not (later phases):** competing-hypothesis (ACH) scoring / a measured
false-assertion rate, or hybrid dense retrieval. See
[`docs/design.md`](docs/design.md).

## Architecture

Two layers, honestly separated (see `docs/design.md`):

- **Deterministic layer** — `investigator/analyzers/` (registry mirrors
  K8sGPT's `IAnalyzer`/`coreAnalyzerMap`), loaded from the config-driven
  toolset manifest (`investigator/toolsets.toml` + `investigator/toolsets.py`
  — TOML, not YAML, so the core stays stdlib-only) instead of hardcoded
  imports, and `investigator/types.py`. Always runs, unconditionally, with no
  LLM involved — the agentic loop below never gets a say in what counts as
  evidence.
- **Reasoning layer** — `investigator/retrieval/` (citation engine mirrors
  LlamaIndex's `CitationQueryEngine`) wrapped in a bounded, context-budgeted
  agentic loop (`investigator/agent.py`, mirrors HolmesGPT's tool-calling
  loop and its context-budget truncation) + `investigator/llm.py` (backend
  abstraction mirrors K8sGPT's `IAI`), orchestrated in
  `investigator/engine.py`. Offline mode always does exactly one search
  round; a real LLM backend may search further before answering.

## Layout

```
investigator/
  types.py                 # Incident/BGPUpdate + Result/Finding (K8sGPT-style)
  toolsets.toml              # config-driven analyzer manifest (TOML, stdlib-only)
  toolsets.py                # manifest loader + dynamic analyzer registration
  analyzers/               # deterministic detectors + registry
    base.py  moas.py  withdrawal_storm.py  as_path_loop.py  route_leak.py
  retrieval/               # BM25 + CitationEngine (numbered sources, abstain)
    corpus.py  citations.py  contradiction.py
  llm.py                   # LLMBackend: NoOp (offline) + LiteLLM (real)
  agent.py                  # bounded, context-budgeted agentic search loop (ReAct-style, RFC retrieval only)
  engine.py  report.py  cli.py
  ingest.py                 # RIPE RIS / RouteViews raw MRT -> Incident JSON
  evaluate.py                # expected-vs-detected accuracy over the catalog
  evaluation/                # citation-CORRECTNESS harness (claims.py, entailment.py, scorer.py)
data/
  incidents/               # sample incident JSON (synthetic) + real, ingested ones
    catalog.json            # documented historical incidents (ground truth, verify before trusting)
  rfcs/                     # condensed RFC excerpts (swap for full IETF text)
tests/                     # analyzer + toolset + retrieval/abstention/contradiction + agent + ingest/evaluate/evaluation tests
docs/design.md
```

## Roadmap

- **Phase 1 ✅** baseline parity: analyzers, cited retrieval, agentic search loop (this repo)
- **Phase 1.5 ✅** real-incident ingestion (RIPE RIS/RouteViews) + detection-accuracy eval harness
- **Phase 2 ✅** config-driven toolset abstraction (TOML) + a real route-leak analyzer + LLM context-budget truncation
- **Phase 3 ✅** citation-correctness eval harness (ALCE-style precision/recall + RAGChecker-style retriever-vs-generator split), pluggable lexical/cross-encoder entailment checking
- **Phase 4 ✅** adversarial contradiction retrieval (`--seek-contradictions`), reusing Phase 1 retrieval + Phase 3 entailment checking; a real, verified false-positive limitation is documented, not hidden
- **Phase 5** competing-hypothesis (ACH) reasoning + measured abstention; hybrid BM25+dense retrieval
