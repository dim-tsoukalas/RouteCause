from investigator.agent import AgentLoop
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


class ScriptedBackend:
    """Test double: returns pre-programmed responses in sequence. Distinct
    from NoOpBackend, which deliberately never triggers a second round."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls = 0

    def complete(self, prompt: str) -> str:
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response

    def name(self) -> str:
        return "scripted"


def test_single_round_when_backend_answers_immediately():
    backend = ScriptedBackend(["FINAL: prefix hijacks show as MOAS [1]."])
    eng = CitationEngine(CHUNKS, top_k=2, min_score=0.1)
    loop = AgentLoop(eng, backend, max_iterations=3)

    ans = loop.run("what indicates a prefix hijack?", seed_query="prefix hijack MOAS")

    assert not ans.abstained
    assert ans.answer == "prefix hijacks show as MOAS [1]."
    assert len(ans.trace) == 1  # only the mandatory seed search
    assert backend.calls == 1


def test_multi_round_accumulates_sources_without_duplicates():
    backend = ScriptedBackend([
        'ACTION: search_rfcs("withdrawn routes reachability")',
        "FINAL: hijacks show as MOAS [1] and withdrawals are covered separately [2].",
    ])
    eng = CitationEngine(CHUNKS, top_k=1, min_score=0.1)
    loop = AgentLoop(eng, backend, max_iterations=3)

    ans = loop.run("what indicates a prefix hijack, and what about withdrawals?",
                    seed_query="prefix hijack MOAS")

    assert not ans.abstained
    assert backend.calls == 2
    assert len(ans.trace) == 2
    # two distinct sections retrieved across the two rounds, numbered 1..2, no dupes
    ids = [s.source_id for s in ans.sources]
    assert len(ids) == len(set(ids))
    assert [s.n for s in ans.sources] == list(range(1, len(ans.sources) + 1))


def test_repeated_query_does_not_duplicate_sources():
    backend = ScriptedBackend([
        'ACTION: search_rfcs("prefix hijack MOAS")',  # same as the seed query
        "FINAL: confirmed [1].",
    ])
    eng = CitationEngine(CHUNKS, top_k=1, min_score=0.1)
    loop = AgentLoop(eng, backend, max_iterations=3)

    ans = loop.run("q", seed_query="prefix hijack MOAS")

    ids = [s.source_id for s in ans.sources]
    assert len(ids) == len(set(ids))


def test_max_iterations_bound_forces_a_usable_answer():
    backend = ScriptedBackend(['ACTION: search_rfcs("x")'])  # always requests another round
    eng = CitationEngine(CHUNKS, top_k=1, min_score=0.1)
    loop = AgentLoop(eng, backend, max_iterations=2)

    ans = loop.run("q", seed_query="prefix hijack MOAS")

    assert backend.calls == 2
    assert "search limit reached" in ans.answer
    assert ans.sources  # grounding gathered so far is still returned
    assert not ans.abstained


def test_malformed_response_falls_through_to_final():
    # Covers the NoOp-safety path: any response not matching ACTION: is
    # treated as the final answer, without depending on NoOpBackend's exact text.
    backend = ScriptedBackend(["some free-form answer that isn't ACTION or FINAL prefixed"])
    eng = CitationEngine(CHUNKS, top_k=2, min_score=0.1)
    loop = AgentLoop(eng, backend, max_iterations=3)

    ans = loop.run("what indicates a prefix hijack?", seed_query="prefix hijack MOAS")

    assert backend.calls == 1
    assert ans.answer == "some free-form answer that isn't ACTION or FINAL prefixed"
    assert len(ans.trace) == 1


def test_abstains_when_seed_search_finds_nothing_and_backend_gives_up():
    backend = ScriptedBackend([f"FINAL: {ABSTAIN_MARKER} — no sufficiently relevant source found."])
    eng = CitationEngine(CHUNKS, top_k=2, min_score=1.0)
    loop = AgentLoop(eng, backend, max_iterations=3)

    ans = loop.run("how do I bake sourdough bread", seed_query="how do I bake sourdough bread")

    assert ans.abstained
    assert not ans.sources
