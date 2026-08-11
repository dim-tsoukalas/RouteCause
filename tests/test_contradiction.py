from investigator.evaluation.entailment import LexicalOverlapChecker
from investigator.retrieval.citations import CitationEngine
from investigator.retrieval.contradiction import (
    Hypothesis,
    hypotheses_from_results,
    seek_contradictions,
)
from investigator.retrieval.corpus import Chunk
from investigator.types import Finding, Result

CHUNK_SUPPORTS = Chunk(
    "SUPPORT",
    "An unexpected change in origin AS for a prefix is a strong indicator of a prefix hijack.",
)
CHUNK_CONTRADICTS = Chunk(
    "CONTRADICT",
    "A change in origin AS for a prefix is not an indicator of a prefix hijack in anycast deployments.",
)
CHUNK_UNRELATED = Chunk("UNRELATED", "Sourdough bread requires a long fermentation time.")
CHUNK_TOPICALLY_RELEVANT = Chunk("RELEVANT", "alpha zeta eta theta iota kappa lambda")


def _citation_engine():
    return CitationEngine(
        [CHUNK_SUPPORTS, CHUNK_CONTRADICTS, CHUNK_UNRELATED], top_k=6, min_score=0.1
    )


def test_hypotheses_from_results_only_includes_fired_results():
    results = [
        Result(kind="MOAS", name="p", details="Prefix p was announced by 2 origin ASNs.",
               findings=[Finding(text="x")]),
        Result(kind="WithdrawalStorm", name="p", details="", findings=[]),  # empty -> not a hypothesis
    ]
    hyps = hypotheses_from_results(results)
    assert len(hyps) == 1
    assert hyps[0].kind == "MOAS"
    assert hyps[0].statement == "Prefix p was announced by 2 origin ASNs."


def test_hypotheses_from_results_empty_when_nothing_fired():
    results = [Result(kind="MOAS", name="p", details="", findings=[])]
    assert hypotheses_from_results(results) == []


def test_seek_contradictions_finds_verified_counter_evidence():
    hypothesis = Hypothesis(
        kind="MOAS",
        statement="An unexpected change in origin AS for a prefix is a strong indicator of a prefix hijack.",
    )
    check = seek_contradictions(hypothesis, _citation_engine(), LexicalOverlapChecker())

    contradicting_ids = {s.source_id for s in check.contradicting}
    assert "CONTRADICT" in contradicting_ids
    assert "UNRELATED" not in contradicting_ids  # irrelevant, not a refutation


def test_seek_contradictions_keeps_unclear_as_topically_relevant():
    # UNCLEAR (on-topic, real vocabulary overlap, but below the strict
    # ENTAILED threshold) must not be silently dropped -- it's the
    # relevance-tier evidence ACH's assert/abstain gate relies on.
    hypothesis = Hypothesis(kind="MOAS", statement="alpha beta gamma delta epsilon")
    engine = CitationEngine([CHUNK_TOPICALLY_RELEVANT], top_k=6, min_score=0.1)
    check = seek_contradictions(hypothesis, engine, LexicalOverlapChecker())

    relevant_ids = {s.source_id for s in check.topically_relevant}
    assert "RELEVANT" in relevant_ids
    assert check.supporting == []
    assert check.relevant_count == 1


def test_seek_contradictions_reports_none_found_honestly():
    # A hypothesis with no real counter-evidence anywhere in this corpus.
    hypothesis = Hypothesis(kind="ASPathLoop", statement="Sourdough bread requires fermentation.")
    engine = CitationEngine([CHUNK_SUPPORTS, CHUNK_CONTRADICTS], top_k=6, min_score=0.1)
    check = seek_contradictions(hypothesis, engine, LexicalOverlapChecker())

    assert check.contradicting == []
    assert "No counter-evidence found" in check.render()
