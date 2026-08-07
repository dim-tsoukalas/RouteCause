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

Update: the RFC corpus was 2 hand-picked excerpt files when this limitation
was first written; it's now 16 full RFCs (945 chunks, see "RFC corpus
expansion" below). The multi-round search loop does have more real payoff
against the larger corpus — observed directly: the local Ollama backend used
its full 3-round search budget against the expanded corpus on the flagship
demo question, versus 1 round against the 2-file corpus. That extra search
did not translate into better *grounding*, though — see the corpus-expansion
section for why more search rounds over a bigger corpus produced a less
grounded answer, not a more grounded one.

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
| Adversarial contradiction retrieval | `investigator/retrieval/contradiction.py` | reuses Phase 1 retrieval + Phase 3 entailment checking |
| ACH reasoning + measured abstention | `investigator/ach.py` | Heuer's ACH; false-assertion rate measured in `investigator/evaluate.py --ach` |

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
- **Phase 4 ✅ (adversarial retrieval):** done — see below. The `Report`'s
  reserved hypotheses/contradiction slot turned out to be unnecessary as a
  data-model change: `--seek-contradictions` is a post-hoc CLI pass over an
  already-built `Report`, the same pattern `--score-citations` established,
  not a new field threaded through `investigate()`.
- **Phase 5 ✅ (abstention / ACH):** done — see below. The `min_score` floor
  and `INSUFFICIENT EVIDENCE` marker were indeed the seed, as anticipated;
  the ACH matrix and false-assertion measurement are built on top of
  Phase 4's `Hypothesis`/`ContradictionCheck`, not new infrastructure. The
  first measured outcome (100% abstention on the real catalog) was a
  genuine finding, not a shipped-and-forgotten number, and led directly to
  the two-tier evidence bar follow-up (3 correct assertions, 0 false,
  2-file corpus) — see below. Re-measured again after the RFC corpus
  expansion: 3 correct, **1 false**, 9 abstained — a real regression,
  diagnosed rather than absorbed into the earlier number; see "RFC corpus
  expansion" below and
  [docs/corpus-expansion-results.md](corpus-expansion-results.md).

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
  documented here as an approximation. **Verified against the real
  mechanism, not assumed equivalent** (docs/alignment-plan.md item 5): the
  real HolmesGPT caps each tool to a *percentage* of the model's actual
  context window (`TOOL_MAX_ALLOCATED_CONTEXT_WINDOW_PCT`, default 15%)
  with an absolute *token* ceiling (`TOOL_MAX_ALLOCATED_CONTEXT_WINDOW_TOKENS`,
  default 25K), plus a separate compaction step that summarizes old
  conversation history once the running total nears the window, and can
  spill very large tool output to disk. This project's fixed character
  count mirrors the *spirit* (bound what one search adds to the prompt) but
  not the mechanism (no percentage-of-window scaling, no token counting, no
  compaction, no disk spillover) — a real, meaningful gap, not glossed
  over now that it's been checked against the source.

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
- `investigator/evaluation/scorer.py` computes ALCE's actual statement-level
  definitions (Gao et al., 2023), not an approximation of them. **Recall**
  for a claim is 1 iff it has >=1 citation and the *concatenation* of all its
  cited sources entails it — not "at least one cited source, alone, entails
  it." That distinction bites exactly where RFC grounding lives: a claim
  jointly supported by two passages that are each insufficient alone (e.g.
  RFC 7908 §4 + RFC 4271 §9.1.2 grounding one MOAS claim, neither sufficient
  alone) scores 1 under ALCE, 0 under the naive rule — a real gap an earlier
  revision of this scorer had, caught and fixed, with
  `test_joint_citation_support_counts_toward_alce_recall_and_precision`
  (`tests/evaluation/test_scorer.py`) as the regression test.
  **Precision** is gated on that per-claim recall (ALCE's own rule — an
  unsupported claim's citations aren't "wrong," the claim itself is) and,
  within a recall-met claim, a citation counts as precise if it entails the
  claim alone *or* removing it from the cited set breaks the concatenation's
  entailment (load-bearing even if insufficient alone); a citation droppable
  with no loss of support is redundant, not precise. Plus a RAGChecker-style
  retriever-vs-generator split for every recall miss: re-query the *full*
  corpus (not just what was cited,
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

## Adversarial / contradicting-evidence retrieval (Phase 4)

"Hypothesis" has no prior meaning in this codebase — decided here to mean
the claim behind one *fired* deterministic analyzer `Result` (its `kind` +
`details`), not a new generation step. The observations Layer 1 already
computes are the things worth interrogating; when multiple analyzers fire on
one incident (real cases seen this session: `pakistan-youtube-2008` fires
both MOAS and RouteLeak; `rostelecom-2020` fires three), those are genuinely
competing claims about the same evidence.

- `investigator/retrieval/contradiction.py`: `hypotheses_from_results()`
  turns fired `Result`s into `Hypothesis`es; `seek_contradictions()` retrieves
  broadly around a hypothesis's own topic (`CitationEngine.retrieve_sources`,
  unchanged from Phase 1) and classifies each candidate's *stance* with the
  Phase 3 `EntailmentChecker`, keeping only `CONTRADICTS`-labeled passages as
  refuting evidence. Deliberately not query negation: lexical BM25 doesn't
  understand negation semantics, so the entailment model — not query
  phrasing — is what's responsible for identifying contradiction, matching
  the source plan's own emphasis that refutation must be "verified... not
  asserted."
- This required extending Phase 3's `EntailmentLabel` with a 4th value,
  `CONTRADICTS`, split out from the generic `NOT_ENTAILED` bucket (which
  used to conflate "actively refutes" with "source just doesn't address
  this"). Backward compatible with `evaluation/scorer.py` (only ever checks
  `== ENTAILED`) — confirmed by re-running the full Phase 3 suite, not
  assumed.
- `--seek-contradictions` on `investigate` (not `ask`, which has no analyzer
  results to form hypotheses from) — a post-hoc CLI pass over the built
  `Report`, same pattern as `--score-citations`.

**Verified, reported limitation — not glossed over, and re-verified after a
fix, not left at the first finding:** run for real against
`pakistan-youtube-2008`, both the lexical checker *and* the real
cross-encoder model (initially `nli-deberta-v3-xsmall`, ~22M params, chosen
for speed) mislabeled RFC 4271 §9.1.2 (AS_PATH loop detection) as
`CONTRADICTS` a MOAS claim about origin-ASN counts — genuinely unrelated
topics, not a refutation. This raised an obvious question: is a bigger
*specialized* entailment model (not a general-purpose LLM-as-judge, which
stays out of scope for the reasons above) actually more accurate here, or is
the failure mode fundamental regardless of size? Tested directly rather than
argued in the abstract: swapping to `nli-deberta-v3-base` (~184M) fixed the
MOAS case *and* a second one (ASPathLoop vs. the same RFC section), while
still correctly handling the original clear-cut entailment/contradiction
test cases — a real, measured improvement, not just a different failure
mode. It did **not** fix a third case (RouteLeak vs. the same RFC section),
which reads as a more genuinely borderline pairing (both concern AS_PATH
mechanics) rather than as clear-cut a mismatch as the MOAS case was.
`-base` is now the default. Separately, fixing this surfaced a real bug: the
`CITATION_CHECKER` env var was silently dead code, because
`toolsets.toml`'s `[citation_eval].checker = "lexical"` was always present
and always took priority over it — the env var could never actually select
the cross-encoder through the CLI. Fixed by having the env var take
priority when set (`investigator/evaluation/entailment.py`'s
`default_checker()`).

Net honest conclusion: model capacity measurably reduces this failure mode,
it does not eliminate it. NLI models are known to over-rely on negation-word
*presence* as a shortcut cue (RFC prose is full of routine "MUST NOT"/"not
X" normative language unrelated to any given claim), and the 2-file corpus
is small enough that BM25 has little to choose from, so topically-adjacent-
but-unrelated passages clear its relevance floor more easily than they
should. Treat `contradicting` output as a signal worth human review, not a
settled verdict — the same caution already applied to MOAS's "presumed
legitimate origin" heuristic. A larger, more topically-diverse RFC corpus
remains the most likely further fix; not attempted here.

### The Phase 3/4 checker split (docs/alignment-plan.md item 3)

One `EntailmentChecker` instance did both jobs above Phase 3 (citation
correctness: does the *cited* source support this specific claim) and
Phase 4 (does this passage *refute* this hypothesis). The source plan
argued this conflation explains the AS_PATH-vs-MOAS false positive above,
and prescribed two purpose-built models instead of one general one:
`lytang/MiniCheck-Flan-T5-Large` (MIT, 0.8B, purpose-trained claim-vs-
document grounding, binary by design) for Phase 3, and
`MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli` (MIT, 435M,
genuine 3-way NLI trained partly on ANLI — adversarially collected
specifically to break lexical-overlap/negation-shortcut heuristics) for
Phase 4, requiring `CONTRADICTS` to beat both `ENTAILED` and `UNCLEAR` by a
margin before counting as counter-evidence. Both implemented as new
`EntailmentChecker`s (`MiniCheckSupportChecker`,
`MarginNLIContradictionChecker`, `investigator/evaluation/entailment.py`),
selected independently via `default_support_checker()` /
`default_contradiction_checker()` and
`[citation_eval].support_checker` / `.contradiction_checker` in
`toolsets.toml` — additive, opt-in, `lexical` stays the shipped default for
both, same pattern as `cross_encoder` before it.

**Correction to the source plan's own diagnosis, found while implementing
it:** it claimed "your pipeline has no neutral." Not accurate —
`EntailmentLabel.UNCLEAR` already existed, and `CrossEncoderNLIChecker`
already mapped a 3-way model's "neutral" output to it; the two-tier
evidence bar (Phase 5, below) is built entirely on that existing tier. The
real mechanism was narrower: even a real 3-way model's raw argmax
sometimes still picked `CONTRADICTS` over `NEUTRAL` on this exact case
(the documented negation-shortcut bias), not that the pipeline had nowhere
to put "neutral" if a model said so. The plan's *prescription* — a bigger,
ANLI-trained model, a margin requirement, used only for the contradiction
job — still measurably works; the diagnosis's wording was wrong, the fix
wasn't.

**Re-tested directly, not assumed fixed by a bigger model:** ran
`MarginNLIContradictionChecker` against the exact documented case (RFC
4271 §9.1.2's AS_PATH loop-detection text vs. the real MOAS analyzer's `"2
origin ASNs observed for a single prefix."` statement, both pulled
verbatim from the running system, not paraphrased) —
**99.5% neutral, 0.4% contradiction.** Fixed. Covered by a permanent
regression test,
`tests/evaluation/test_entailment.py::test_margin_nli_contradiction_checker_fixes_the_documented_as_path_false_positive`,
alongside a sanity check that the same checker still correctly flags a
genuine contradiction
(`test_margin_nli_contradiction_checker_still_detects_genuine_contradiction`).

**Real installation friction, reported rather than smoothed over:** the
PyPI package literally named `minicheck` is an unrelated formal-
verification tool (`check_liveness`, `z3_available`, TLA+/Promela export)
— a name collision, not the fact-checking model. The real package installs
from GitHub:
`pip install "minicheck @ git+https://github.com/Liyan06/MiniCheck.git@main"`.
Two more runtime dependencies surfaced only by actually running it, not
listed on the model card: `accelerate` (transformers' `device_map="auto"`
requires it) and NLTK's `punkt_tab` tokenizer data (`nltk.download("punkt_tab")`).

**Measured against the real 13-incident catalog — and the result is the
opposite of what the narrow re-test predicted.** Swapping
`MarginNLIContradictionChecker` in as the production contradiction checker
(`CITATION_CONTRADICTION_CHECKER=nli_margin python -m investigator.evaluate
--ach`) does not improve the false-assertion rate; it craters it: **0
correct assertions, 1 false assertion, 12 abstained** (was 3 correct, 1
false, 9 abstained with the default lexical checker on the same expanded
corpus). `pakistan-youtube-2008` and `china-telecom-18min-2010` — both
previously *correct* `MOAS` assertions — now abstain outright.

**Diagnosed, not just measured, because the isolated fix above was real and
this result needed explaining, not dismissing.** `rank_hypotheses()`
(`investigator/ach.py`) has a gate that runs *before* the two-tier
relevant-vs-contradicting comparison: `if all(s.supporting_count == 0 for s
in scores): abstain`. `supporting_count` is the count of sources this
checker calls strict `ENTAILED` — and this specific model is dramatically
more conservative about that label than the lexical checker was. Verified
directly: the two chunks the lexical checker called "strict entailment"
support for `pakistan-youtube-2008`'s MOAS hypothesis (RFC 6811 §2.1 —
literally pseudo-code — and RFC 7454 §6.1.2.2, generic RIR-filter prose)
both score `UNCLEAR` under `MarginNLIContradictionChecker` (0.62 and 0.999
neutral respectively) — arguably a *more correct* judgment (pseudo-code
doesn't semantically entail "2 origin ASNs observed for a single prefix"),
but it means `supporting_count` collapses to 0 for most hypotheses on most
incidents, re-triggering almost exactly the original 100%-abstention
problem the two-tier bar was built to fix in the first place (see above) —
just via a stricter, better-calibrated entailment judgment instead of a
demanding threshold.

The one new false assertion (`indosat-2014`, expected `prefix_hijack`/MOAS,
asserts `[ASPathLoop]` instead) reveals a second, structural pattern, not a
fluke: `ASPathLoop`'s hypothesis template ("N announcement(s) with a
repeated ASN in AS_PATH") is a near-paraphrase of RFC 4271's own
loop-detection definition, so it systematically clears strict entailment
more easily than MOAS or RouteLeak's phrasing does — a property of how
closely each analyzer's own statement wording happens to mirror RFC
phrasing, orthogonal to which hypothesis is actually correct for the
incident.

**Conclusion: the isolated re-test and the system-level re-test both
happened and both are reported, even though they point in opposite
directions.** `MarginNLIContradictionChecker` demonstrably fixes the one
documented false positive it was built to fix. It is *not* recommended as
a wholesale replacement for the production contradiction checker without
also addressing `rank_hypotheses()`'s hard dependency on `supporting_count
> 0` — likely by decoupling "is this genuinely a strict match" from
whichever checker also does the contradiction classification, a real
follow-up, not attempted here. Stays available, opt-in only
(`CITATION_CONTRADICTION_CHECKER=nli_margin` or
`[citation_eval].contradiction_checker = "nli_margin"`), `lexical` remains
the shipped default.

## Competing-hypothesis (ACH) reasoning + measured abstention (Phase 5)

The last phase of the original 0–5 plan: enumerate hypotheses, score each
against combined supporting+refuting evidence, and abstain when no
hypothesis clears an evidence threshold, reporting a false-assertion rate.
Built almost entirely on Phase 4's existing `Hypothesis`/`ContradictionCheck`
objects — `investigator/ach.py` is composition, not new retrieval or
entailment infrastructure.

**Deliberately not Self-RAG reflection tokens or an LLM "reflecting" on its
own evidence sufficiency** (the source plan's suggested scaffolds): that
would reintroduce the self-critique problem arXiv:2310.01798 ("LLMs Cannot
Self-Correct Reasoning Yet") found unreliable — the same reasoning that
already kept Phase 4's contradiction search retrieval-and-entailment-
verified rather than generator-asserted. The abstention decision here is a
fully computed function of hard evidence counts; no model ever judges
itself.

**Ranking rule** (`rank_hypotheses` in `investigator/ach.py`): Heuer's ACH
insight is to minimize *disconfirmation*, not maximize confirmation, so
hypotheses are ranked by fewest contradicting sources first, ties broken by
most supporting. **A real bug was found and fixed while measuring this
against the actual 13-incident catalog, not in the abstract:** the original
rule let a hypothesis with *zero* evidence found either way outrank one with
real (if mixed) evidence, because Phase 4's per-hypothesis independent
retrieval means "found nothing" and "found something and got it partly
wrong" aren't naturally comparable on contradicting-count alone. Fixed by
requiring genuine supporting evidence as the primary sort key — a hypothesis
nobody could find any evidence for now always ranks behind one with real
support, and abstains outright if *no* hypothesis found any.

**Measured, not asserted: the false-assertion rate is `n/a` (100%
abstention) against the real catalog, with both entailment checkers.** This
was checked end-to-end, including diagnosing *why*, not just reported as a
number:
1. Before the ranking-rule fix: 100% *false*-assertion rate — the bug above
   plus Phase 4's known entailment-precision issue compounded badly.
2. After the fix: 0 false assertions (good — the fix works), but also 0
   correct assertions. Every incident abstains.
3. Root cause, traced concretely (e.g. `pakistan-youtube-2008`'s MOAS
   hypothesis): even the real cross-encoder model refuses to call RFC 7908
   §4 "supporting" evidence for a specific claim like "2 origin ASNs
   observed for this prefix" — correctly, since the RFC says a MOAS is "a
   strong *indicator* of" a hijack, hedged/definitional language, not a
   claim that strictly *entails* this particular incident's specifics. This
   is a **structural mismatch**, not a bug: RFC citations were designed as
   contextual/definitional grounding (and work well for that — see Phase 1's
   citation engine), not as case-specific logical proof, which is a
   materially stricter bar.

This was shipped deliberately, not left broken: a mechanism that correctly
recognizes its evidence doesn't clear a real bar and says so is a legitimate,
defensible result — safer than one that asserts anyway. But it was also a
diagnosed, not just accepted, dead end — the root cause above pointed at a
specific, checkable fix, so it was built and re-measured rather than left as
a documented limitation.

**Follow-up fix: the two-tier evidence bar.** `ContradictionCheck` (Phase 4)
already computed a middle `UNCLEAR` entailment label — on-topic, real
vocabulary overlap, just short of the strict `ENTAILED` bar — and silently
discarded it. `investigator/ach.py`'s net-refuted gate now compares
`contradicting_count` against `relevant_count` (`ENTAILED` + `UNCLEAR`)
instead of the strict `supporting_count` alone; the strict count is still
computed and reported alongside every verdict as the conservative,
labeled-separately number — this widens *which bar an assertion is measured
against*, not what counts as evidence in the first place. Concretely, for
`pakistan-youtube-2008`'s MOAS hypothesis: 1 strict-entailed source + 1
further topically-relevant (`UNCLEAR`) source = 2, no longer outweighed by
its 2 `CONTRADICTS` sources — one of which is exactly the documented RFC
4271 §9.1.2 lexical false positive above, riding in on a negation-mismatch
against the shared, contentless token "2". Re-measured against the real
13-incident catalog (`investigator/evaluate.py --ach`): **3 correct
assertions, 0 false assertions, 10 honest abstentions** (`pakistan-
youtube-2008`, `indosat-2014`, `china-telecom-18min-2010` — the same
MOAS-with-genuine-strict-support pattern in all three). Nothing that
previously abstained correctly now flips to a wrong answer; the fix only
unlocks assertions where real evidence was already present and only being
outvoted by a documented retrieval/entailment artifact. All of the above is
against the 2-file corpus.

### RFC corpus expansion (was Phase 6, now done)

Expanded from 2 hand-picked excerpts to the full alignment-plan target list
— 16 RFCs (4271, 4272, 7908, 9234, 8212, 7454, 6811, 6480, 8205, 8206, 8207,
4760, 1997, 4456, 5065, 2439), 945 chunks after cleaning + chunking. Full
diagnosis in
[docs/corpus-expansion-results.md](corpus-expansion-results.md); summary
here.

**Two bugs, both invisible against 2 hand-picked excerpts, both only found
by actually running the cleaner over all 16 real RFCs:**
`investigator/retrieval/corpus.py`'s `_SECTION_RE` matched
Table-of-Contents entries and body numbered-list items as section headers
(both are digits-and-dots; the old regex didn't check indentation, and real
IETF headers are always flush at column 0 while TOC/list-item lines are
always indented). And the preamble-skip logic (Status of This Memo /
Copyright Notice / Table of Contents) only recognized *numbered* section
headers as the point to resume keeping text — RFC 1997 (1996-era, headings
like "Abstract"/"Introduction", never numbers a single section) lost its
**entire body** to this, caught only because all 16 target RFCs were run
through the cleaner, not assumed to generalize from RFC 4271 alone. Both
fixed and covered by `tests/test_corpus.py`.

**A third thing needed recalibration, not a bug fix:** `CitationEngine
.min_score` was an absolute BM25 score floor calibrated against a
2-document index — `idf(term)` rises with corpus size for a term whose
document frequency stays flat, so that floor gets easier to clear as the
corpus grows, for reasons unrelated to relevance (verified empirically:
the same off-topic-but-lexically-loaded chunk's score climbed ~19x as a
padding corpus grew from 1 to 501 chunks in `tests/test_citations.py`).
Added `BM25.max_possible_score()` (the idf-based saturation ceiling for a
query) and an opt-in `CitationEngine(min_score_fraction=...)` that gates on
a fraction of that ceiling instead — scale-invariant, additive on top of
`min_score` so no existing caller's behavior changed. The first fraction
tried (0.2) was wrong: calibrated against this real corpus with real
multi-term incident questions, the flagship MOAS query scored ratio 0.161
— genuinely on-topic, but *below* an unrelated "kubernetes ingress
controller" query's 0.219. Ratio-to-ceiling does not cleanly separate
on-topic from off-topic on real natural-language queries the way it does on
a synthetic single/double-term test case; recalibrated to 0.1, deliberately
conservative, documented in `DEFAULT_MIN_SCORE_FRACTION`'s docstring as
guarding against corpus-size drift specifically, not as a general relevance
classifier (that remains BM25's known, pre-existing, and still-unaddressed
limitation — see "Deliberate limitations" below).

**Re-measured `--ach` against the expanded corpus: 3 correct assertions,
1 false assertion, 9 honest abstentions** — worse on the headline metric,
not better, and reported as such rather than adjusted after the fact.
`cloudflare-verizon-2019` (expected `route_leak`) flipped from a correct
abstention to a false `[ASPathLoop]` assertion. Diagnosed, not just
measured: this incident's catalog entry already documents no `RouteLeak`
finding fires for it (a pre-existing detection-layer gap, unrelated to the
RFC corpus); under the 2-file corpus `ASPathLoop` had zero evidence either
way, so ACH correctly abstained, but the expanded corpus gave `ASPathLoop`
genuine, checker-verified evidence (RFC 6811 §2 / RFC 7908 §2 do strictly
entail "a repeated ASN in AS_PATH is a real signal," and this incident's raw
MRT data genuinely has 23 such repeats) — a true statement that isn't the
same thing as "this incident's root cause was a route leak." ACH's own
genuine-evidence-beats-zero-evidence ranking rule (the fix earlier in this
section) then correctly picks the strongest hypothesis *among the ones the
analyzer layer actually produced*, which isn't the right one, because the
deterministic layer never produced a `RouteLeak` finding for this incident's
data pattern. **Not patched here, deliberately** — loosening or tightening
the evidence bar specifically to make this one case abstain again would be
the "loosen the bar until it passes" anti-pattern the two-tier design above
exists to avoid; the real fix is closing the detection-layer gap, out of
scope for a corpus swap.

Of the 6 baseline "no evidence found at all" abstentions this expansion was
expected to help, 5 changed outcome: 1 became the false assertion above; 4
(`twitter-rtcomm-2022`, `klayswap-2022`, `rostelecom-2020`,
`level3-comcast-2017`) now have real evidence weighed on both sides but net
refuted, a materially more informative abstention than "found nothing" even
though still an abstention; 1 (`amazon-route53-mew-2018`) is genuinely
unchanged — even 16 RFCs of BGP-security text has nothing topically close
enough to that incident's specific finding.

**Real LLM narration also got measurably worse, for a different reason —
see docs/corpus-expansion-results.md for the full transcripts.** Re-running
the flagship `pakistan-youtube-2008` demo against the expanded corpus:
the hosted backend (`claude-haiku-4-5`), which answered confidently before
(100%/60% precision/recall), now abstains outright on the literal same
question — retrieval surfaces more, more topically diffuse sources, and the
model chose not to assert from them. The local backend (`llama3.1:8b`),
which scored 33%/33% before, now scores **0%/0%** while sounding *more*
confident — it composed fluent prose citing real BGPsec/RPKI RFC sections
that don't actually say what its sentences claim. A bigger corpus gave a
weaker model more plausible-sounding material to draw from without its
grounding discipline improving to match; `--score-citations` is exactly the
mechanism that catches this, and without it this would read as a *better*
answer, not a worse one.

## Deliberate limitations

- Retrieval is lexical BM25 only (no dense/hybrid yet). The RFC corpus
  expansion (above) made this limitation *more* visible, not less: BM25's
  lexical-coincidence false-positive rate (a query matching one rare corpus
  term can outrank a genuinely on-topic multi-term query) doesn't improve
  with more text, and `min_score_fraction`'s calibration against real
  queries confirmed it directly — a "kubernetes ingress controller" query
  outscored the flagship on-topic MOAS query on ratio-to-ceiling. Hybrid
  dense retrieval is the planned fix, behind the same `CitationEngine`
  interface, not attempted here.
- The route-leak analyzer (see Phase 2 above) is a heuristic bounded by what
  a bare BGP update stream can show, not proof of an AS-relationship policy
  violation — stated in its own docstring, not just here. The corpus
  expansion's one new false assertion (`cloudflare-verizon-2019`, see
  above) traces directly to this analyzer not firing for that incident's
  data pattern, not to anything RFC-corpus-related — a concrete case of
  this limitation actually biting, not a hypothetical one.
- The agentic search loop (see "two-layer split" above), adversarial
  contradiction retrieval (Phase 4), and ACH reasoning (Phase 5) were all
  real but corpus-bound against the 2-file RFC corpus; the RFC corpus
  expansion (above) is that fix, done — the ACH false-assertion rate moved
  from 0/3 to 1/4, and 5 of 6 previously-uninformative abstentions now have
  real evidence weighed. Both directions are reported, not just the
  favorable one — see [docs/corpus-expansion-results.md](corpus-expansion-results.md).
- All six phases of the original build plan (0–5), plus the RFC corpus
  expansion from Phase 6, are now done. Remaining future work: hybrid dense
  retrieval (the item the corpus expansion most concretely motivates now —
  see above), a claims→sources provenance graph, and live BGP feed
  integration — all effort-gated, none started here.
