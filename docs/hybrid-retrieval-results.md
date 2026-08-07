# Hybrid (BM25 + dense) retrieval results (item 7)

Captured 2026-08-07. Compares BM25-only (the shipped default) against
hybrid retrieval (`[rfc_search].retrieval = "hybrid"` in `toolsets.toml`)
on the same 16-RFC corpus from item 4b.

## Motivating failure, measured before building anything

RFC prose is full of near-synonyms an analyzer's own hypothesis wording
doesn't share. Tested the *real* hypothesis templates
(`investigator/analyzers/*.py`), not paraphrased approximations, against
the real corpus with BM25:

- **`WithdrawalStorm`**: `"Total 403 withdrawals; peak burst 63 in
  window."` — top BM25 hits are RFC 2439's numeric configuration tables and
  RFC 4272's TCP-RST section, both irrelevant. BM25 is matching the bare
  digits `403`/`63` as if they were meaningful terms, not the actual
  concept ("route flap damping" — RFC 2439's real subject, never surfaced
  meaningfully).
- **`RouteLeak`**: `"...transit AS(es) appeared mid-window across peers,
  origin unchanged"` — **zero BM25 hits.** Abstains outright, despite RFC
  7908 having an entire route-leak type taxonomy. The analyzer's phrasing
  just doesn't share vocabulary with the RFC's.

Dense retrieval (`BAAI/bge-small-en-v1.5`, with BGE's documented query
instruction prefix — verified directly that skipping the prefix is a real,
silent quality regression, not a micro-optimization) on the same two
queries surfaces RFC 2439 (Route Flap Damping — the actually-relevant RFC)
and RFC 7908's route-leak type definitions in the top few results — neither
meaningfully found by BM25 alone. This justified building hybrid retrieval;
see `investigator/retrieval/citations.py`'s `DenseIndex` docstring for the
full comparison.

## Design

- `DenseIndex`: embeds all chunks once at load time, cosine similarity per
  query. `sentence-transformers` is already an optional dependency
  (`CrossEncoderNLIChecker`), so no new toolchain.
- `_reciprocal_rank_fusion`: combines BM25's and dense's ranked candidate
  lists by **rank position**, not raw score — BM25 scores and cosine
  similarities live on incomparable scales, so summing them directly would
  let whichever number happens to run larger dominate. RRF (Cormack et al.,
  2009), `k=60` (the standard constant, unchanged, not tuned).
- Abstention: BM25 naturally returns nothing when zero terms overlap;
  dense embeddings do not have that property (cosine similarity always
  returns *something*), so hybrid mode needed its own floor
  (`min_dense_score`) or it would **never abstain**, undermining the whole
  project's abstain-rather-than-guess thesis. Verified this was a real risk
  before shipping a fix, not a hypothetical: without a floor, a "how do I
  bake sourdough bread" query returned 4 sources.
- Additive, opt-in, same pattern as every other real upgrade in this
  project: `bm25` stays the shipped default; `hybrid` requires the `nli`
  extra and an explicit `[rfc_search].retrieval = "hybrid"`.

## Calibrating `min_dense_score` — same separation problem as `min_score_fraction`, found again

Measured real analyzer hypothesis templates against genuinely off-topic
queries:

| Query | Similarity |
|---|---|
| MOAS (real) | 0.740 |
| ASPathLoop (real) | 0.710 |
| RouteLeak (real) | 0.659 |
| WithdrawalStorm (real) | 0.631 |
| "kubernetes ingress controller" (off-topic) | **0.642** |
| "weather forecast" (off-topic) | 0.563 |
| "sourdough bread" (off-topic) | 0.547 |
| "chocolate chip cookies" (off-topic) | 0.480 |
| "1980s sci-fi movie" (off-topic) | 0.469 |

**Not a clean separation.** The same "kubernetes ingress controller" query
that broke `min_score_fraction`'s calibration (item 4b — it scored *above*
the real MOAS query there too) breaks this one too, scoring *above*
`WithdrawalStorm`'s genuine on-topic score. This is a repeat finding, not a
new one: technical-register vocabulary overlap ("configure," "controller,"
routing-adjacent phrasing) reads as similar to BGP RFC prose under both a
lexical-ceiling-ratio and a dense-cosine-similarity floor, for the same
underlying reason — neither method distinguishes topic from register.
**Dense retrieval does not fix this failure mode; it reproduces it.**
`DEFAULT_MIN_DENSE_SCORE = 0.6` sits in the gap that does separate cleanly
(all four real on-topic queries above it, four of five off-topic queries
below it), with the kubernetes case reported as a known miss rather than
tuned around.

## Real-catalog measurement: fixes the item-4b false assertion

```bash
CITATION_CONTRADICTION_CHECKER=lexical  # default, unchanged
# [rfc_search].retrieval = "hybrid" in toolsets.toml
python -m investigator.evaluate --ach --toolsets <hybrid-config>
```

| | BM25-only (16-RFC corpus, default) | Hybrid (16-RFC corpus) |
|---|---|---|
| Correct assertions | 3 | 3 |
| False assertions | **1** | **0** |
| Abstained | 9 | 10 |

**Fixes `cloudflare-verizon-2019`'s false assertion** (item 4b's finding),
reverting to a correct abstention — matching the original 2-file-corpus
numbers (3/0/10), but now on the full 16-RFC corpus. No new correct
assertions unlocked; this is a defensive fix (fewer wrong answers), not an
expansion of coverage.

**Diagnosed, not just measured — and it connects to a separate finding.**
Inspected the actual evidence: under BM25-only, `ASPathLoop`'s "strict
entailment" support for this incident came from RFC 6811 §2 (literally
pseudo-code) and RFC 7908 §2 — the *same* spurious "supporting" evidence
the checker-split investigation (item 3) independently found and flagged
as arguably not real entailment at all (a genuine 3-way NLI model refused
to call it `ENTAILED` either). Under hybrid retrieval, RRF fusion changes
which candidates rank in the final top-k for this query; those specific
chunks get displaced, `ASPathLoop`'s `supporting_count` reverts to 0, and
`rank_hypotheses()`'s existing "abstain if nothing has genuine support"
gate correctly fires. **Two independent fixes — a better contradiction
checker (item 3) and better retrieval (item 7) — converge on the same
root cause**: BM25 surfacing lexically-similar-but-not-actually-entailing
passages (pseudo-code, generic filter prose) and the system trusting them
as "strict entailment" evidence. Neither was aimed at the other's target;
both hit it anyway, which is reasonably strong evidence the diagnosis is
right rather than a coincidence.

## What this means for defaults

Not flipped to the shipped default. Reasons:

1. Adds a real dependency (`sentence-transformers`, already optional for
   `nli`, but not part of the zero-install core path).
2. The `min_dense_score` separation gap (kubernetes-style false positives)
   is real and unresolved — same caveat as `min_score_fraction`.
3. One incident's worth of real-catalog signal (13 incidents, one flipped)
   is a real result but a small one; more corpus/incident coverage would
   make this more confident, not less true.

Stays opt-in via `[rfc_search].retrieval = "hybrid"`, consistent with
every other "real but not default" upgrade in this project
(`cross_encoder`, `minicheck`, `nli_margin`).
