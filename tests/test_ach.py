from investigator.ach import build_ach_matrix, rank_hypotheses
from investigator.evaluation.entailment import LexicalOverlapChecker
from investigator.retrieval.citations import CitationEngine, Source
from investigator.retrieval.contradiction import ContradictionCheck, Hypothesis
from investigator.retrieval.corpus import Chunk


def _check(kind, supporting=0, contradicting=0, topically_relevant=0):
    hyp = Hypothesis(kind=kind, statement=f"{kind} claim")
    return ContradictionCheck(
        hypothesis=hyp,
        query=hyp.statement,
        supporting=[Source(i, f"{kind}-S{i}", "x") for i in range(supporting)],
        topically_relevant=[Source(i, f"{kind}-R{i}", "x") for i in range(topically_relevant)],
        contradicting=[Source(i, f"{kind}-C{i}", "x") for i in range(contradicting)],
        checker_name="test",
    )


def test_fewest_contradictions_wins_even_with_fewer_supporting_sources():
    # MOAS has more supporting evidence, but RouteLeak has zero contradictions
    # vs MOAS's one -- Heuer's method favors RouteLeak (least refuted).
    moas = _check("MOAS", supporting=5, contradicting=1)
    route_leak = _check("RouteLeak", supporting=1, contradicting=0)

    matrix = rank_hypotheses([moas, route_leak])

    assert not matrix.abstained
    assert matrix.leading.hypothesis.kind == "RouteLeak"
    assert matrix.scores[0].hypothesis.kind == "RouteLeak"
    assert matrix.scores[1].hypothesis.kind == "MOAS"


def test_abstains_when_top_two_are_tied():
    a = _check("MOAS", supporting=2, contradicting=1)
    b = _check("RouteLeak", supporting=2, contradicting=1)

    matrix = rank_hypotheses([a, b])

    assert matrix.abstained
    assert matrix.leading is None
    assert "cannot distinguish" in matrix.abstain_reason


def test_abstains_when_leading_hypothesis_is_net_refuted():
    only = _check("MOAS", supporting=1, contradicting=3)

    matrix = rank_hypotheses([only])

    assert matrix.abstained
    assert "more refuting than topically-relevant evidence" in matrix.abstain_reason


def test_abstains_on_empty_input():
    matrix = rank_hypotheses([])
    assert matrix.abstained
    assert matrix.scores == []


def test_zero_evidence_does_not_beat_genuine_mixed_evidence():
    # Regression test for a real bug found while measuring the false-
    # assertion rate against the real catalog: a hypothesis nobody could
    # find ANY evidence for must not outrank one with real (even if mixed)
    # supporting + contradicting evidence.
    no_evidence = _check("ASPathLoop", supporting=0, contradicting=0)
    mixed_evidence = _check("MOAS", supporting=1, contradicting=1)

    matrix = rank_hypotheses([no_evidence, mixed_evidence])

    assert not matrix.abstained
    assert matrix.leading.hypothesis.kind == "MOAS"


def test_relevance_tier_evidence_can_outweigh_contradictions_strict_alone_cannot():
    # Regression test for the real pakistan-youtube-2008 case: MOAS had 1
    # strict (ENTAILED) source and 2 CONTRADICTS sources -- net-refuted on
    # the strict count alone (1 < 2) -- but a further on-topic UNCLEAR
    # source brings relevant_count to 2, tying (not losing to) the 2
    # contradictions, so ACH should assert rather than abstain.
    moas = _check("MOAS", supporting=1, contradicting=2, topically_relevant=1)

    matrix = rank_hypotheses([moas])

    assert not matrix.abstained
    assert matrix.leading.hypothesis.kind == "MOAS"
    assert matrix.leading.relevant_count == 2
    assert matrix.leading.supporting_count == 1  # conservative strict number still reported


def test_abstains_when_nothing_found_any_supporting_evidence():
    a = _check("MOAS", supporting=0, contradicting=1)
    b = _check("RouteLeak", supporting=0, contradicting=0)

    matrix = rank_hypotheses([a, b])

    assert matrix.abstained
    assert "no hypothesis found any genuine supporting evidence" in matrix.abstain_reason


def test_asserts_when_leading_hypothesis_is_net_supported_and_unambiguous():
    strong = _check("MOAS", supporting=3, contradicting=0)
    weak = _check("ASPathLoop", supporting=0, contradicting=2)

    matrix = rank_hypotheses([strong, weak])

    assert not matrix.abstained
    assert matrix.leading.hypothesis.kind == "MOAS"


CHUNK_SUPPORTS = Chunk(
    "SUPPORT",
    "An unexpected change in origin AS for a prefix is a strong indicator of a prefix hijack.",
)
CHUNK_CONTRADICTS = Chunk(
    "CONTRADICT",
    "A change in origin AS for a prefix is not an indicator of a prefix hijack in anycast deployments.",
)


def test_build_ach_matrix_integration_with_real_checker():
    citations = CitationEngine([CHUNK_SUPPORTS, CHUNK_CONTRADICTS], top_k=6, min_score=0.1)
    hypotheses = [
        Hypothesis(
            kind="MOAS",
            statement="An unexpected change in origin AS for a prefix is a strong indicator of a prefix hijack.",
        ),
    ]
    matrix = build_ach_matrix(hypotheses, citations, LexicalOverlapChecker())
    assert len(matrix.scores) == 1
    assert matrix.scores[0].contradicting_count >= 1  # the CONTRADICT chunk should be found
