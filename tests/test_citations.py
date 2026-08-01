from investigator.retrieval.citations import ABSTAIN_MARKER, CitationEngine
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
