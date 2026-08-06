from investigator.evaluation.entailment import LexicalOverlapChecker
from investigator.evaluation.scorer import score_citations
from investigator.retrieval.citations import CitationEngine, CitedAnswer, Source
from investigator.retrieval.corpus import Chunk

# Corpus has THREE chunks; only A and B ever get cited in the answer. C
# exists purely to test the "corpus had support, but it wasn't cited"
# generator-error path.
CHUNK_A = Chunk("A", "MOAS indicates a prefix hijack when origin changes unexpectedly.")
CHUNK_B = Chunk("B", "Withdrawn routes signal a route is no longer reachable.")
CHUNK_C = Chunk("C", "A withdrawal caused packet loss for several minutes across many peers.")


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
    assert c1.entailed_by_any_cited
    # c2: cited source B does NOT support it, but uncited source C does ->
    # a generator error (the corpus had support, it wasn't used).
    assert not c2.entailed_by_any_cited
    assert c2.entailed_by_uncited_corpus_source is True
    # c3: uncited, and nothing in the whole corpus supports it -> retriever error.
    assert not c3.entailed_by_any_cited
    assert c3.entailed_by_uncited_corpus_source is False

    assert card.citation_precision == 0.5   # 1 of 2 placed citations actually entails
    assert abs(card.citation_recall - (1 / 3)) < 1e-9
    assert card.generator_error_count == 1
    assert card.retriever_error_count == 1


def test_render_not_applicable_gives_a_reason_not_a_fake_score():
    answer = CitedAnswer(query="q", answer="[no-LLM mode] x", sources=[])
    card = score_citations(answer, _citation_engine(), LexicalOverlapChecker())
    rendered = card.render()
    assert "not applicable" in rendered
    assert "%" not in rendered
