# Corpus expansion results (item 4b)

Captured 2026-08-06, immediately after replacing the 2 hand-picked RFC
excerpts with 16 full-text RFCs from rfc-editor.org. Compare against
[docs/corpus-baseline-2rfc.md](corpus-baseline-2rfc.md) — that document is
the "before" half of this delta.

Corpus: 4271, 4272, 7908, 9234, 8212, 7454, 6811, 6480, 8205, 8206, 8207,
4760, 1997, 4456, 5065, 2439 (the full alignment-plan item-4 target list).
826,736 raw bytes → 945 chunks after `load_corpus`'s cleaning + chunking
pass (`investigator/retrieval/corpus.py`).

Two prerequisite bugs, both only visible against real RFC text (see commit
`38d6292` for the fixes and their tests):

- `_SECTION_RE` mislabeled Table-of-Contents entries and body numbered-list
  items as section headers, because both are digits-and-dots but the regex
  didn't check indentation.
- The preamble-skip logic (Status of This Memo / Copyright Notice / Table
  of Contents) only recognized *numbered* section headers as the resume
  point. RFC 1997 (1996-era, uses bare headings like "Abstract" and
  "Introduction" throughout, never numbers a single section) lost its
  **entire body** to this — first caught by running the cleaner over all 16
  target RFCs, not assumed to generalize from RFC 4271 alone.

A third thing, `CitationEngine.min_score`'s corpus-size dependence, needed
recalibration rather than a bug fix — see
`investigator/retrieval/citations.py`'s `DEFAULT_MIN_SCORE_FRACTION`
docstring for the full story: the first value tried (0.2) was wrong, because
on real multi-term incident questions the ceiling-ratio does not cleanly
separate on-topic from off-topic the way it did on a synthetic test case.
Recalibrated to 0.1 empirically against this corpus.

## Detection accuracy: unchanged, as expected

```bash
python -m investigator.evaluate
```

**4/13 correct** — identical to baseline. This number never depended on the
RFC corpus (deterministic analyzers only), so it's confirmation nothing else
broke, not a corpus-expansion result.

## ACH false-assertion rate: got worse, not better

```bash
python -m investigator.evaluate --ach
```

| | 2-RFC baseline | 16-RFC expanded |
|---|---|---|
| False-assertion rate | 0/3 (0%) | **1/4 (25%)** |
| Correct assertions | 3 | 3 |
| Abstained | 10 | 9 |

This is the honest result the plan asked for, reported as it happened, not
adjusted after the fact. One incident flipped from a correct abstention to a
**false assertion**: `cloudflare-verizon-2019` (expected `route_leak`) now
gets ACH verdict `[ASPathLoop]`.

**Diagnosis, not just the number:** this incident's own catalog entry
already documents that no `RouteLeak` finding fires for it — "WithdrawalStorm
and ASPathLoop both fire as secondary signals" is a pre-existing detection
gap, unrelated to the RFC corpus. Under the 2-RFC corpus, `ASPathLoop` had no
real evidence either way (0 topically-relevant, 0 contradicting), so ACH
abstained on both candidate hypotheses. Under the 16-RFC corpus, `ASPathLoop`
found **genuine, real, checker-verified evidence**: RFC 6811 §2 and
RFC 7908 §2 do strictly entail "a repeated ASN in AS_PATH is a real signal"
— that's a true statement about this incident's raw MRT data (23
announcements really do repeat an ASN in-path). It's just not the same thing
as "this incident's root cause was a route leak." With `WithdrawalStorm`
sitting at 0 evidence either way, ACH's own least-refuted-first,
genuine-evidence-beats-zero-evidence ranking rule (the fix from the
Phase 5 ranking-bug case) correctly picks `ASPathLoop` as the strongest
hypothesis *among the ones the analyzer layer actually produced* — it just
isn't the *right* hypothesis, because the deterministic layer never produced
a `RouteLeak` finding for this incident's data pattern.

**This is a real finding, not a corpus-cleaning bug — verified before
writing it up.** Two things checked: (1) the raw MRT evidence for the
`ASPathLoop` finding is real (23 genuine AS_PATH repeats in this incident's
data, not a chunking artifact), and (2) the cited RFC passages genuinely say
what the entailment checker says they say (spot-checked RFC 6811 §2 and
RFC 7908 §2 by hand). The failure is architectural: a larger, topically
denser corpus makes it *easier* for a technically-true-but-not-root-cause
secondary signal to clear the evidence bar, when the deterministic layer has
a coverage gap (no firing `RouteLeak` hypothesis) for the actually-correct
explanation. More corpus helps a correct hypothesis clear the bar (see the
abstention-count improvement below) but does nothing to stop an incorrect
one from clearing it too, when it's the *only* one with real evidence.

**Not fixed here, deliberately.** Loosening or tightening the evidence bar
specifically to make this one case abstain again would be exactly the
"loosen the bar until it passes" anti-pattern this project's own two-tier
design was built to avoid. The real fix is closing the detection-layer gap
(a `RouteLeak` analyzer that actually fires on this incident's pattern) or a
third ACH signal that weighs "does this hypothesis's *kind* match what the
firing analyzer suite is capable of detecting for this incident shape" —
both out of scope for a corpus swap. Flagged here as a known, diagnosed
limitation, not silently absorbed into a "3 correct, 0 false" claim that
would no longer be true.

Of the baseline's 6 "no hypothesis found any genuine supporting evidence"
abstentions, 5 changed outcome:

- `cloudflare-verizon-2019` → the false assertion diagnosed above.
- `twitter-rtcomm-2022`, `klayswap-2022`, `rostelecom-2020`,
  `level3-comcast-2017` → still abstain, but for a materially different,
  more informative reason: `ABSTAIN (even the leading hypothesis has more
  refuting than topically-relevant evidence (3 vs 1; only 1 of that meets
  the strict entailment bar))`. The corpus now has real, checker-verified
  evidence on both sides of these hypotheses — it's just net unfavorable,
  not absent. That's the corpus doing its intended job: these are no longer
  "found nothing," they're "found something, and it doesn't clear the bar,"
  a materially more honest abstention than before.
- `amazon-route53-mew-2018` is the only one of the 6 unchanged — still
  "no hypothesis found any genuine supporting evidence in the corpus,"
  meaning even 16 RFCs' worth of BGP-security text has nothing topically
  close enough to this incident's specific finding.

## Real LLM narration: also worse, for a different, non-obvious reason

Re-ran the exact flagship demo command (`pakistan-youtube-2008`, same
question, `claude-haiku-4-5` hosted + `ollama/llama3.1:8b` local,
`--seek-contradictions --score-citations`) against the expanded corpus.

**Hosted (`claude-haiku-4-5`): abstained outright.** Previously answered
confidently (100% precision / 60% recall). With the expanded corpus,
retrieval for this exact question now surfaces RFC 8206/8207/6811/7454
passages (BGPsec/RPKI-adjacent, not the direct RFC 7908 §4 MOAS-definition
passage that won before) — the model had 3 more search rounds available and
used none of them, choosing `FINAL: INSUFFICIENT EVIDENCE` over asserting
from what it retrieved. Arguably the *correct*, cautious behavior for the
sources actually in front of it, but it means the flagship demo no longer
has a hosted narration to show.

**Local (`ollama/llama3.1:8b`): narrated confidently, but citation
correctness dropped to 0/4.** Unlike the hosted model, `llama3.1:8b`
composed a fluent, technically-plausible answer citing BGPsec (RFC 8205/8206)
and RPKI validation (RFC 6811) — sophisticated-*sounding* prose that turned
out to be **less grounded than before**, not more:

| | 2-RFC baseline | 16-RFC expanded |
|---|---|---|
| Claims made | 3 | 4 |
| Citation precision | 33% | n/a (0 citations entailed) |
| Citation recall | 33% | **0%** |
| Retriever errors | 1 | 3 |
| Generator errors | 1 | 1 |

**This is the standout finding of the corpus expansion, and it's a
cautionary one:** a bigger, more topically-diverse corpus gave the weaker
model *more plausible-sounding material to draw from* (real BGPsec/RPKI RFC
text, genuinely in the corpus) without the model's grounding discipline
improving to match — it name-drops real RFC sections that don't actually
say what its sentences claim. Citation-correctness scoring is exactly the
mechanism that catches this; without `--score-citations` this would read as
a *better* answer, not a worse one. More corpus is not an unconditional
improvement to citation-grounded narration — it can raise the retrieval
system's ceiling for plausible-but-wrong material faster than it raises a
given model's grounding discipline. Worth a footnote for item 7 (hybrid
dense retrieval): a corpus this size makes the retrieval quality gap between
a weaker and a stronger backend more visible, not less.

## What actually got better

- 4 of the 6 baseline "no genuine supporting evidence" abstentions now have
  real, checker-verified evidence weighed (even where it's not yet enough to
  clear the assert bar) — the corpus is doing its intended job for those.
- The section-regex and preamble-skip bugs, and the corpus-size-dependent
  score floor, are now fixed and tested independently of this specific
  corpus's content (see commit 38d6292) — durable infrastructure gains
  regardless of how this particular before/after nets out.

## What got worse, honestly

- ACH false-assertion rate: 0% → 25% (1 new false assertion), diagnosed
  above as a detection-layer gap the corpus expansion exposed rather than
  caused.
- Local-model citation-correctness on the flagship demo: 33%/33% → 0%/n/a.
- Hosted-model flagship demo: went from a confident, well-grounded answer to
  an outright abstention on the literal same question.

Per the plan's own instruction: report whichever way it goes. This is not
the flattering outcome, and it isn't being framed as one.
