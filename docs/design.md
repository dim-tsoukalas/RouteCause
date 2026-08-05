# Design notes

## The two-layer split (why detection is LLM-free)

Borrowed from K8sGPT: **deterministic analyzers** compute what is observably
true from the evidence and emit structured `Result`s; the **LLM is enrichment
only**, constrained to narrate over retrieved, cited sources or abstain. This
keeps hallucination out of the detection path — the observations in a report
are computed facts, not model guesses.

```
Incident (BGP evidence) ──► Analyzer registry ──► [Result, Result, …]
                                                        │
RFC corpus ──► BM25 CitationEngine ──► numbered sources │
                                                        ▼
                                             InvestigationEngine
                                                        │
                                                        ▼
                                    Report: observations + cited explanation + next steps
```

**Layer 2 is now a bounded agentic loop** (`investigator/agent.py`), not a
single retrieval call: after a mandatory seed search, an LLM backend may
request additional `search_rfcs` searches (up to `max_search_rounds`,
default 3) before answering — refining its query based on what came back,
mirroring HolmesGPT's tool-calling loop. This is deliberately confined to
retrieval: **Layer 1 stays exactly as unconditional and LLM-free as before**.
The LLM is never given the option of skipping or choosing among analyzers —
only of how much RFC grounding to gather before explaining what the
analyzers already found. Letting the loop reach into detection would reopen
the hallucination risk the two-layer split exists to close.

Offline/no-LLM mode (`NoOpBackend`) is unaffected in substance: since NoOp
can't "decide" to call a tool, the loop's mandatory seed search is the only
round that ever runs for it — identical retrieval/citation behavior to
before this loop existed, just routed through the same mechanism a real
backend uses to go further.

Mechanism note: the loop uses prompt-based ReAct parsing (`ACTION:
search_rfcs("...")` / `FINAL: ...` text lines, regex-parsed) rather than
native LiteLLM function-calling, so `LLMBackend.complete(prompt) -> str`
stays unchanged and works identically across every LiteLLM-supported
provider. Trade-off: less "native" than real function-calling, but simpler,
provider-agnostic, and trivially unit-testable with a scripted fake backend
(see `tests/test_agent.py`).

Known limitation: the RFC corpus is currently 2 hand-picked excerpt files, so
a multi-round search loop has limited practical payoff until the corpus is
larger (see "swap for full IETF text" below) — the loop is real and tested
now; its value grows with corpus size.

## Component map

| Concern | Module | Analog it mirrors |
|---|---|---|
| Evidence model | `investigator/types.py` | — |
| Analyzer interface + registry | `investigator/analyzers/base.py` | K8sGPT `IAnalyzer` / `coreAnalyzerMap` |
| Deterministic detectors | `investigator/analyzers/*.py` | K8sGPT analyzers |
| LLM backend abstraction | `investigator/llm.py` | K8sGPT `IAI` |
| RFC retrieval + citations | `investigator/retrieval/` | LlamaIndex `CitationQueryEngine` |
| Agentic search loop | `investigator/agent.py` | HolmesGPT tool-calling loop (ReAct-via-prompt-parsing, not native function-calling) |
| Orchestration | `investigator/engine.py` | HolmesGPT investigation loop |
| CLI | `investigator/cli.py` | HolmesGPT `ask` / `investigate` |
| Real-incident ingestion | `investigator/ingest.py` | — |
| Detection-accuracy eval | `investigator/evaluate.py` | — |

## How later phases slot in without churn

- **Phase 2 (more analyzers / toolsets):** add a module under `analyzers/`,
  import it in `analyzers/__init__.py`. Zero core changes.
- **Phase 3 (citation-correctness harness):** add `evaluation/`; consume
  `Report.results` + `CitedAnswer.sources`. The claim→source pairs are already
  structured for entailment checking (ALCE / MiniCheck / RAGChecker).
- **Phase 4 (adversarial retrieval):** add a contradiction-seeking query path
  in `retrieval/`; reuse `BM25`/`CitationEngine`. The `Report` already reserves
  a hypotheses/contradiction slot.
- **Phase 5 (abstention / ACH):** the `min_score` floor and the answer-level
  `INSUFFICIENT EVIDENCE` marker are the seed; extend into a scored ACH matrix
  and a false-assertion metric.

## Real-incident ingestion + evaluation (Phase 1.5)

The Phase 1 "done" bar above called for RIPE RIS / RouteViews data via
PyBGPStream. That library wraps a C library (libbgpstream) with no Windows
wheels, and was going to require a native/Rust toolchain regardless of
platform for a fresh Python version — both hostile to "clone and run."
Instead:

- `investigator/ingest.py` downloads raw MRT update files directly from the
  public RIPE RIS (`data.ris.ripe.net`) and RouteViews (`archive.routeviews.org`)
  archives for a prefix + time window, parses them with the pure-Python
  `mrtparse` package (no native/C dependency), filters to the target prefix,
  and writes the same `Incident` JSON shape the loader already accepts —
  zero core changes. It lists each month's directory rather than assuming a
  fixed dump interval, since RIS runs ~5 minutes and RouteViews' cadence has
  varied over the archive's history; multi-collector support (RIS + RouteViews
  together) falls out of that for free.
- `data/incidents/catalog.json` holds a small ground-truth catalog (name,
  window, prefixes, expected outcome, a `notes` field flagging that the window
  is deliberately wide and should be verified against a primary source before
  being treated as precise).
- `investigator/evaluate.py` runs every registered analyzer over each cataloged
  incident and reports expected-vs-detected — turning "does it work on this one
  example" into a measured accuracy table. A label with no mapped analyzer
  (currently `route_leak` — there's no leak detector yet) reports "not
  applicable" rather than a false pass/fail, so a coverage gap reads as a
  finding rather than a bug.

Known limitation carried forward: RIPEstat's `bgplay` API (the obvious
lowest-effort choice) was tried first and rejected — live-checked, it only
retains roughly the last 1.5–2 years, which excludes the historical incidents
worth demonstrating against (2008 Pakistan Telecom/YouTube, 2019
Cloudflare/Verizon). The raw-archive approach above has no such limit.

## Deliberate limitations

- Retrieval is lexical BM25 only (no dense/hybrid yet) — good enough for RFC
  clause matching; hybrid is a Phase-2/3 upgrade behind the same interface.
- No route-leak analyzer yet (see Phase 1.5 above) — a leak-type incident
  correctly evaluates as "not applicable," not a miss.
- The agentic search loop (see "two-layer split" above) is real but
  low-value today given a 2-file RFC corpus; it earns its keep once the
  corpus is scaled up.
- No YAML-defined toolset abstraction or LLM context-budget truncation yet
  (Phase 2 in the roadmap) — analyzers are still a hardcoded Python registry.
- No competing hypotheses, no citation-correctness scoring yet — those are the
  differentiators, intentionally deferred so the baseline ships first.
