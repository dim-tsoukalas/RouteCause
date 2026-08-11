# Engineering findings & measured results

The detail behind the summary in the [README](../README.md). Every item here
was found by measuring against real data, not asserted in a design doc.

## What I measured

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
  diagnosed in [corpus-expansion-results.md](corpus-expansion-results.md) —
  the false assertion traces to a pre-existing detection-layer gap the bigger
  corpus exposed rather than caused.

- **A checker fix that provably fixes the bug it targeted also provably
  breaks the system it's plugged into — both measured, not just the
  flattering half.** Split the single entailment checker Phase 3 and
  Phase 4 shared into two purpose-built ones: `MiniCheckSupportChecker`
  (binary, citation correctness) and `MarginNLIContradictionChecker`
  (genuine 3-way NLI, adversarial retrieval). Isolated re-test of the
  documented RFC 4271-vs-MOAS false positive: **fixed** — 99.5% neutral,
  0.4% contradiction, where the old checker confidently said `CONTRADICTS`.
  Re-tested against the real 13-incident catalog, not stopped at the
  isolated win: false-assertion rate went from 3 correct/1 false/9 abstained
  (lexical checker) to **0 correct/1 false/12 abstained** — two previously-
  *correct* MOAS assertions now abstain outright. Root cause: the new
  model is far more conservative about strict `ENTAILED` than the lexical
  checker was (verified directly — the exact chunks the lexical checker
  called "strict entailment" for MOAS turn out to be pseudo-code and
  generic filter prose that a real NLI model correctly refuses to call
  entailment), which collapses `investigator/ach.py`'s `supporting_count`
  to zero almost everywhere and re-triggers the original 100%-abstention
  problem the two-tier evidence bar was built to fix. Not adopted as the
  default; stays available, opt-in only. Full diagnosis in
  `design.md`'s "Phase 3/4 checker split" section and
  `investigator/retrieval/contradiction.py`'s module docstring.

- **Two unrelated fixes converged on the same root cause from different
  directions.** Hybrid (BM25 + dense) retrieval was built for a different
  reason entirely — BM25 returning *zero* hits for `RouteLeak`'s real
  hypothesis statement despite RFC 7908 having a full route-leak taxonomy —
  but measured against the real catalog, it also fixed the corpus
  expansion's false assertion (3 correct/**0** false/10 abstained, was
  3/1/9). Diagnosed, not coincidental: RRF fusion displaces the exact same
  spurious "strict entailment" evidence (RFC 6811 §2 — literally
  pseudo-code) the checker-split investigation above *independently*
  flagged as questionable. Also not adopted as default: the same "kubernetes
  ingress controller" query that broke the corpus-expansion floor breaks the
  dense-retrieval floor too (0.642, above the real `WithdrawalStorm` query's
  0.631) — dense retrieval doesn't fix BM25's register-vs-topic confusion, it
  reproduces it. See [hybrid-retrieval-results.md](hybrid-retrieval-results.md).

- **A new, independent evidence axis genuinely improved detection accuracy
  — and exposed a real architectural gap in how it gets used.** Added an
  RPKI/ROA validation toolset (`investigator/analyzers/rpki.py`) — two new
  files plus one `[[toolset]]` config entry, proving the toolset
  abstraction with a second data source per Phase 2's own done-criterion.
  Real result: detection accuracy **4/13 → 5/13** —
  `amazon-route53-mew-2018` (the real MyEtherWallet DNS hijack) now
  correctly detected, genuinely new signal MOAS couldn't produce (MOAS
  needs both origins visible in-window; RPKI only needs the anomalous one
  to lack a valid ROA). But the ACH false-assertion rate didn't move,
  and *why* is itself the finding: `rank_hypotheses()` routes RPKI evidence
  through the same RFC-citation entailment gate as everything else, even
  though a ROA is self-certifying and shouldn't need RFC prose to
  corroborate it — a structural mismatch, not a capacity problem, flagged
  as real follow-up work rather than silently worked around. See
  [rpki-toolset-results.md](rpki-toolset-results.md).

## Full transcript: the 2008 Pakistan Telecom / YouTube hijack

Real MRT archive data (RIPE RIS + RouteViews, 2008-02-24 18:47–20:54 UTC) for
the incident where Pakistan Telecom (AS17557) originated YouTube's
`208.65.153.0/24` in response to a government block order, and the
more-specific route leaked globally via PCCW (AS9491), hijacking YouTube
traffic worldwide. No synthetic data, no cherry-picked prompt:

```bash
INVESTIGATOR_MODEL=ollama/llama3.1:8b investigate pakistan-youtube-2008 \
  --question "Using the reference corpus, explain why a prefix (208.65.153.0/24) being announced by two distinct origin ASNs (AS17557 and AS36561) is treated as a strong indicator of a hijack or misconfiguration, and what validation step is recommended." \
  --seek-contradictions --score-citations
```

against the full 16-RFC corpus, trimmed only for length (evidence lists
collapsed with `…`):

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
layers are exactly right (MOAS, correctly, same verdict as the 2-RFC corpus)
but the local model's narration is **not** — it reads fluently and cites four
real RFC sections, and every single one of those citations is wrong (`0%`
recall). This is precisely the failure `--score-citations` exists to catch,
and it's materially worse than this same command produced against the smaller
2-RFC corpus (33%/33%) — a bigger, more topically diverse corpus gave the
model more plausible-sounding material without its grounding discipline
improving to match.

Measured, not cherry-picked: `investigator/evaluate.py --ach` runs the
detection + retrieval pipeline over all 13 real catalog incidents and reports
**3 correct assertions, 1 false assertion, 9 honest abstentions** against the
expanded corpus (was 3/0/10 against the 2-RFC corpus) — see
[corpus-expansion-results.md](corpus-expansion-results.md) for the diagnosed
false assertion.

## Real LLM narration (hosted + local)

The transcript above is the local model; the same question, same incident,
same corpus, run against a **hosted** backend (`claude-haiku-4-5` via LiteLLM)
behaves completely differently: it **abstains outright**, where against the
smaller 2-RFC corpus it answered confidently (100%/60% precision/recall).
Provider variance is itself part of what's being measured:

| | 2-RFC: `claude-haiku-4-5` | 2-RFC: `llama3.1:8b` | 16-RFC: `claude-haiku-4-5` | 16-RFC: `llama3.1:8b` |
|---|---|---|---|---|
| Outcome | answered | answered | **abstained** | answered |
| Claims made | 5 | 3 | 0 | 4 |
| Citation precision | 100% | 33% | n/a | n/a (0 entailed) |
| Citation recall | 60% | 33% | n/a | **0%** |

Neither backend was fully grounded even against the small corpus. Against the
expanded corpus, the hosted model became *more* conservative and the local
model became *less* grounded while sounding more confident — two different,
both real, reactions to the same change in retrieval breadth. This was
invisible until real model output — not `NoOpBackend`'s echoed prompt, not a
hand-written fixture — was actually scored, twice, against two corpus sizes.
See [corpus-expansion-results.md](corpus-expansion-results.md).

## What it does — and deliberately does not — do

**Does:** deterministic BGP anomaly detection (MOAS/hijack, withdrawal storm,
AS_PATH loop, route leak, RPKI/ROA authorization), an agentic search loop over
RFCs (`investigator/agent.py`) with numbered `[n]` citations, abstention when
no source is relevant, a pluggable LLM backend, config-driven analyzer toolsets
(`investigator/toolsets.toml`), and a CLI with `pip install -e .` console
scripts.

**Also does:** real-incident ingestion from RIPE RIS / RouteViews
(`investigator/ingest.py`), a detection-accuracy evaluation harness
(`investigator/evaluate.py`), a citation-*correctness* harness
(`investigator/evaluation/`, `--score-citations`) — does the cited RFC clause
actually entail the claim, not just get mentioned — and adversarial
counter-evidence retrieval (`--seek-contradictions`): for each fired finding,
retrieve broadly and keep only passages an entailment checker verifies as
genuinely contradicting it. Pluggable entailment checking throughout: a
dependency-free lexical heuristic by default, or a real HuggingFace MNLI
cross-encoder as an opt-in upgrade — deliberately not LLM-as-judge, which would
undermine the point of an independent check.

On top of that, competing-hypothesis (ACH) reasoning (`investigator/ach.py`):
ranks fired findings by Heuer's method (fewest refuted first, not most
confirmed) and abstains rather than asserting when no hypothesis clears a real
evidence bar. Measured against the real 13-incident catalog three times (see
`design.md`'s Phase 5 section and
[corpus-expansion-results.md](corpus-expansion-results.md)): a ranking-rule bug
found and fixed; a two-tier evidence bar that turned a 100% abstention rate
into 3 correct / 0 false / 10 abstained (2-file corpus); re-measured at
3 correct / 1 false / 9 abstained after the corpus expansion, diagnosed rather
than hidden.

**Also does:** a 16-RFC corpus (945 chunks) instead of 2 hand-picked excerpts,
which surfaced two real parsing bugs and required a scale-invariant relevance
floor (`CitationEngine.min_score_fraction`); and opt-in hybrid retrieval
(BM25 + dense embeddings via reciprocal rank fusion) — motivated by a measured
BM25 failure and not shipped as default because it reproduces rather than fixes
BM25's register-vs-topic confusion on adjacent-domain queries.

**Does not (Phase 6, effort-gated):** a claims→sources provenance graph, live
BGP feed integration. See [`design.md`](design.md).

## Roadmap

Phases 0–5 are done — see [`design.md`](design.md) for what "done" meant for
each, including the honestly measured limitations.

- **Phase 1 ✅** baseline parity: analyzers, cited retrieval, agentic search loop
- **Phase 1.5 ✅** real-incident ingestion (RIPE RIS/RouteViews) + detection-accuracy eval harness
- **Phase 2 ✅** config-driven toolset abstraction (TOML) + a real route-leak analyzer + LLM context-budget truncation
- **Phase 3 ✅** citation-correctness eval harness (ALCE-style precision/recall + RAGChecker-style retriever-vs-generator split), pluggable entailment checking
- **Phase 4 ✅** adversarial contradiction retrieval (`--seek-contradictions`); a real, verified false-positive limitation documented, not hidden
- **Phase 5 ✅** competing-hypothesis (ACH) reasoning + measured abstention (`--ach`)
- **RFC corpus expansion ✅** 2 excerpts → 16 full RFCs — see [corpus-expansion-results.md](corpus-expansion-results.md)
- **Entailment checker split ✅** purpose-built checkers per phase; both the fix and the regression it caused reported, opt-in only
- **Hybrid (BM25 + dense) retrieval ✅** opt-in — see [hybrid-retrieval-results.md](hybrid-retrieval-results.md)
- **RPKI/ROA validation toolset ✅** second independent evidence axis (4/13 → 5/13) — see [rpki-toolset-results.md](rpki-toolset-results.md)
- **Phase 6 (not started):** claims→sources provenance graph, live BGP feed integration

## Layout

```
pyproject.toml              # pip install -e .; console scripts: investigate, ask, investigator-serve
investigator/
  types.py                   # Incident/BGPUpdate + Result/Finding (K8sGPT-style)
  toolsets.toml / toolsets.py # config-driven analyzer manifest (TOML, stdlib-only) + loader
  analyzers/                 # deterministic detectors + registry
    base.py  moas.py  withdrawal_storm.py  as_path_loop.py  route_leak.py  rpki.py
  retrieval/                 # BM25 + dense (hybrid, opt-in) + CitationEngine (numbered sources, abstain)
    corpus.py  citations.py  contradiction.py
  llm.py                     # LLMBackend: NoOp (offline) + LiteLLM (real) + InstrumentedBackend
  agent.py                   # bounded, context-budgeted agentic search loop (ReAct-style, RFC retrieval only)
  engine.py  report.py  cli.py
  api.py                     # FastAPI service over InvestigationEngine
  observability.py           # optional OpenTelemetry / stderr tracing
  ach.py                     # ACH ranking + two-tier evidence bar + measured abstention
  ingest.py                  # RIPE RIS / RouteViews raw MRT -> Incident JSON
  rpki.py                    # RIPEstat RPKI/ROA fetch + local cache -> RPKIAnalyzer
  evaluate.py                # expected-vs-detected accuracy; --ach for the false-assertion rate
  evaluation/                # citation-CORRECTNESS harness (claims.py, entailment.py, scorer.py)
data/
  incidents/                 # sample incident JSON + real, ingested ones; catalog.json
  rfcs/                      # 16 full IETF RFCs, cleaned + chunked at load time
deploy/                      # Render + Hugging Face Space configs
scripts/                     # docker-smoke.sh / .ps1
tests/                       # 123 tests across analyzers, retrieval, ach, agent, ingest, cli, api
```
