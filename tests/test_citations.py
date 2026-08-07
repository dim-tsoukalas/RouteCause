import pytest

from investigator.retrieval.citations import (
    ABSTAIN_MARKER,
    BM25,
    CitationEngine,
    DenseIndex,
    _reciprocal_rank_fusion,
)
from investigator.retrieval.corpus import Chunk


CHUNKS = [
    Chunk("RFC 4271 §9.1.2", "An AS loop is detected when the local system's own "
          "autonomous system number appears in the AS_PATH attribute of a received route."),
    Chunk("RFC 7908 §4", "An unexpected change in origin AS for a prefix is a strong "
          "indicator of a prefix hijack, a MOAS condition, and warrants RPKI validation."),
    Chunk("RFC 4271 §4.3", "Withdrawn Routes carry the IP address prefixes that are being "
          "withdrawn from service because they are no longer reachable."),
]


def test_retrieval_ranks_relevant_source_first():
    eng = CitationEngine(CHUNKS, top_k=2, min_score=0.1)
    ans = eng.query("what indicates a prefix hijack or MOAS?")
    assert not ans.abstained
    assert ans.sources[0].source_id == "RFC 7908 §4"


def test_sources_are_numbered_from_one():
    eng = CitationEngine(CHUNKS, top_k=3, min_score=0.1)
    ans = eng.query("AS_PATH loop detection")
    # BM25 only returns sources with a nonzero match, so the count varies;
    # what matters is the numbering is contiguous starting at 1.
    assert [s.n for s in ans.sources] == list(range(1, len(ans.sources) + 1))
    assert len(ans.sources) >= 1


def test_abstains_when_nothing_relevant():
    eng = CitationEngine(CHUNKS, top_k=3, min_score=1.0)
    ans = eng.query("how do I bake sourdough bread")
    assert ans.abstained
    assert ABSTAIN_MARKER in ans.answer


def test_abstains_on_offtopic_via_stopword_filter():
    # Common words alone must not clear the relevance floor.
    eng = CitationEngine(CHUNKS, top_k=3, min_score=1.0)
    ans = eng.query("what is the best way to do this")
    assert ans.abstained


def test_noop_backend_preserves_sources_in_answer():
    eng = CitationEngine(CHUNKS, top_k=2, min_score=0.1)
    ans = eng.query("withdrawn routes")
    # NoOp backend echoes the prompt, which contains the numbered source block.
    assert "Source 1" in ans.answer


# --------------------------------------------------------------------------- #
# Scale-invariant relevance floor (docs/alignment-plan.md item 4b)
# --------------------------------------------------------------------------- #
# An off-topic chunk that happens to contain one rare term with high term
# frequency, padded out with a growing number of unrelated filler chunks
# that don't share that term. A fixed absolute BM25 score threshold gets
# easier to clear as the corpus grows, purely because idf(term) rises for a
# term whose document frequency stays flat -- not because the chunk got any
# more relevant. min_score_fraction is meant to be immune to exactly this.
_OFFTOPIC_LOADED = Chunk(
    "IRR", "The aggregator field appears in weather balloon telemetry aggregator logs "
           "from a coastal station."
)
_OFFTOPIC_QUERY = "aggregator field validation"


def _corpus_with_filler(n_filler: int) -> list[Chunk]:
    filler = [
        Chunk(f"F{i}", f"Filler document number {i} about unrelated topics like "
                        f"gardening and weather patterns.")
        for i in range(n_filler)
    ]
    return [_OFFTOPIC_LOADED, *filler]


def test_absolute_score_for_a_fixed_offtopic_match_drifts_up_with_corpus_size():
    small = BM25(_corpus_with_filler(0))
    large = BM25(_corpus_with_filler(500))
    small_score = small.score(_OFFTOPIC_QUERY, top_k=1)[0][1]
    large_score = large.score(_OFFTOPIC_QUERY, top_k=1)[0][1]
    # Same chunk, same query, only N changed -- yet the raw score roughly
    # 5x'd. A min_score threshold calibrated against the small corpus does
    # not mean what it meant once the corpus has grown.
    assert large_score > small_score * 3


def test_max_possible_score_ratio_stays_stable_across_corpus_sizes():
    ratios = []
    for n_filler in (0, 50, 500):
        bm25 = BM25(_corpus_with_filler(n_filler))
        top_score = bm25.score(_OFFTOPIC_QUERY, top_k=1)[0][1]
        ceiling = bm25.max_possible_score(_OFFTOPIC_QUERY)
        ratios.append(top_score / ceiling)
    # The ratio to max_possible_score is what min_score_fraction gates on --
    # unlike the raw score, it stays in a narrow band regardless of N.
    assert max(ratios) - min(ratios) < 0.05


def test_min_score_fraction_catches_a_leak_that_an_absolute_floor_misses():
    # An absolute floor calibrated to correctly abstain on the small corpus...
    small_engine = CitationEngine(_corpus_with_filler(0), top_k=1, min_score=1.0)
    assert small_engine.retrieve_sources(_OFFTOPIC_QUERY) == []
    # ...leaks through once the corpus has grown, even though nothing about
    # this chunk's actual relevance changed.
    large_engine_absolute = CitationEngine(_corpus_with_filler(500), top_k=1, min_score=1.0)
    assert large_engine_absolute.retrieve_sources(_OFFTOPIC_QUERY) != []
    # min_score_fraction, isolated from the (now-leaking) absolute floor by
    # setting min_score to 0, still catches it at the same corpus size.
    large_engine_relative = CitationEngine(
        _corpus_with_filler(500), top_k=1, min_score=0.0, min_score_fraction=0.6
    )
    assert large_engine_relative.retrieve_sources(_OFFTOPIC_QUERY) == []


# --------------------------------------------------------------------------- #
# Hybrid (BM25 + dense) retrieval (docs/alignment-plan.md item 7)
# --------------------------------------------------------------------------- #
_CHUNK_A = Chunk("A", "alpha")
_CHUNK_B = Chunk("B", "beta")
_CHUNK_C = Chunk("C", "gamma")


def test_reciprocal_rank_fusion_rewards_cross_list_agreement():
    # B appears in both lists (even at middling rank); A and C each appear
    # in only one list. Appearing in both must beat appearing in only one,
    # however well-ranked there.
    bm25_ranked = [_CHUNK_A, _CHUNK_B]
    dense_ranked = [_CHUNK_B, _CHUNK_C]
    fused = _reciprocal_rank_fusion([bm25_ranked, dense_ranked], top_k=3)
    assert fused[0][0] == _CHUNK_B


def test_reciprocal_rank_fusion_respects_top_k():
    fused = _reciprocal_rank_fusion([[_CHUNK_A, _CHUNK_B, _CHUNK_C]], top_k=2)
    assert len(fused) == 2


# A near-synonym pair BM25 cannot bridge: the query shares almost no
# vocabulary with the chunk that actually answers it, mirroring the real
# WithdrawalStorm/RouteLeak failures documented in DenseIndex's docstring
# (BM25 abstains outright on RouteLeak's real hypothesis template).
_FLAP_DAMPING_CHUNK = Chunk(
    "RFC 2439", "Route flap damping suppresses a route that is repeatedly withdrawn and "
                "re-announced by assigning it an instability penalty."
)
_UNRELATED_CHUNK = Chunk(
    "RFC 9999", "BGPsec path validation uses digital signatures to protect the AS_PATH "
                "attribute from tampering by untrusted parties."
)
_WITHDRAWAL_STORM_QUERY = "Total 403 withdrawals; peak burst 63 in window."


def test_dense_index_finds_near_synonym_bm25_would_miss():
    pytest.importorskip("sentence_transformers")
    dense = DenseIndex([_FLAP_DAMPING_CHUNK, _UNRELATED_CHUNK])
    hits = dense.score(_WITHDRAWAL_STORM_QUERY, top_k=2)
    assert hits[0][0] == _FLAP_DAMPING_CHUNK

    # Confirm this really is a case BM25 cannot bridge -- the whole point of
    # the test -- not a redundant check of something BM25 already handled.
    bm25 = BM25([_FLAP_DAMPING_CHUNK, _UNRELATED_CHUNK])
    assert bm25.score(_WITHDRAWAL_STORM_QUERY, top_k=2) == []


def test_citation_engine_hybrid_recovers_a_query_bm25_alone_abstains_on():
    pytest.importorskip("sentence_transformers")
    chunks = [_FLAP_DAMPING_CHUNK, _UNRELATED_CHUNK]
    dense = DenseIndex(chunks)

    bm25_only = CitationEngine(chunks, top_k=1, min_score=0.1)
    assert bm25_only.retrieve_sources(_WITHDRAWAL_STORM_QUERY) == []

    hybrid = CitationEngine(chunks, top_k=1, min_score=0.1, dense_index=dense, min_dense_score=0.4)
    sources = hybrid.retrieve_sources(_WITHDRAWAL_STORM_QUERY)
    assert sources and sources[0].source_id == "RFC 2439"


def test_citation_engine_hybrid_still_abstains_below_min_dense_score():
    pytest.importorskip("sentence_transformers")
    chunks = [_FLAP_DAMPING_CHUNK, _UNRELATED_CHUNK]
    dense = DenseIndex(chunks)
    # An impossibly high floor -- dense always finds *something* (cosine
    # similarity has no free "found nothing" signal the way BM25 does), so
    # min_dense_score is the only thing that can make hybrid retrieval
    # abstain when BM25 also has nothing.
    hybrid = CitationEngine(chunks, top_k=1, min_score=0.1, dense_index=dense, min_dense_score=0.99)
    assert hybrid.retrieve_sources(_WITHDRAWAL_STORM_QUERY) == []
