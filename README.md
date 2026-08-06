# network-investigator

A citation-grounded network-incident investigator. It analyzes BGP incident
evidence with **deterministic analyzers** (no LLM in the detection path) and
explains them using **cited passages from RFCs**, refusing to answer when it
can't ground a claim in a source.

> **Phase 1 (baseline parity) through Phase 5 (competing-hypothesis
> reasoning) are all done** — see [Roadmap](#roadmap). Deterministic
> anomaly detection, cited RFC retrieval, adversarial counter-evidence
> search, and measured abstention are the differentiators over a plain
> cited-QA tool; the incident below is the real, end-to-end result of all
> four working together.

## What I found

Worth reading even if you skip the code — each found by actually measuring
against real data, not asserted in a design doc:

- **RFC citations are definitional grounding, not case-specific proof.**
  Measuring the ACH system against all 13 real catalog incidents first
  produced 0 correct assertions — it abstained on every one, including
  `pakistan-youtube-2008`, where the leading hypothesis was actually right.
  The cause was structural: RFC text like "an unexpected change in origin AS
  is a strong indicator of a hijack" is hedged, general-purpose grounding, so
  it can't *strictly entail* "these specific 2 ASNs did it here" — no matter
  how good the checker is. That distinction became a deliberate, labeled
  two-tier evidence bar (`investigator/ach.py`) — "topically supports" vs.
  "strictly entails" — which turned that same incident into a correct,
  honestly-reported assertion instead of a silent abstention.

- **A bigger entailment model measurably helped — but didn't fix the
  underlying failure mode.** Both the cheap lexical checker and a real
  22M-parameter cross-encoder NLI model (`nli-deberta-v3-xsmall`) made the
  same mistake: flagging RFC 4271's *AS_PATH loop-detection* section as
  `CONTRADICTS`-ing a completely unrelated MOAS claim, apparently because
  both texts happen to contain the word "not." Swapping to the
  184M-parameter `-base` checkpoint fixed that case and a second one
  outright without breaking anything that already worked — a real, measured
  improvement, not an assumed one. It left a third, genuinely borderline
  case unresolved, confirming the honest conclusion: model capacity reduces
  this negation-shortcut failure mode, it doesn't eliminate it.

- **A ranking bug that only showed up against real, messy data.** The first
  version of ACH's ranking rule sorted hypotheses by fewest-contradictions-
  first, straight out of Heuer's method. Running it against the real catalog
  surfaced a bug no hand-written test had caught: a hypothesis nobody could
  find *any* evidence for was beating one with real, if mixed, supporting
  *and* contradicting evidence, purely because zero contradictions beat
  some. The fix makes genuine supporting evidence the primary sort key so an
  evidence-free hypothesis can no longer win by default — it's now a
  permanent regression test
  (`test_zero_evidence_does_not_beat_genuine_mixed_evidence`).

- **Real model narration finds citation gaps synthetic tests never could.**
  `--score-citations` had only ever scored `NoOpBackend`'s echoed prompt or
  hand-written fixtures — both trivially "cite" their own source text. Pointed
  at actual generated prose for the first time (`claude-haiku-4-5` hosted,
  `llama3.1:8b` local via Ollama, same incident, same question, against the
  2-RFC corpus): the hosted run scored 100% citation precision but only 60%
  recall — two of five generated claims had no supporting passage anywhere in
  the corpus, i.e. the model editorialized past what its own cited source
  actually said. The local run did worse and differently: 33%/33%, with both
  a retriever error *and* a generator error (a claim the corpus could have
  supported but that didn't get cited). Neither failure mode is visible until
  real model output — with all its variance across providers — is actually in
  the loop.

- **A bigger RFC corpus is not an unconditional improvement — measured, not
  assumed.** Expanding from 2 hand-picked excerpts to 16 full RFCs (945
  chunks) was expected to reduce abstentions. It did, for some incidents —
  but it also produced this project's **first false ACH assertion** (0% → 25%
  false-assertion rate) and made the flagship demo's *local* model narration
  measurably worse (33%/33% citation precision/recall → 0%/0%), because a
  larger, topically denser corpus gives a weaker model more plausible-
  sounding material to draw from without its grounding discipline improving
  to match — it name-drops real RFC sections that don't actually say what its
  sentences claim. The hosted model, given the same larger corpus, abstained
  outright on the same question it answered confidently before. All three are
  diagnosed, not just reported, in
  [docs/corpus-expansion-results.md](docs/corpus-expansion-results.md) — the
  false assertion traces to a pre-existing detection-layer gap the bigger
  corpus exposed rather than caused. See
  [Real LLM narration](#real-llm-narration-hosted--local) below for the
  current transcript.

## See it work: the 2008 Pakistan Telecom / YouTube hijack

Real MRT archive data (RIPE RIS + RouteViews, 2008-02-24 18:47–20:54 UTC) for
the incident where Pakistan Telecom (AS17557) originated YouTube's
`208.65.153.0/24` in response to a government block order, and the
more-specific route leaked globally via PCCW (AS9491), hijacking YouTube
traffic worldwide. No synthetic data, no cherry-picked prompt. This is

```bash
INVESTIGATOR_MODEL=ollama/llama3.1:8b investigate pakistan-youtube-2008 \
  --question "Using the reference corpus, explain why a prefix (208.65.153.0/24) being announced by two distinct origin ASNs (AS17557 and AS36561) is treated as a strong indicator of a hijack or misconfiguration, and what validation step is recommended." \
  --seek-contradictions --score-citations
```

after [install](#install) with the `llm` extra, against the full 16-RFC
corpus (see [Real incidents](#real-incidents-ripe-ris--routeviews)), trimmed
only for length (evidence lists are collapsed with `…`):

```
## Observations (computed from evidence)
### [CRITICAL] MOAS — 208.65.153.0/24
- Prefix 208.65.153.0/24 was announced by 2 distinct origin ASNs
  (AS17557, AS36561). Expected a single origin; presumed legitimate origin
  is AS17557. (ground in: BGP origin AS semantics and prefix hijack (MOAS))
- Anomalous origin AS36561 advertised 208.65.153.0/24 (59 announcement(s)).
  - Evidence:
    - rrc00@2008-02-24T20:07:25Z ANNOUNCE 208.65.153.0/24 origin=AS36561
      path=[3549 36561] peer=AS3549
    - …and 58 more

## Explanation (grounded in reference docs)
The presence of a prefix (208.65.153.0/24) being announced by two distinct
origin ASNs (AS17557 and AS36561) is treated as a strong indicator of a
hijack or misconfiguration because it violates the security guarantees
provided by BGPsec when used in conjunction with origin validation
[RFC 8205 §8.1]. Specifically, according to RFC 8205 §4.1, a BGPsec speaker
should only originate a BGPsec UPDATE message advertising a route for a
given prefix if there exists a valid ROA authorizing the BGPsec speaker's AS
to originate routes to this prefix [RFC 6482]. …

Sources:
  [1] RFC 8206 §3.1   [2] RFC 8205 §4.1   [3] RFC 6811 §2.1   [4] RFC 8205 §8.1

Citation-correctness scorecard (checker: lexical_overlap):
  claims: 4
  citation precision: n/a
  citation recall: 0%
  retriever errors (no corpus support found): 3
  generator errors (corpus had support, not cited): 1
  [MISS] (uncited) The presence of a prefix … is treated as a strong
       indicator of a hijack or misconfiguration because it violates the
       security guarantees provided by BGPsec …
        -> retriever error
  [MISS] (uncited) Specifically, according to RFC 8205 §4.1, a BGPsec
       speaker should only originate … if there exists a valid ROA
       authorizing … [RFC 6482].
        -> generator error
  [MISS] (uncited) The presence of two distinct origin ASNs indicates that
       either one or both … have not been authorized … to originate route
       advertisements for the given prefix …
        -> retriever error
  [MISS] (uncited) This is further supported by RFC 6811 §2.1, which
       illustrates a procedure for validating prefixes …
        -> retriever error

Competing considerations (verified counter-evidence, not asserted):

[MOAS] 2 origin ASNs observed for a single prefix.
  Counter-evidence found (verified by entailment checker):
    - RFC 8206 §1.2
    - RFC 8206 §3
  Supporting evidence (strict entailment):
    - RFC 6811 §2.1
    - RFC 7454 §6.1.2.2

ACH ranking (least-refuted first):
  1. [MOAS] 2 origin ASNs observed for a single prefix.
     -- 2 topically-relevant (2 strictly entailed), 2 contradicting
  2. [ASPathLoop] 10 announcement(s) with a repeated ASN in AS_PATH.
     -- 1 topically-relevant (1 strictly entailed), 3 contradicting
  3. [RouteLeak] 1 new transit AS(es) appeared mid-window, origin unchanged.
     -- 0 topically-relevant (0 strictly entailed), 4 contradicting
Verdict: leading hypothesis is [MOAS] 2 origin ASNs observed for a single
prefix. (asserted on relevance-tier evidence: 2 vs 2 contradicting;
conservative strict-entailment count: 2)
```

This transcript is shown warts and all, on purpose: the detection and ACH
layers are still exactly right (MOAS, correctly, same verdict as the 2-RFC
corpus) but the local model's narration is **not** — it reads fluently and
cites four real RFC sections, and every single one of those citations is
wrong (`0%` recall). This is precisely the failure `--score-citations`
exists to catch, and it's a materially worse result than this same command
produced against the smaller 2-RFC corpus (33%/33%) — a bigger, more
topically diverse corpus gave the model more plausible-sounding material to
draw from without its grounding discipline improving to match. See
[Real LLM narration](#real-llm-narration-hosted--local) for the hosted-model
comparison (which abstained outright on this exact question) and
[docs/corpus-expansion-results.md](docs/corpus-expansion-results.md) for the
full diagnosis, including why this is being shown here rather than swapped
for a more flattering question.

Real archive data → deterministic MOAS detection → real model narration
(local, via LiteLLM/Ollama) → citation-correctness scoring that catches the
narration's ungrounded citations → adversarial counter-evidence search (two
of MOAS's four candidate sources got flagged as *refuting* it) → a
competing-hypothesis verdict that survives that contradiction anyway,
reported against **two labeled evidence bars** ("strictly entailed" and
"topically relevant") rather than one bar loosened until it passes.
Measured, not cherry-picked: `investigator/evaluate.py --ach` runs the
detection + retrieval pipeline over all 13 real catalog incidents and
reports **3 correct assertions, 1 false assertion, 9 honest abstentions**
against the expanded corpus (was 3/0/10 against the 2-RFC corpus) — see
[What it does](#what-it-does--and-deliberately-does-not--do-yet) and
[docs/corpus-expansion-results.md](docs/corpus-expansion-results.md) for the
diagnosed false assertion.

### Real LLM narration (hosted + local)

The transcript above is the local model; the same question, same incident,
same corpus, run against a **hosted** backend (`claude-haiku-4-5` via
LiteLLM) behaves completely differently: it **abstains outright**, where
against the smaller 2-RFC corpus it answered confidently (100%/60%
precision/recall). With more, more topically diffuse sources retrieved for
this exact question, the model chose `FINAL: INSUFFICIENT EVIDENCE` over
asserting from what it retrieved — arguably the right call given what it
saw, but it means there's no hosted narration to show here anymore. Both
backends are exercised by `investigator/llm.py`'s `LiteLLMBackend` — this is
provider parity actually run, not just claimed, and provider variance is
itself part of what's being measured:

| | 2-RFC corpus: `claude-haiku-4-5` | 2-RFC corpus: `llama3.1:8b` | 16-RFC corpus: `claude-haiku-4-5` | 16-RFC corpus: `llama3.1:8b` |
|---|---|---|---|---|
| Outcome | answered | answered | **abstained** | answered |
| Claims made | 5 | 3 | 0 | 4 |
| Citation precision | 100% | 33% | n/a | n/a (0 entailed) |
| Citation recall | 60% | 33% | n/a | **0%** |

Neither backend was fully grounded even against the small corpus (the hosted
model asserted two claims the corpus didn't support; the local model did
worse, missing a claim entirely and failing to cite a passage that would
have supported another). Against the expanded corpus, the hosted model
became *more* conservative and the local model became *less* grounded while
sounding more confident — two different, both real, reactions to the same
change in retrieval breadth. This is exactly the differentiator Phase 3
exists to measure, and it was invisible until real model output — not
`NoOpBackend`'s echoed prompt, not a hand-written fixture — was actually
scored, twice, against two different corpus sizes. See
[docs/corpus-expansion-results.md](docs/corpus-expansion-results.md) for the
full before/after and diagnosis.

## Install

```bash
pip install -e .

investigate pakistan-youtube-2008
investigate pakistan-youtube-2008 --seek-contradictions
ask "how is a BGP AS_PATH loop detected?"
```

`investigate` and `ask` are console-script entry points (`pyproject.toml`'s
`[project.scripts]`) — the core (analyzers, BM25 citation retrieval, the
offline CLI, contradiction retrieval + ACH with the default lexical
entailment checker) runs on the standard library alone, no extras required.
`investigate` also accepts a path to any incident JSON file, not just a
catalog name — see [Real incidents](#real-incidents-ripe-ris--routeviews)
below for producing your own from raw MRT archives.

Optional extras, each independent:

```bash
pip install -e ".[ingest]"   # mrtparse, for pulling real incidents from RIPE RIS/RouteViews
pip install -e ".[llm]"      # litellm, for natural-language narration (INVESTIGATOR_MODEL=...)
pip install -e ".[nli]"      # sentence-transformers, for the real cross-encoder entailment checker
pip install -e ".[dev]"      # pytest
pip install -e ".[all]"      # everything above
```

```bash
pytest -q
```

Don't want to install anything? Everything above also runs with no install
at all: `PYTHONPATH=. python -m investigator.cli investigate ...` /
`PYTHONPATH=. python -m investigator.ingest ...` / `PYTHONPATH=. python -m
pytest -q`, same as `investigate`/`ask` and the rest, just spelled out in
full each time.

## Real incidents (RIPE RIS / RouteViews)

`data/incidents/incident_moas_withdrawal.json` is synthetic (TEST-NET-3, private
ASNs) — a worked example, not evidence. Everything above ran against real
data: `investigator/ingest.py` (needs the `ingest` extra) pulls raw MRT
update streams directly from the public RIPE RIS and RouteViews archives for
a prefix + time window, filters to that prefix, and normalizes the result
into the same incident JSON shape (pure Python — `mrtparse` only, no
PyBGPStream/native toolchain, so it installs the same way on any platform):

```bash
pip install -e ".[ingest]"

# fetch a named historical incident from data/incidents/catalog.json:
python -m investigator.ingest catalog pakistan-youtube-2008
python -m investigator.ingest catalog cloudflare-verizon-2019

# or fetch an arbitrary prefix/window directly:
python -m investigator.ingest fetch \
  --prefix 104.16.0.0/12 --start 2019-06-24T10:00:00Z --end 2019-06-24T13:00:00Z \
  --name cloudflare_verizon_2019 --collectors rrc00,route-views2

# then investigate it exactly like the sample above, by catalog name:
investigate pakistan-youtube-2008
```

`investigator/evaluate.py` runs every analyzer (and, with `--ach`, the full
contradiction-retrieval + ACH pipeline) over the whole catalog and reports
expected-vs-detected, so both detection accuracy and the false-assertion
rate are measured against documented outcomes rather than eyeballed on one
example:

```bash
python -m investigator.evaluate
python -m investigator.evaluate --ach
```

The catalog's incident windows are deliberately wide and flagged for
verification (see `data/incidents/catalog.json`) — treat them as a starting
point, not authoritative ground truth, until cross-checked against a primary
source.

Set `INVESTIGATOR_MODEL` (+ a provider key, see `.env.example`, needs the
`llm` extra) to turn on natural-language narration that cites the same
numbered sources — verified end-to-end against both a hosted model
(`claude-haiku-4-5`) and a local one (`ollama/llama3.1:8b`, no key, no
network egress); see [Real LLM narration](#real-llm-narration-hosted--local).
Without it, the tool runs in no-LLM mode and shows the grounded findings and
sources verbatim.

## What it does — and deliberately does not — do (yet)

**Does:** deterministic BGP anomaly detection (MOAS/hijack, withdrawal storm,
AS_PATH loop, route leak), an agentic search loop over RFCs (the LLM may run
multiple `search_rfcs` queries before answering, `investigator/agent.py`)
with numbered `[n]` citations, abstention when no source is relevant, a
pluggable LLM backend, config-driven analyzer toolsets
(`investigator/toolsets.toml`), a CLI with `pip install -e .` console
scripts.

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
section for the full before/after.

On top of that, competing-hypothesis (ACH) reasoning
(`investigator/ach.py`, folded into `--seek-contradictions`): ranks fired
analyzer findings by Heuer's ACH method (fewest refuted first, not most
confirmed) and abstains rather than asserting when no hypothesis clears a
real evidence bar. **Measured against the real 13-incident catalog
(`investigator/evaluate.py --ach`), not left as an untested claim, three
times:** first, a real ranking-rule bug was found and fixed (a hypothesis
with zero evidence was beating one with genuine mixed evidence) — after
which the system correctly abstained on all 13 real incidents rather than
asserting anything, a legitimate but weak result: RFC citations are hedged/
definitional grounding, not case-specific logical proof, and a strict
entailment bar mostly can't clear that distinction against a 2-file corpus.
Second, a **two-tier evidence bar** was added on top: ACH's assert/abstain
gate now compares contradicting evidence against a *relevance* tier
(on-topic, checker-verified, even if short of strict entailment) instead of
the strict tier alone, while still reporting the strict count alongside
every verdict as the conservative cross-check — two labeled bars, not one
loosened until it passes. Re-measured against the 2-file corpus: **3
correct assertions, 0 false assertions, 10 honest abstentions**. Third,
after expanding to the full 16-RFC corpus (below): **3 correct assertions,
1 false assertion, 9 honest abstentions** — a real, diagnosed regression
(not silently absorbed into the earlier number), traced to a pre-existing
detection-layer gap the bigger corpus exposed rather than caused. See
`docs/design.md`'s Phase 5 section and
[docs/corpus-expansion-results.md](docs/corpus-expansion-results.md) for
the full diagnosis at each stage.

**Also does (as of the corpus expansion):** a bigger, topically-focused RFC
corpus — 16 full RFCs (4271, 4272, 7908, 9234, 8212, 7454, 6811, 6480, 8205,
8206, 8207, 4760, 1997, 4456, 5065, 2439) instead of 2 hand-picked excerpts,
945 chunks instead of a handful. This surfaced two real bugs only visible
against real RFC text (a section-header regex that mislabeled Table-of-
Contents entries, and a preamble-skip that ate an entire RFC's body when it
used pre-2000-style unnumbered headings — see `investigator/retrieval/corpus.py`)
and required recalibrating the relevance floor to be scale-invariant rather
than an absolute BM25 score (`CitationEngine.min_score_fraction`). The
result was **not** an unconditional improvement — see
[docs/corpus-expansion-results.md](docs/corpus-expansion-results.md) for the
false-assertion regression and the LLM-narration degradation this exposed,
reported honestly rather than adjusted after the fact.

**Does not (Phase 6, effort-gated):** hybrid BM25+dense retrieval (the
retrieval-precision gap the corpus expansion made *more* visible, not
less — see the corpus-expansion results doc), a claims→sources provenance
graph, live BGP feed integration. See [`docs/design.md`](docs/design.md).

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
pyproject.toml              # pip install -e .; console scripts: investigate, ask
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
  ach.py                     # ACH ranking + two-tier evidence bar + measured abstention (Phase 5)
  ingest.py                 # RIPE RIS / RouteViews raw MRT -> Incident JSON
  evaluate.py                # expected-vs-detected accuracy over the catalog; --ach for the false-assertion rate
  evaluation/                # citation-CORRECTNESS harness (claims.py, entailment.py, scorer.py)
data/
  incidents/               # sample incident JSON (synthetic) + real, ingested ones
    catalog.json            # documented historical incidents (ground truth, verify before trusting)
  rfcs/                     # 16 full IETF RFCs (rfc-editor.org), cleaned + chunked at load time
tests/                     # analyzer + toolset + retrieval/abstention/contradiction + ach + agent + ingest/evaluate/evaluation/cli tests
docs/design.md
docs/alignment-plan.md      # delta vs. the original build plan, ordered by value
docs/corpus-expansion-results.md  # before/after of the RFC corpus expansion, honestly reported
```

## Roadmap

The original build plan's Phases 0-5 are all done as of this line — see
`docs/design.md` for what "done" meant for each, including the honestly
measured limitations.

- **Phase 1 ✅** baseline parity: analyzers, cited retrieval, agentic search loop (this repo)
- **Phase 1.5 ✅** real-incident ingestion (RIPE RIS/RouteViews) + detection-accuracy eval harness
- **Phase 2 ✅** config-driven toolset abstraction (TOML) + a real route-leak analyzer + LLM context-budget truncation
- **Phase 3 ✅** citation-correctness eval harness (ALCE-style precision/recall + RAGChecker-style retriever-vs-generator split), pluggable lexical/cross-encoder entailment checking
- **Phase 4 ✅** adversarial contradiction retrieval (`--seek-contradictions`), reusing Phase 1 retrieval + Phase 3 entailment checking; a real, verified false-positive limitation is documented, not hidden
- **Phase 5 ✅** competing-hypothesis (ACH) reasoning + measured abstention (`investigator/ach.py`, `--ach`); a real ranking-rule bug was found and fixed against real data, and a follow-up two-tier evidence bar turned the resulting 100% real-catalog abstention rate into 3 correct assertions with 0 false assertions (2-file corpus) — re-measured at 3 correct, 1 false, 9 abstained after the corpus expansion below, diagnosed rather than hidden
- **RFC corpus expansion ✅** 2 hand-picked excerpts → 16 full RFCs (945 chunks); fixed two real bugs only visible against full RFC text and a corpus-size-dependent relevance floor; the result was a genuine mix of better (more abstentions now have real evidence weighed) and worse (a new false ACH assertion, degraded local-model grounding) — see [docs/corpus-expansion-results.md](docs/corpus-expansion-results.md)
- **Phase 6 (effort-gated, not started):** hybrid BM25+dense retrieval, a claims→sources provenance graph, live BGP feed integration
