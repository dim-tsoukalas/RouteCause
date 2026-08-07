"""Adversarial / contradicting-evidence retrieval (Phase 4).

A "hypothesis" here is the claim behind one *fired* deterministic analyzer
result -- there's no separate hypothesis-generation step, the observations
Layer 1 already computed (investigator/analyzers/) are the things worth
interrogating for counter-evidence. When multiple analyzers fire on the same
incident (seen for real this session: `pakistan-youtube-2008` fires both
MOAS and RouteLeak), those are genuinely competing claims about the same
evidence.

Retrieval doesn't try to cleverly negate the search query -- lexical BM25
doesn't understand negation semantics, so a literal "NOT X" query wouldn't
reliably find refuting passages. Instead: retrieve broadly around the
hypothesis's own topic (`CitationEngine.retrieve_sources`, unchanged from
Phase 1), then let an `EntailmentChecker` classify each candidate's
*stance*. Only passages the checker labels `CONTRADICTS` count as refuting
evidence -- verified by the entailment model, never asserted by a generator.
As of the checker split below, this uses a *different* checker instance
than Phase 3's citation-correctness scoring
(`investigator.evaluation.entailment.default_contradiction_checker()`, not
`default_support_checker()`) -- see that split's rationale further down.

KNOWN, VERIFIED LIMITATION (found against the original 2-file RFC corpus;
see FIXED note below): the default (dependency-free) `LexicalOverlapChecker`
mislabeled a topically-
unrelated passage (RFC 4271 §9.1.2, about AS_PATH loop detection) as
`CONTRADICTS` a MOAS claim about origin-ASN counts. The real
`CrossEncoderNLIChecker` did too, at first -- but that was model-size-
dependent, not a fundamental limit of using a real model: the originally
chosen `nli-deberta-v3-xsmall` (~22M params, picked for speed) got it wrong;
swapping to `-base` (~184M) fixed that specific case *and* a second one
(ASPathLoop vs. the same RFC section) without breaking either of the
original clear-cut entailment/contradiction test cases -- see
`EntailmentChecker`'s docstring (investigator/evaluation/entailment.py) for
the full comparison. It did NOT fix a third, more defensible-but-still-
questionable case (RouteLeak vs. the same RFC section -- these two are
topically closer, both concerning AS_PATH mechanics, so this reads as a
genuine borderline case rather than an obvious mismatch). Bottom line,
checked directly rather than assumed: a bigger *specialized* entailment
model measurably reduces this failure mode but does not eliminate it.
Contributing factors: NLI models are known to over-rely on negation-word
*presence* as a shortcut cue (RFC prose is full of routine "MUST NOT"/"not
X" language unrelated to any specific claim), and the corpus is small
enough that BM25 has little to choose from, so topically-adjacent passages
clear its relevance floor more easily than they should. Treat
`contradicting` results as a signal worth human review, not a settled
verdict -- the same caution this project already applies to MOAS's
"presumed legitimate origin" heuristic.

FIXED, RE-TESTED: `MarginNLIContradictionChecker`
(investigator/evaluation/entailment.py), a genuine 3-way NLI model
(`MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli`, trained
partly on ANLI, which is adversarially collected specifically to break
this exact negation-shortcut pattern) requiring `CONTRADICTS` to beat both
`ENTAILED` and `UNCLEAR` by a margin, not just be the argmax. Re-tested
directly against the documented case above, not just assumed fixed by a
bigger model: scores it 99.5% neutral, 0.4% contradiction --
`tests/evaluation/test_entailment.py::test_margin_nli_contradiction_checker_fixes_the_documented_as_path_false_positive`.
One correction to the source plan's own diagnosis of this bug: it claimed
"your pipeline has no neutral" -- not accurate, `EntailmentLabel.UNCLEAR`
already existed and `CrossEncoderNLIChecker` already mapped "neutral" to
it (that's what the two-tier evidence bar below is built on). The real
problem was narrower: even a real 3-way model's raw argmax sometimes
picked `CONTRADICTS` over `NEUTRAL` on this exact case due to the
negation-shortcut bias above, not that the label didn't exist. The plan's
recommended fix (a better, ANLI-trained model, used only for this job)
still measurably works -- the diagnosis's wording was off, the
prescription wasn't.

NOT ADOPTED AS THE DEFAULT, AND HERE'S WHY -- MEASURED, NOT ASSUMED:
`MarginNLIContradictionChecker` fixes the one documented false positive
above, but swapping it in for the real 13-incident catalog
(`CITATION_CONTRADICTION_CHECKER=nli_margin`) makes the false-assertion
rate *worse*, not better: 0 correct assertions, 1 false, 12 abstained
(was 3/1/9 with lexical on the same corpus) -- `pakistan-youtube-2008` and
`china-telecom-18min-2010`, both previously *correct* MOAS assertions, now
abstain. Root cause: `investigator/ach.py`'s `rank_hypotheses()` abstains
outright if *every* hypothesis has `supporting_count == 0` (strict
`ENTAILED`), and this model is dramatically more conservative about that
label than the lexical checker -- verified directly, the two chunks the
lexical checker called "strict entailment" for MOAS (RFC 6811 §2.1,
literally pseudo-code, and RFC 7454 §6.1.2.2, generic RIR-filter prose)
both score `UNCLEAR` here, arguably a more *correct* judgment that
nonetheless collapses `supporting_count` to 0 almost everywhere,
re-triggering the original 100%-abstention problem the two-tier bar below
exists to fix. Full diagnosis, including the second, structural pattern
behind the one new false assertion, in `docs/design.md`'s "Phase 3/4
checker split" section. Stays available, opt-in only; `lexical` remains
the shipped default.

TWO-TIER EVIDENCE BAR: the flip side of that same false-positive-prone
`CONTRADICTS` signal is that strict `ENTAILED` (the lexical checker's
overlap >= 0.5) is a genuinely demanding bar for a short, numbers-heavy
analyzer claim ("2 origin ASNs observed for a single prefix.") against
RFC prose that never uses that phrasing. Against the real catalog this
produced a MOAS hypothesis with real strict-tier support (1 source) still
losing to 2 `CONTRADICTS` sources -- and one of those two was exactly the
documented RFC 4271 §9.1.2 false positive above, riding in on a
negation-mismatch against the shared, contentless token "2". Rather than
discard the `UNCLEAR` middle tier (on-topic, real vocabulary overlap, just
not confident enough for strict entailment), `ContradictionCheck` now keeps
it as `topically_relevant`, separate from `supporting`. `relevant_count`
(supporting + topically_relevant) is what ACH's assert/abstain gate
actually compares against `contradicting_count` -- see
`investigator/ach.py`'s `HypothesisScore` docstring for why. `supporting`
(strict) is still reported alongside it as the conservative number: this is
two labeled bars shown to the reader, not one bar loosened until it passes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from investigator.evaluation.entailment import EntailmentChecker, EntailmentLabel
from investigator.retrieval.citations import CitationEngine, Source
from investigator.types import Result


@dataclass(frozen=True)
class Hypothesis:
    kind: str        # analyzer kind, e.g. "MOAS"
    statement: str    # human-readable claim (Result.details)


@dataclass
class ContradictionCheck:
    hypothesis: Hypothesis
    query: str
    supporting: list[Source] = field(default_factory=list)          # ENTAILED (strict tier)
    topically_relevant: list[Source] = field(default_factory=list)  # UNCLEAR (relevance tier only)
    contradicting: list[Source] = field(default_factory=list)       # CONTRADICTS
    checker_name: str = ""

    @property
    def relevant_count(self) -> int:
        """Two-tier evidence bar (Phase 5): the corpus 'topically supports'
        this hypothesis if a source is on-topic (ENTAILED *or* UNCLEAR) and
        wasn't flagged as refuting -- weaker than strict entailment, but
        still entailment-checker-verified per source, never asserted. See
        `HypothesisScore` (investigator/ach.py) for why this tier, not the
        strict `len(supporting)`, is what ACH's assert/abstain gate uses."""
        return len(self.supporting) + len(self.topically_relevant)

    def render(self) -> str:
        lines = [f"[{self.hypothesis.kind}] {self.hypothesis.statement}"]
        if self.contradicting:
            lines.append("  Counter-evidence found (verified by entailment checker):")
            for s in self.contradicting:
                lines.append(f"    - {s.source_id}")
        else:
            lines.append("  No counter-evidence found in the corpus.")
        if self.supporting:
            lines.append("  Supporting evidence (strict entailment):")
            for s in self.supporting:
                lines.append(f"    - {s.source_id}")
        if self.topically_relevant:
            lines.append("  Additional topically-relevant evidence (relevance tier only, not strictly entailed):")
            for s in self.topically_relevant:
                lines.append(f"    - {s.source_id}")
        return "\n".join(lines)


def hypotheses_from_results(results: list[Result]) -> list[Hypothesis]:
    """One hypothesis per *fired* (non-empty) result -- by kind, not per
    individual finding, so one analyzer's own findings don't produce a
    combinatorial explosion of near-duplicate searches."""
    return [Hypothesis(kind=r.kind, statement=r.details) for r in results if not r.is_empty()]


def seek_contradictions(
    hypothesis: Hypothesis,
    citations: CitationEngine,
    checker: EntailmentChecker,
    top_k: int = 6,
) -> ContradictionCheck:
    candidates = citations.retrieve_sources(hypothesis.statement)[:top_k]
    supporting: list[Source] = []
    topically_relevant: list[Source] = []
    contradicting: list[Source] = []
    for source in candidates:
        verdict = checker.check(hypothesis.statement, source.text)
        if verdict.label == EntailmentLabel.ENTAILED:
            supporting.append(source)
        elif verdict.label == EntailmentLabel.CONTRADICTS:
            contradicting.append(source)
        elif verdict.label == EntailmentLabel.UNCLEAR:
            # On-topic (real vocabulary overlap) but not confident enough for
            # strict entailment -- kept as the weaker "relevance tier" rather
            # than silently dropped, per the two-tier evidence bar below.
            topically_relevant.append(source)
    return ContradictionCheck(
        hypothesis=hypothesis,
        query=hypothesis.statement,
        supporting=supporting,
        topically_relevant=topically_relevant,
        contradicting=contradicting,
        checker_name=checker.name(),
    )
