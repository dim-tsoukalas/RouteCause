from investigator.evaluation.entailment import EntailmentLabel, LexicalOverlapChecker
from investigator.evaluation.scorer import score_citations
from investigator.retrieval.citations import CitationEngine, CitedAnswer, Source
from investigator.retrieval.corpus import Chunk

# Corpus has THREE chunks; only A and B ever get cited in the answer. C
# exists purely to test the "corpus had support, but it wasn't cited"
# generator-error path.
CHUNK_A = Chunk("A", "MOAS indicates a prefix hijack when origin changes unexpectedly.")
CHUNK_B = Chunk("B", "Withdrawn routes signal a route is no longer reachable.")
CHUNK_C = Chunk("C", "A withdrawal caused packet loss for several minutes across many peers.")

# D and E each cover half of a claim's vocabulary -- neither alone clears the
# lexical-overlap ENTAILED threshold, but their concatenation does. This is
# the ALCE joint-support case: ("neither citation sufficient alone, only the
# concatenation is") that the old any-cited-entails rule scored as recall 0.
CHUNK_D = Chunk("D", "Hijack detection relies on monitoring prefixes.")
CHUNK_E = Chunk("E", "Origin validation is confirmed via authorization.")


def _citation_engine():
    return CitationEngine([CHUNK_A, CHUNK_B, CHUNK_C], top_k=4, min_score=0.1)


def test_not_applicable_for_noop_answer():
    answer = CitedAnswer(
        query="q", answer="[no-LLM mode] echoed prompt text with Source 1 (A):",
        sources=[Source(1, "A", CHUNK_A.text)],
    )
    card = score_citations(answer, _citation_engine(), LexicalOverlapChecker())
    assert not card.applicable
    assert "no real narration" in card.not_applicable_reason


def test_not_applicable_for_abstained_answer():
    answer = CitedAnswer(query="q", answer="INSUFFICIENT EVIDENCE", sources=[], abstained=True)
    card = score_citations(answer, _citation_engine(), LexicalOverlapChecker())
    assert not card.applicable


def test_full_scoring_scenario_precision_recall_and_error_split():
    answer = CitedAnswer(
        query="why",
        answer=(
            "MOAS indicates a hijack when origin changes [1]. "
            "The withdrawal caused packet loss for several minutes [2]. "
            "Ducks are aquatic birds entirely unrelated to networking."
        ),
        sources=[Source(1, "A", CHUNK_A.text), Source(2, "B", CHUNK_B.text)],
    )
    card = score_citations(answer, _citation_engine(), LexicalOverlapChecker())

    assert card.applicable
    assert len(card.claim_verdicts) == 3

    c1, c2, c3 = card.claim_verdicts
    # c1: cited source A genuinely supports it -> recall hit.
    assert c1.recall_met
    # c2: cited source B does NOT support it, but uncited source C does ->
    # a generator error (the corpus had support, it wasn't used).
    assert not c2.recall_met
    assert c2.entailed_by_uncited_corpus_source is True
    # c3: uncited, and nothing in the whole corpus supports it -> retriever error.
    assert not c3.recall_met
    assert c3.entailed_by_uncited_corpus_source is False

    # ALCE gates precision on recall: c2's citation isn't counted at all
    # (its claim failed recall), so precision is 1/1 (only c1's citation),
    # not 1/2 -- a claim's citations aren't "imprecise" just because the
    # claim itself wasn't supported.
    assert card.citation_precision == 1.0
    assert abs(card.citation_recall - (1 / 3)) < 1e-9
    assert card.generator_error_count == 1
    assert card.retriever_error_count == 1


def test_joint_citation_support_counts_toward_alce_recall_and_precision():
    answer = CitedAnswer(
        query="why",
        answer="Hijack detection requires origin validation checks [1][2].",
        sources=[Source(1, "D", CHUNK_D.text), Source(2, "E", CHUNK_E.text)],
    )
    engine = CitationEngine([CHUNK_A, CHUNK_B, CHUNK_C, CHUNK_D, CHUNK_E], top_k=5, min_score=0.1)
    card = score_citations(answer, engine, LexicalOverlapChecker())

    assert len(card.claim_verdicts) == 1
    cv = card.claim_verdicts[0]
    # Neither citation entails the claim by itself...
    assert cv.per_cited_source[1].label != EntailmentLabel.ENTAILED
    assert cv.per_cited_source[2].label != EntailmentLabel.ENTAILED
    # ...but ALCE recall checks the concatenation of everything cited, which does.
    assert cv.recall_met
    assert card.citation_recall == 1.0
    # Both were necessary for that joint support (dropping either breaks
    # entailment) -> both precise, not just "cited".
    assert cv.precise_citations == {1, 2}
    assert card.citation_precision == 1.0


def test_render_not_applicable_gives_a_reason_not_a_fake_score():
    answer = CitedAnswer(query="q", answer="[no-LLM mode] x", sources=[])
    card = score_citations(answer, _citation_engine(), LexicalOverlapChecker())
    rendered = card.render()
    assert "not applicable" in rendered
    assert "%" not in rendered
