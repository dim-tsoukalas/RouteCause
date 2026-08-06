# Alignment plan: closing the gap to the original build plan

Status as of 2026-08-06. Phases 0–5 are implemented; Phase 6 is deliberately
not started. This document is the delta between what the original build plan
specified and what this repo actually does, ordered by value — plus the
deviations that should be *defended* rather than closed, and two places where
the **original plan is wrong** and should be deviated from deliberately.

---

## The framing

"As close as possible to the original plan" is the wrong goal if taken
literally. The plan itself says its effort figures are "planning figures, not
commitments," permits the DeBERTa fallback, and names a defensible minimum
scope of Phases 0–4. It also — by its own admission — was written without web
access, and verification has now shown at least two of its technical
recommendations to be the wrong call for this project.

Four buckets:

- **Correctness gaps** — a claim the README already makes is not supported by
  what the code does. Fix first.
- **Missing scope** — real plan items not built.
- **Defend** — deviations that are fine or better. Prepare the one-liner.
- **Deviate deliberately** — the plan's own recommendation is wrong here.

---

## Gap table

| Plan item | Status | Bucket |
|---|---|---|
| Phase 0: LiteLLM routes to API model *and* local Ollama | ✅ Done — `claude-haiku-4-5` (hosted) + `ollama/llama3.1:8b` (local), README updated | Correctness |
| Phase 3: citation precision/recall over generated claims | Only run on NoOp output + fixtures | Correctness |
| Phase 3: ALCE-style recall | Definition doesn't match ALCE | Correctness |
| Phase 3/4: one checker doing two different jobs | Conflated; explains a documented bug | Correctness |
| Phase 1: full RFC corpus | 2 hand-picked excerpts | Correctness |
| Plan caveats: re-verify upstream facts | Partly done below | Correctness |
| Phase 1: hybrid BM25 + dense retrieval | BM25 only | Missing scope |
| Phase 2: second data source proves the abstraction | Claimed, never demonstrated | Missing scope |
| Phase 3: **Bespoke-MiniCheck-7B primary** | Not used | **Deviate — plan is wrong** |
| Phase 4: NLI-filter contradictions with the same stack | Same checker as Phase 3 | **Deviate — plan is wrong** |
| Phase 3: ALCE + RAGChecker as libraries | Metrics reimplemented | Defend |
| Phase 1: LlamaIndex + Chroma/Qdrant | Hand-rolled BM25 + citation engine | Defend |
| Phase 2: YAML toolsets | TOML toolsets | Defend |
| Data: PyBGPStream | mrtparse + stdlib, real MRT archives | Defend (better) |
| Phase 6 | Not started | Correctly deferred |

---

## Where the original plan is wrong

### A. Bespoke-MiniCheck-7B is the wrong checker for this project

The plan names it primary with "DeBERTa-MNLI or T5-TRUE as lighter fallbacks."
Verification against the live model card changes this:

- **It is licensed CC BY-NC 4.0** — non-commercial. Making a non-commercial
  model the default checker in an open-source portfolio tool is a licensing
  problem, and "commercial licensing, contact company@bespokelabs.ai" is not
  something you want in the dependency path of a repo you're showing off.
- It is 8B params, needs a GPU or vLLM for usable throughput, and the plan
  already flagged this as a risk.

**`lytang/MiniCheck-Flan-T5-Large` dominates it for this use case:** MIT
licensed, 0.8B, explicitly "the best fact-checking model with size < 1B,"
reported at GPT-4 parity and ~400× cheaper, CPU-feasible. Same authors, same
paper, same `minicheck` package (`model_name='flan-t5-large'`).

It is also a real upgrade over what you run today. `cross-encoder/nli-deberta-v3-base`
is a **general NLI** model; MiniCheck is **purpose-trained on claim-vs-document
grounding**, which is exactly your Phase 3 task.

### B. Phase 3 and Phase 4 need two different checkers

This is the more important finding, and it explains a bug you already
documented.

MiniCheck outputs a **binary** label: `MiniCheck-Model(document, claim) -> {0, 1}`,
supported or not supported. It has no way to express *contradiction*. Your
Phase 4 adversarial retrieval needs exactly that — passages that genuinely
**CONTRADICT** a hypothesis, not passages that merely fail to support it.

Your current design uses one `EntailmentChecker` for both jobs, and the
failure you documented in the README is the predictable symptom: RFC 4271's
AS_PATH loop-detection section flagged as `CONTRADICTS`-ing an unrelated MOAS
claim, "apparently because both texts happen to contain the word 'not.'" That
is the classic MNLI annotation artifact — models trained on MNLI learn
negation as a contradiction cue and systematically collapse *neutral* into
*contradiction* for topically unrelated pairs. An unrelated passage should be
NEUTRAL. Your pipeline has no neutral.

**The fix is architectural, not a bigger model:**

- **Phase 3 (does the cited source support this claim?)** →
  `lytang/MiniCheck-Flan-T5-Large`. Binary is the right shape here.
- **Phase 4 (does this passage refute this hypothesis?)** → a genuine 3-way
  NLI model that can say *neutral*:
  `MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli` (435M, MIT,
  trained on MNLI + FEVER-NLI + **ANLI** + LingNLI + WANLI). ANLI is
  adversarially collected specifically to break the lexical-overlap and
  negation shortcuts that produced your false positive.

Then require `CONTRADICTION` to beat *both* `ENTAILMENT` and `NEUTRAL` by a
margin before a passage counts as counter-evidence.

This is a better story than "I used the model the plan named." You found a
failure mode, diagnosed it as a task/model mismatch rather than a capacity
problem, and fixed it by splitting one interface into two — after your own
scaling experiment (xsmall → base) showed capacity only *reduced* it. Your
`EntailmentChecker` Protocol already makes both swaps cheap.

---

## P0 — Correctness

### 1. Actually run the LLM path — ✅ done

Phase 0's done-criterion was "a hello world completion routes through LiteLLM
to both an API model and local Ollama." `litellm` is now an installed,
verified dependency (`llm` extra in `pyproject.toml`, already correctly
placed there before this pass) and the flagship README demo has been
re-generated against real model output.

Ran: `claude-haiku-4-5` (hosted, via `ANTHROPIC_API_KEY`) and
`ollama/llama3.1:8b` (local, no key, no network egress), both against the
same incident (`pakistan-youtube-2008`) and the same evidence-referencing
question, with `--seek-contradictions --score-citations`. Both are captured
in the README's [Real LLM narration](../README.md#real-llm-narration-hosted--local)
section.

This mattered far beyond Phase 0 because of what it does to Phase 3:
`score_citations` measures whether *generated claims* are entailed by the
sources they cite. Under `NoOpBackend` the "answer" is the echoed prompt, so
the harness had only ever seen synthetic fixtures
(`tests/evaluation/test_scorer.py`) and text that trivially matches its own
sources. Pointed at real output for the first time:

- **`claude-haiku-4-5`**: 100% citation precision, 60% recall — 5 claims, 2
  with no corpus support anywhere (retriever errors), 0 miscited.
- **`ollama/llama3.1:8b`**: 33%/33% — 3 claims, 1 retriever error *and* 1
  generator error (a claim the corpus could have supported but that didn't
  get cited).

Neither backend was fully grounded once it committed to a claim — confirming
the plan's prediction that real numbers would be worse than the synthetic
baseline, and demonstrating the differentiator actually works: this failure
mode was invisible under `NoOpBackend` and is now caught. One caveat worth
recording: the agent's prompt (`investigator/agent.py`) only carries
retrieved RFC text and the question, not the analyzer's specific findings —
a generic question ("why did connectivity change?") caused *both* models to
correctly abstain outright, and a sharper, evidence-referencing question was
needed before either would commit to a claim at all. That's arguably
correct behavior (no fabrication without grounding) but is worth a follow-up
note if it surprises users running their own questions.

**Done when:** the README shows a real narrated investigation and a
citation-correctness scorecard computed over model-generated prose, from both
a hosted and a local backend. ✅

### 2. Fix the ALCE recall definition

`scorer.py:138` computes recall as `entailed_by_any_cited` — i.e. at least one
cited source, *on its own*, entails the claim.

ALCE defines it differently: a statement's citation recall is 1 iff it has at
least one citation **and the concatenation of all cited passages** fully
supports it. The difference bites exactly where RFC grounding lives — a claim
supported jointly by RFC 7908 §4 and RFC 4271 §9.1.2, with neither sufficient
alone, scores 0 under your rule and 1 under ALCE's.

Precision has a similar gap: ALCE gates a citation's precision on the
statement's recall being 1, and counts a citation as precise if it fully *or
partially* supports the statement; your version is a flat
`entailed_citations / total_citations`.

Either match the definitions or rename the metric and state the difference
explicitly in `docs/design.md`. Both are defensible; silently calling a
different metric "ALCE-style" is not. Note that concatenated-source scoring
is also what MiniCheck is built for — it takes a whole document, not a single
span.

### 3. Split the checkers (see section B above)

**Done when:** `investigator/evaluation/entailment.py` exposes a
support-checker and a separate 3-way contradiction-checker, the README's
AS_PATH false positive is re-tested against the new stack, and the result —
fixed or not — is reported.

### 4. Expand the RFC corpus

Target the topically dense BGP/routing-security subset, ~15–20 full RFCs:
4271, 4272, 7908, 9234, 8212, 7454 (BCP 194), 6811, 6480, 8205, 8206, 8207,
4760, 1997, 4456, 5065, 2439. Per-RFC text at
`https://www.rfc-editor.org/rfc/rfc<N>.txt`.

*(Correction to an earlier draft of this plan: I claimed the full IETF dump
would "dilute IDF." That is backwards — adding unrelated documents raises N
while `df` for BGP terms stays flat, so IDF for your discriminative terms goes
**up**. The real arguments for a curated subset are (a) precision@k, since
top-4 over ~500k chunks gives far more chances for a lexically-similar but
topically-irrelevant chunk to win, and (b) **evaluation attribution** — with a
focused corpus, an abstention means the RFC series genuinely doesn't address
the claim, rather than retrieval losing it in the noise. That distinction is
precisely what your RAGChecker-style retriever-vs-generator split measures, so
a focused corpus makes your headline metric interpretable.)*

Three things break on real RFC text:

- **Page furniture.** Form feeds, running headers, `[Page 42]` footers get
  appended as prose. Needs a cleaner that also strips Status of This Memo,
  Copyright, the table of contents, References, and Authors' Addresses. The
  TOC especially — dense with section titles, it will outrank real body text
  on exactly the queries that matter.
- **`_SECTION_RE` over-matches.** Any line starting with digits-and-dots,
  including TOC entries and numbered list items, becomes a section label. A
  mislabeled citation is worse than no citation given what you claim to
  measure.
- **`min_score = 1.0` is corpus-size dependent.** An absolute BM25 score
  calibrated against a two-document index. Since IDF for your query terms
  *rises* with N, this floor gets progressively easier to clear as the corpus
  grows — your abstention rate will drift down for reasons that have nothing
  to do with evidence quality. Make it relative (fraction of top-hit score, or
  a percentile of the score distribution) and document why.

**Capture baseline harness numbers before expanding.** The before/after delta
is the artifact; it cannot be reconstructed afterwards.

Expect ACH results to move. The two-tier evidence bar exists because hedged
RFC text couldn't strictly entail incident-specific claims; more corpus may or
may not change that, and either outcome is worth writing up.

### 5. Verification pass on the plan's own caveats

The plan closes by noting web tools were unavailable and that every
architectural detail "MUST be re-verified." `docs/design.md` now carries a
lineage table asserting correspondence to K8sGPT's `IAI`, HolmesGPT's toolset
model, and LlamaIndex's `CitationQueryEngine` — precisely the claims a
technical reader checks first.

Already verified while writing this plan:

- ✅ `bespokelabs/Bespoke-MiniCheck-7B` exists at that path — **but is CC BY-NC 4.0**.
- ✅ arXiv 2404.10774 (MiniCheck, EMNLP 2024) resolves.
- ✅ ALCE metric definitions — and your implementation differs (item 2).
- ✅ RFC 9234 and RFC 7454/BCP 194 are correctly identified. Note RFC 7454 is
  in the process of being updated (`bgpopsecupd`) — worth a footnote.
- ✅ `MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli` exists, MIT.

Still to verify: K8sGPT `IAnalyzer` / `IAI` signatures and `Result`/`Failure`
field names; K8sGPT's current CNCF tier; HolmesGPT's built-in toolset list and
truncation internals; LlamaIndex `citation_chunk_size` / `citation_chunk_overlap`
defaults; the remaining six arXiv IDs.

### 6. Housekeeping

- `.gitattributes` with `*.json text eol=lf`, then re-checkout. 24 incident
  files show as modified with ~179k insertions and ~179k deletions — a pure
  line-ending flip that will pollute the next commit.
- `requirements.txt` ships with every real dependency commented out, so
  `pip install -r requirements.txt` does not give the documented capability.
  Move to extras (`llm`, `nli`, `retrieval`).

---

## P1 — Missing scope

### 7. Hybrid BM25 + dense retrieval

Plan Phase 1 specified hybrid; the repo is BM25-only. Do this **after** the
corpus expansion so the justification is measured. RFC prose is full of
near-synonyms a lexical matcher can't bridge ("withdrawal storm" vs. "route
flap", "origin change" vs. "unauthorized announcement"), so recall degradation
at 20 RFCs is likely — but demonstrate it.

`sentence-transformers` is already a soft dependency, so BGE or E5 adds no new
toolchain. Keep it behind the same config switch pattern as
`[citation_eval].checker` so the dependency-free path survives.

### 8. Prove the toolset abstraction with a second data source

Phase 2's done-criterion was "a new data source can be added without touching
the core loop." The abstraction exists; the proof doesn't. The diff itself is
the evidence — if it touches only a new module plus one `[[toolset]]` block,
the claim is proven.

Batfish needs Docker. An **RPKI/ROA validation toolset** over the existing
incidents is cheaper, needs no new runtime, and is more domain-relevant: it
turns "AS36561 announced this prefix" into "AS36561 announced this prefix and
no ROA authorizes it," which is the strongest evidence a hijack analyzer can
produce. It also gives Phase 5's ACH a genuinely independent evidence axis
rather than more RFC prose.

---

## Defend, don't fix

- **Hand-rolled BM25 instead of LlamaIndex + Chroma.** The core runs on the
  standard library with no install; the `CitationEngine` mirrors
  `CitationQueryEngine` semantics so the swap is contained. Adding dense
  retrieval (#7) is the honest response, not adopting the framework.
- **Metrics reimplemented instead of importing ALCE/RAGChecker.** ALCE is a
  benchmark harness over ASQA/QAMPARI/ELI5, not a library that drops onto a
  BGP corpus; the definitions are what transfer — so get them right (#2).
- **TOML instead of YAML toolsets.** Same config-driven model, and `tomllib`
  is stdlib in 3.11+, preserving zero-install. Cosmetic.
- **mrtparse instead of PyBGPStream.** Exceeds the plan. PyBGPStream wraps a C
  library with no Windows wheels; the plan's own risk note said to start from
  curated incidents and defer live feeds — you ingested 13 real incidents from
  raw RIS/RouteViews MRT archives anyway. Lead with this.
- **Four analyzers, the ACH ranking-bug fix, the two-tier evidence bar.**
  Beyond plan scope. `test_zero_evidence_does_not_beat_genuine_mixed_evidence`
  is the best story in the repo — the eval harness caught something
  hand-written tests missed, which is the entire thesis.

---

## Sequencing

| # | Item | Est. | Notes |
|---|---|---|---|
| 1 | Run the LLM path, regenerate README demo + scorecard | ✅ done | Unblocks honest Phase 3 numbers |
| 6 | Housekeeping (line endings, extras) | 1 hour | — |
| 2 | ALCE definition fix | 0.5 day | Do before re-measuring |
| 4a | Baseline harness numbers **before** corpus change | 1 hour | Blocks 4b |
| 4b | Corpus expansion + cleaner + scale-invariant floor | 2–3 days | Blocks 7 |
| 3 | Split support vs. contradiction checkers | 1–2 days | Highest-signal single change |
| 5 | Finish verification pass | 1 hour | — |
| 7 | Hybrid dense retrieval, if measurement justifies | 2–3 days | — |
| 8 | RPKI/ROA toolset | 1–2 days | — |

Items 1–6 decide whether existing claims hold. Stop there and the project is
honest and defensible. Items 7–8 are scope.

Phase 6 stays out until the numbers are stable, per the plan's own gate.

---

## Sources

- [bespokelabs/Bespoke-MiniCheck-7B](https://huggingface.co/bespokelabs/Bespoke-MiniCheck-7B) — CC BY-NC 4.0, 8B
- [lytang/MiniCheck-Flan-T5-Large](https://huggingface.co/lytang/MiniCheck-Flan-T5-Large) — MIT, 0.8B
- [MiniCheck (EMNLP 2024), arXiv:2404.10774](https://arxiv.org/pdf/2404.10774.pdf) · [GitHub](https://github.com/Liyan06/MiniCheck)
- [LLM-AggreFact leaderboard](https://llm-aggrefact.github.io/blog)
- [MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli](https://huggingface.co/MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli) — MIT, 3-way NLI
- [ALCE: Enabling LLMs to Generate Text with Citations (EMNLP 2023)](https://aclanthology.org/2023.emnlp-main.398.pdf)
- [RFC 9234](https://www.rfc-editor.org/rfc/rfc9234.html) · [RFC 7454 / BCP 194 update status](https://ayuda.la/en/blog/bgpopsecupd-en/)
