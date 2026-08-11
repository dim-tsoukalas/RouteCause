"""Competing-hypothesis (ACH) reasoning + measured abstention (Phase 5).

Heuer's Analysis of Competing Hypotheses, applied to the `Hypothesis` /
`ContradictionCheck` objects Phase 4 (investigator/retrieval/contradiction.py)
already produces: rank by *fewest refuting sources first*, not most
supporting sources -- ACH's actual insight is to fight confirmation bias by
minimizing disconfirmation, not by maximizing confirmation. Abstains rather
than asserting a hypothesis that isn't actually well-supported.

Deliberately not Self-RAG reflection tokens or an LLM "judging" its own
evidence sufficiency: that would reintroduce the self-critique problem
arXiv:2310.01798 ("LLMs Cannot Self-Correct Reasoning Yet") found unreliable,
which is exactly why Phase 4's contradiction search is retrieval-and-
entailment-verified rather than generator-asserted in the first place. The
abstention decision here is a fully computed function of hard evidence
counts -- never a model judging itself.

TWO-TIER EVIDENCE BAR: `HypothesisScore` carries both `supporting_count`
(strict: entailment-checker `ENTAILED` only) and `relevant_count` (relevance:
`ENTAILED` + `UNCLEAR` -- on-topic per the checker, even if not confident
enough to call strict entailment; see `ContradictionCheck.relevant_count` in
investigator/retrieval/contradiction.py for why the `UNCLEAR` tier is worth
keeping at all). The leading hypothesis's net-refuted gate below compares
`contradicting_count` against `relevant_count`, not the strict count: against
the real catalog, requiring strict entailment to outweigh contradictions
abstained on every single incident, including ones (e.g. `pakistan-youtube-2008`)
where the leading hypothesis already had genuine strict-tier support and the
"refuting" evidence was itself the documented lexical-checker false positive
in contradiction.py's docstring. Both numbers are always reported together
(`render()`, `ACHMatrix.render()`) -- this loosens *which bar an assertion is
measured against*, not what counts as evidence; nothing here lets an
uncontested, zero-evidence hypothesis assert, and the strict count stays
visible as the conservative cross-check.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from investigator.evaluation.entailment import EntailmentChecker
from investigator.retrieval.citations import CitationEngine
from investigator.retrieval.contradiction import (
    ContradictionCheck,
    Hypothesis,
    seek_contradictions,
)


@dataclass
class HypothesisScore:
    hypothesis: Hypothesis
    check: ContradictionCheck
    supporting_count: int    # strict tier: ENTAILED only -- the conservative number
    relevant_count: int      # relevance tier: ENTAILED + UNCLEAR -- what the assert/abstain gate uses
    contradicting_count: int


@dataclass
class ACHMatrix:
    scores: list[HypothesisScore] = field(default_factory=list)  # ranked, least-refuted first
    abstained: bool = False
    abstain_reason: str = ""

    @property
    def leading(self) -> HypothesisScore | None:
        return None if self.abstained or not self.scores else self.scores[0]

    def render(self) -> str:
        lines = ["ACH ranking (least-refuted first):"]
        for i, s in enumerate(self.scores, start=1):
            lines.append(
                f"  {i}. [{s.hypothesis.kind}] {s.hypothesis.statement} "
                f"-- {s.relevant_count} topically-relevant ({s.supporting_count} strictly entailed), "
                f"{s.contradicting_count} contradicting"
            )
        if self.abstained:
            lines.append(f"Verdict: ABSTAIN -- {self.abstain_reason}")
        elif self.leading is not None:
            lines.append(
                f"Verdict: leading hypothesis is [{self.leading.hypothesis.kind}] "
                f"{self.leading.hypothesis.statement} "
                f"(asserted on relevance-tier evidence: {self.leading.relevant_count} vs "
                f"{self.leading.contradicting_count} contradicting; conservative strict-entailment "
                f"count: {self.leading.supporting_count})"
            )
        return "\n".join(lines)


def rank_hypotheses(checks: list[ContradictionCheck]) -> ACHMatrix:
    """Pure: Heuer ranking + abstention rules. No I/O, so it's directly
    unit-testable, and reusable without redoing retrieval/entailment calls
    by callers (CLI, evaluate.py) that already computed the checks."""
    if not checks:
        return ACHMatrix(scores=[], abstained=True, abstain_reason="no analyzer findings to evaluate")

    scores = [
        HypothesisScore(c.hypothesis, c, len(c.supporting), c.relevant_count, len(c.contradicting))
        for c in checks
    ]
    # Rank key, in priority order: (1) a hypothesis with genuine supporting
    # evidence always outranks one with none -- a hypothesis nobody could
    # find ANY evidence for shouldn't win just because it also wasn't
    # contradicted (found and fixed a real bug here: per-hypothesis
    # independent retrieval means "found nothing" and "found something and
    # got it right" aren't naturally comparable on contradicting-count
    # alone). (2) among hypotheses that do have support, fewest
    # contradictions first -- Heuer's actual insight, minimize
    # disconfirmation rather than maximize confirmation. (3) ties broken by
    # most supporting.
    scores.sort(key=lambda s: (s.supporting_count == 0, s.contradicting_count, -s.supporting_count))

    if all(s.supporting_count == 0 for s in scores):
        return ACHMatrix(
            scores=scores, abstained=True,
            abstain_reason="no hypothesis found any genuine supporting evidence in the corpus",
        )

    leader = scores[0]
    if leader.contradicting_count > leader.relevant_count:
        return ACHMatrix(
            scores=scores, abstained=True,
            abstain_reason=(
                f"even the leading hypothesis ([{leader.hypothesis.kind}]) has more "
                f"refuting than topically-relevant evidence ({leader.contradicting_count} vs "
                f"{leader.relevant_count}; only {leader.supporting_count} of that meets the "
                f"strict entailment bar)"
            ),
        )

    if len(scores) >= 2:
        runner_up = scores[1]
        leader_key = (leader.supporting_count == 0, leader.contradicting_count, leader.supporting_count)
        runner_up_key = (runner_up.supporting_count == 0, runner_up.contradicting_count, runner_up.supporting_count)
        if leader_key == runner_up_key:
            return ACHMatrix(
                scores=scores, abstained=True,
                abstain_reason=(
                    f"cannot distinguish between competing hypotheses "
                    f"[{leader.hypothesis.kind}] and [{runner_up.hypothesis.kind}] "
                    f"-- tied on both supporting and contradicting evidence"
                ),
            )

    return ACHMatrix(scores=scores, abstained=False)


def build_ach_matrix(
    hypotheses: list[Hypothesis], citations: CitationEngine, checker: EntailmentChecker
) -> ACHMatrix:
    """One-shot convenience: seek_contradictions() per hypothesis, then
    rank_hypotheses(). Used by investigator.evaluate's --ach path."""
    checks = [seek_contradictions(h, citations, checker) for h in hypotheses]
    return rank_hypotheses(checks)
