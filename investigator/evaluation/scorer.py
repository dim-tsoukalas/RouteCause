"""Citation-correctness scoring harness.

Matches ALCE's (Gao et al., 2023) statement-level definitions, not an
approximation of them:

* Citation recall for a claim is 1 iff it has >=1 citation AND the
  *concatenation* of all its cited sources entails it -- not "at least one
  cited source, alone, entails it". A claim jointly supported by two
  passages that are each insufficient alone (real case: RFC 7908 SS4 +
  RFC 4271 SS9.1.2 grounding one MOAS claim, neither sufficient alone) scores
  1 here, not 0.
* Citation precision is only computed over claims whose recall is 1 (ALCE
  gates it that way -- an unsupported claim's citations aren't "wrong", the
  claim itself is). Within those, a citation is precise if it entails the
  claim alone, or if removing it from the cited set breaks the
  concatenation's entailment (i.e. it was load-bearing even though
  insufficient alone). A citation that could be dropped with no loss of
  support is not counted as precise (redundant, not wrong).

For claims that fail recall, re-queries the *full* corpus (not just what got
cited) to tell apart two different failure modes, RAGChecker-style:

* generator error -- the corpus had a source that would have supported the
  claim, but the loop didn't cite it (or cited the wrong thing).
* retriever error -- nothing in the corpus supports the claim at all (no
  support exists to find, or the claim is simply hallucinated beyond the
  corpus).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from investigator.evaluation.claims import Claim, extract_claims
from investigator.evaluation.entailment import (
    EntailmentChecker,
    EntailmentLabel,
    EntailmentVerdict,
)
from investigator.retrieval.citations import CitationEngine, CitedAnswer, Source

# The literal marker NoOpBackend (investigator/llm.py) always prepends. Its
# output is an echoed prompt, not real generated prose -- scoring it would
# mean "checking" the prompt's own instruction text as if it were a claim.
_NOOP_MARKER = "[no-LLM mode]"


@dataclass
class ClaimVerdict:
    claim: Claim
    per_cited_source: dict[int, EntailmentVerdict] = field(default_factory=dict)
    concat_verdict: EntailmentVerdict | None = None  # entailment of claim by ALL cited sources joined
    recall_met: bool = False  # ALCE recall: >=1 citation AND concat_verdict is ENTAILED
    precise_citations: frozenset[int] = frozenset()  # citation ns judged precise (only set when recall_met)
    entailed_by_uncited_corpus_source: bool | None = None  # None: not checked (not needed)


@dataclass
class CitationScorecard:
    applicable: bool
    claim_verdicts: list[ClaimVerdict] = field(default_factory=list)
    citation_precision: float | None = None
    citation_recall: float | None = None
    retriever_error_count: int = 0
    generator_error_count: int = 0
    checker_name: str = ""
    not_applicable_reason: str = ""

    def render(self) -> str:
        if not self.applicable:
            return f"Citation-correctness scorecard: not applicable ({self.not_applicable_reason})"

        lines = [
            f"Citation-correctness scorecard (checker: {self.checker_name}):",
            f"  claims: {len(self.claim_verdicts)}",
            f"  citation precision: {_fmt_pct(self.citation_precision)}",
            f"  citation recall: {_fmt_pct(self.citation_recall)}",
            f"  retriever errors (no corpus support found): {self.retriever_error_count}",
            f"  generator errors (corpus had support, not cited): {self.generator_error_count}",
        ]
        for cv in self.claim_verdicts:
            mark = "OK" if cv.recall_met else "MISS"
            cited = ", ".join(f"[{n}]" for n in cv.claim.cited_source_ns) or "(uncited)"
            lines.append(f"  [{mark}] {cited} {cv.claim.text}")
            if cv.recall_met:
                imprecise = [n for n in cv.claim.cited_source_ns if n not in cv.precise_citations]
                if imprecise:
                    redundant = ", ".join(f"[{n}]" for n in imprecise)
                    lines.append(f"        -> {redundant} redundant (claim entailed without them)")
            elif cv.entailed_by_uncited_corpus_source is not None:
                cause = "generator error" if cv.entailed_by_uncited_corpus_source else "retriever error"
                lines.append(f"        -> {cause}")
        return "\n".join(lines)


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _entailed_by_corpus(claim_text: str, exclude_ids: set[str],
                         citations: CitationEngine, checker: EntailmentChecker) -> bool:
    candidates = citations.retrieve_sources(claim_text)
    for source in candidates:
        if source.source_id in exclude_ids:
            continue
        if checker.check(claim_text, source.text).label == EntailmentLabel.ENTAILED:
            return True
    return False


def _concat_check(claim_text: str, sources: list[Source], checker: EntailmentChecker) -> EntailmentVerdict | None:
    if not sources:
        return None
    concat_text = "\n\n".join(s.text for s in sources)
    return checker.check(claim_text, concat_text)


def _precise_citations(claim: Claim, sources_by_n: dict[int, Source],
                        per_cited: dict[int, EntailmentVerdict], checker: EntailmentChecker) -> frozenset[int]:
    """ALCE necessity test, only ever called when the full cited set entails
    the claim (recall_met). A citation is precise if it entails the claim by
    itself, or if the *rest* of the cited set no longer entails the claim
    without it (i.e. it was load-bearing). A citation droppable with no loss
    of support is redundant, not precise."""
    cited_ns = [n for n in claim.cited_source_ns if n in sources_by_n]
    precise: set[int] = set()
    for n in cited_ns:
        if per_cited[n].label == EntailmentLabel.ENTAILED:
            precise.add(n)
            continue
        remaining = [sources_by_n[m] for m in cited_ns if m != n]
        remaining_verdict = _concat_check(claim.text, remaining, checker)
        still_entailed = remaining_verdict is not None and remaining_verdict.label == EntailmentLabel.ENTAILED
        if not still_entailed:
            precise.add(n)  # this citation was necessary for joint support
    return frozenset(precise)


def _score_claim(claim: Claim, sources_by_n: dict[int, Source],
                  citations: CitationEngine, checker: EntailmentChecker) -> ClaimVerdict:
    per_cited: dict[int, EntailmentVerdict] = {}
    for n in claim.cited_source_ns:
        source = sources_by_n.get(n)
        if source is None:
            continue  # a citation number the answer used that isn't in the source list
        per_cited[n] = checker.check(claim.text, source.text)

    cited_sources = [sources_by_n[n] for n in claim.cited_source_ns if n in sources_by_n]
    concat_verdict = _concat_check(claim.text, cited_sources, checker)
    recall_met = concat_verdict is not None and concat_verdict.label == EntailmentLabel.ENTAILED

    precise_citations: frozenset[int] = frozenset()
    entailed_by_uncited = None
    if recall_met:
        precise_citations = _precise_citations(claim, sources_by_n, per_cited, checker)
    else:
        cited_ids = {s.source_id for s in cited_sources}
        entailed_by_uncited = _entailed_by_corpus(claim.text, cited_ids, citations, checker)

    return ClaimVerdict(
        claim=claim,
        per_cited_source=per_cited,
        concat_verdict=concat_verdict,
        recall_met=recall_met,
        precise_citations=precise_citations,
        entailed_by_uncited_corpus_source=entailed_by_uncited,
    )


def score_citations(
    answer: CitedAnswer, citations: CitationEngine, checker: EntailmentChecker
) -> CitationScorecard:
    if answer.abstained:
        return CitationScorecard(
            applicable=False,
            not_applicable_reason="the answer abstained -- no claims were made to score",
        )
    if answer.answer.startswith(_NOOP_MARKER):
        return CitationScorecard(
            applicable=False,
            not_applicable_reason="offline/no-LLM mode has no real narration to score, "
                                   "only the echoed prompt",
        )

    sources_by_n = {s.n: s for s in answer.sources}
    claims = extract_claims(answer.answer)
    if not claims:
        return CitationScorecard(
            applicable=False,
            not_applicable_reason="no claims could be segmented from the answer text",
        )

    verdicts = [_score_claim(c, sources_by_n, citations, checker) for c in claims]

    # ALCE gates precision on recall: citations belonging to a claim that
    # itself isn't supported by its full cited set don't count as either
    # precise or imprecise -- the claim failed, not those specific citations.
    recall_met_verdicts = [cv for cv in verdicts if cv.recall_met]
    total_citations = sum(len(cv.claim.cited_source_ns) for cv in recall_met_verdicts)
    precise_citations = sum(len(cv.precise_citations) for cv in recall_met_verdicts)
    precision = precise_citations / total_citations if total_citations else None
    recall = sum(1 for cv in verdicts if cv.recall_met) / len(verdicts)

    retriever_errors = sum(
        1 for cv in verdicts
        if not cv.recall_met and cv.entailed_by_uncited_corpus_source is False
    )
    generator_errors = sum(
        1 for cv in verdicts
        if not cv.recall_met and cv.entailed_by_uncited_corpus_source is True
    )

    return CitationScorecard(
        applicable=True,
        claim_verdicts=verdicts,
        citation_precision=precision,
        citation_recall=recall,
        retriever_error_count=retriever_errors,
        generator_error_count=generator_errors,
        checker_name=checker.name(),
    )
