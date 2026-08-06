"""Citation-correctness scoring harness.

For each claim in a narrated answer, checks whether its *own* cited
source(s) actually entail it (ALCE-style precision/recall), and for claims
that fail that check, re-queries the *full* corpus (not just what got cited)
to tell apart two different failure modes, RAGChecker-style:

* generator error -- the corpus had a source that would have supported the
  claim, but the loop didn't cite it (or cited the wrong thing).
* retriever error -- nothing in the corpus supports the claim at all (no
  support exists to find, or the claim is simply hallucinated beyond the
  corpus).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from investigator.evaluation.claims import Claim, extract_claims
from investigator.evaluation.entailment import EntailmentChecker, EntailmentLabel, EntailmentVerdict
from investigator.retrieval.citations import CitationEngine, CitedAnswer, Source

# The literal marker NoOpBackend (investigator/llm.py) always prepends. Its
# output is an echoed prompt, not real generated prose -- scoring it would
# mean "checking" the prompt's own instruction text as if it were a claim.
_NOOP_MARKER = "[no-LLM mode]"


@dataclass
class ClaimVerdict:
    claim: Claim
    per_cited_source: dict[int, EntailmentVerdict] = field(default_factory=dict)
    entailed_by_any_cited: bool = False
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
            mark = "OK" if cv.entailed_by_any_cited else "MISS"
            cited = ", ".join(f"[{n}]" for n in cv.claim.cited_source_ns) or "(uncited)"
            lines.append(f"  [{mark}] {cited} {cv.claim.text}")
            if not cv.entailed_by_any_cited and cv.entailed_by_uncited_corpus_source is not None:
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


def _score_claim(claim: Claim, sources_by_n: dict[int, Source],
                  citations: CitationEngine, checker: EntailmentChecker) -> ClaimVerdict:
    per_cited: dict[int, EntailmentVerdict] = {}
    for n in claim.cited_source_ns:
        source = sources_by_n.get(n)
        if source is None:
            continue  # a citation number the answer used that isn't in the source list
        per_cited[n] = checker.check(claim.text, source.text)

    entailed = any(v.label == EntailmentLabel.ENTAILED for v in per_cited.values())
    entailed_by_uncited = None
    if not entailed:
        cited_ids = {sources_by_n[n].source_id for n in claim.cited_source_ns if n in sources_by_n}
        entailed_by_uncited = _entailed_by_corpus(claim.text, cited_ids, citations, checker)

    return ClaimVerdict(
        claim=claim,
        per_cited_source=per_cited,
        entailed_by_any_cited=entailed,
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

    total_citations = sum(len(cv.claim.cited_source_ns) for cv in verdicts)
    entailed_citations = sum(
        1 for cv in verdicts for v in cv.per_cited_source.values()
        if v.label == EntailmentLabel.ENTAILED
    )
    precision = entailed_citations / total_citations if total_citations else None
    recall = sum(1 for cv in verdicts if cv.entailed_by_any_cited) / len(verdicts)

    retriever_errors = sum(
        1 for cv in verdicts
        if not cv.entailed_by_any_cited and cv.entailed_by_uncited_corpus_source is False
    )
    generator_errors = sum(
        1 for cv in verdicts
        if not cv.entailed_by_any_cited and cv.entailed_by_uncited_corpus_source is True
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
