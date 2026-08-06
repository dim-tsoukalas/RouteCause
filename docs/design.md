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
| Toolset manifest + loader | `investigator/toolsets.toml`, `investigator/toolsets.py` | HolmesGPT YAML toolsets (TOML here, see Phase 2 below) |
| LLM backend abstraction | `investigator/llm.py` | K8sGPT `IAI` |
| RFC retrieval + citations | `investigator/retrieval/` | LlamaIndex `CitationQueryEngine` |
| Agentic search loop | `investigator/agent.py` | HolmesGPT tool-calling loop (ReAct-via-prompt-parsing, not native function-calling) |
| Orchestration | `investigator/engine.py` | HolmesGPT investigation loop |
| CLI | `investigator/cli.py` | HolmesGPT `ask` / `investigate` |
| Real-incident ingestion | `investigator/ingest.py` | — |
| Detection-accuracy eval | `investigator/evaluate.py` | — |
| Citation-correctness eval | `investigator/evaluation/` | ALCE (precision/recall) + RAGChecker (retriever-vs-generator split), not LLM-as-judge |

## How later phases slot in without churn

- **Phase 2 ✅ (more analyzers / toolsets):** done — see "Pluggable toolsets"
  below. Turned out better than the original plan here: instead of adding a
  module and hand-editing an import list in `analyzers/__init__.py`, a new
  analyzer is now a module + one `toolsets.toml` entry, genuinely zero core
  changes (verified, not just claimed — see that section).
- **Phase 3 ✅ (citation-correctness harness):** done — see
  `investigator/evaluation/` below. Deliberately distinct from gameable
  LLM-as-judge faithfulness scoring: entailment checking is pluggable
  (`EntailmentChecker`), with a dependency-free lexical-overlap default and
  a real, verified-working HuggingFace MNLI cross-encoder as an optional
  upgrade — never the same LLM grading its own claim.
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
  reports "not applicable" rather than a false pass/fail, so a coverage gap
  reads as a finding rather than a bug — `route_leak` used to be this
  project's own example of that (see Phase 2 below for why it no longer is).

Known limitation carried forward: RIPEstat's `bgplay` API (the obvious
lowest-effort choice) was tried first and rejected — live-checked, it only
retains roughly the last 1.5–2 years, which excludes the historical incidents
worth demonstrating against (2008 Pakistan Telecom/YouTube, 2019
Cloudflare/Verizon). The raw-archive approach above has no such limit.

## Pluggable toolsets + a real route-leak analyzer (Phase 2)

Phase 2's bar: analyzers become config-driven ("a new data source can be
added without touching the core loop") plus context-budget truncation on
tool output, mirroring HolmesGPT's YAML toolset model and its context
budgeting.

- `investigator/toolsets.toml` + `investigator/toolsets.py` replace the
  hardcoded analyzer imports that used to live in `analyzers/__init__.py`.
  TOML instead of YAML, deliberately: Python 3.11+'s stdlib `tomllib` keeps
  the "no install required for the core" claim true; same config-driven idea
  either way. A new analyzer = one new module implementing the unchanged
  `Analyzer` protocol + one `[[toolset]]` entry — zero edits to `engine.py`,
  `cli.py`, or the registry machinery. `InvestigationEngine` can rebuild the
  registry from a non-default manifest at construction time (see
  `reset_registry()` in `analyzers/base.py` and the reload-aware
  `register_enabled_analyzers()`), which is what makes `--toolsets` on the
  CLI actually change which analyzers run, not just cosmetic.
- `investigator/analyzers/route_leak.py` is the concrete proof of that
  extensibility, and closes a real gap: every `route_leak`-labeled catalog
  incident used to be an automatic `N/A` because no analyzer existed for
  that class. It's a heuristic, explicitly not policy-violation proof (real
  leak detection needs AS-relationship/customer-provider-peer data this
  project doesn't have): it flags a previously-uninvolved AS that suddenly
  becomes a shared interior AS_PATH hop, via 2+ distinct peers, for a prefix
  whose origin AS hasn't changed (an origin change is MOAS's signature, not
  this one's — the two analyzers are deliberately mutually exclusive on that
  axis). Verified against real data: correctly fires on `level3-comcast-2017`
  (a genuine `HIT` where it was previously a guaranteed miss-by-default), and
  correctly stays silent on incidents that don't show that pattern in the
  captured window — an honest result, not a padded one.
- `investigator/agent.py` gained context-budget truncation
  (`_truncate`/`_format_sources`): per-source and overall-block character
  caps (default 4000 chars, configurable via toolsets.toml's `[rfc_search]`
  table) guard the two places a ReAct prompt can grow unboundedly — a larger
  future RFC corpus, and the sources accumulated across multiple search
  rounds. Character-based, not a real tokenizer, so no new dependency;
  documented here as an approximation.

## Citation-correctness evaluation harness (Phase 3)

Distinct from `investigator/evaluate.py` (Phase 1.5), which scores whether
the *deterministic analyzers* detect the right incident type. This scores a
completely different axis: whether the *LLM's cited explanation* actually
says something its cited RFC passage supports — citation presence is not
citation correctness, and the plan is explicit that this must not become
gameable LLM-as-judge faithfulness scoring (RAGAS/TruLens/DeepEval).

- `investigator/evaluation/claims.py` segments a narrated `CitedAnswer` into
  individual `Claim`s (sentence-boundary regex + trailing `[n]` marker
  extraction) — a heuristic, not a real NLP sentence splitter, documented as
  such. An uncited claim is still a `Claim` (empty citation tuple), because
  "asserted nothing to back it up" is itself a real recall signal, not
  something to silently drop.
- `investigator/evaluation/entailment.py` defines one `EntailmentChecker`
  interface with two implementations, decided deliberately with the user
  rather than picking one: `LexicalOverlapChecker` (default, dependency-free
  token-overlap + negation-mismatch heuristic — same honesty pattern as BM25
  over dense embeddings) and `CrossEncoderNLIChecker` (real MNLI via a small
  HuggingFace cross-encoder, `cross-encoder/nli-deberta-v3-xsmall` — CPU-
  friendly, deliberately not Bespoke-MiniCheck-7B, whose GPU/Ollama cost the
  source plan itself flags as a risk). The cross-encoder path was installed
  and run for real in this environment (not just claimed): it correctly
  classified both an entailment and a contradiction test case. Selected via
  `[citation_eval].checker` in `toolsets.toml` (or `CITATION_CHECKER` env
  var as a lower-priority override) — same config-driven pattern as
  `[rfc_search]` from Phase 2.
- `investigator/evaluation/scorer.py` computes ALCE-style citation precision
  (of every citation actually placed, what fraction does its source entail)
  and recall (of every claim made, what fraction has >=1 entailing citation
  among its own), plus a RAGChecker-style retriever-vs-generator split for
  every recall miss: re-query the *full* corpus (not just what was cited,
  reusing `CitationEngine.retrieve_sources` from Phase 1) — if something
  uncited would have worked, that's a generator error; if nothing in the
  corpus supports the claim at all, that's a retriever error.
- **Not applicable in offline/no-LLM mode**, by design, not omission: a
  `NoOpBackend` answer is an echoed prompt, not real generated prose, so
  `score_citations()` detects its literal `"[no-LLM mode]"` marker and
  returns `applicable=False` with a stated reason rather than fabricating a
  score by "checking" the prompt's own instruction text as if it were a
  claim. `--score-citations` on the CLI surfaces this plainly.
- No live-LLM run of the full pipeline was possible in this environment (no
  API key configured) — verified via scripted-backend unit tests
  (`tests/evaluation/`) instead of an end-to-end live narration, stated here
  rather than glossed over.

## Deliberate limitations

- Retrieval is lexical BM25 only (no dense/hybrid yet) — good enough for RFC
  clause matching; hybrid dense retrieval is a later upgrade behind the same
  interface.
- The route-leak analyzer (see Phase 2 above) is a heuristic bounded by what
  a bare BGP update stream can show, not proof of an AS-relationship policy
  violation — stated in its own docstring, not just here.
- The agentic search loop (see "two-layer split" above) is real but
  low-value today given a 2-file RFC corpus; it earns its keep once the
  corpus is scaled up.
- No competing hypotheses, no citation-correctness scoring yet — those are the
  differentiators, intentionally deferred so the baseline ships first.
