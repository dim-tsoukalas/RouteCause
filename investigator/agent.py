"""Agentic tool-calling loop over RFC retrieval (Phase 1 parity item).

Mirrors HolmesGPT's agentic loop, with one deliberate constraint: the only
tool available is `search_rfcs(query)`. Detection stays exactly as it was —
`investigator.analyzers.all_analyzers()` runs unconditionally, first, with no
LLM involvement (see docs/design.md's "two-layer split"). Letting an LLM
choose *whether/which analyzers to run* would reopen the hallucination risk
that split exists to close, so the loop only ever decides how much RFC
grounding to gather before answering — never what counts as evidence.

Mechanism: prompt-based ReAct parsing (`ACTION: search_rfcs("...")` /
`FINAL: ...` text lines, regex-parsed) rather than native LiteLLM
function-calling. This keeps `LLMBackend.complete(prompt) -> str` unchanged
and works identically across every LiteLLM-supported provider.

NoOp-safety: the loop unconditionally performs one seed `search_rfcs` call
before ever prompting the backend, so offline mode (NoOpBackend, which can't
"decide" anything) always gets the same retrieval it got before this loop
existed. NoOp's echoed response never matches `ACTION:`, so it falls through
to "treat as final" after that one mandatory round.
"""
from __future__ import annotations

import re

from investigator.llm import LLMBackend
from investigator.retrieval.citations import ABSTAIN_MARKER, CitationEngine, CitedAnswer, Source

_ACTION_RE = re.compile(r'^\s*ACTION:\s*search_rfcs\(\s*"(.+?)"\s*\)\s*$', re.IGNORECASE | re.MULTILINE)
_FINAL_RE = re.compile(r'^\s*FINAL:\s*(.*)$', re.IGNORECASE | re.DOTALL)

_TOOL_PROMPT_HEADER = (
    "You are investigating a network incident. One tool is available:\n\n"
    '  search_rfcs("<query>") - searches the RFC reference corpus and returns '
    "numbered source passages relevant to <query>.\n\n"
    "You have already been given the results of one search below. If they are "
    "not sufficient to answer the question, you may request up to {rounds_left} "
    "more search(es). Respond with EXACTLY ONE of:\n\n"
    '  ACTION: search_rfcs("<a different or refined query>")\n'
    "  FINAL: <your answer, citing sources inline as [n], using ONLY the "
    f"sources shown below. If none are sufficient, respond with "
    f'FINAL: {ABSTAIN_MARKER} — no sufficiently relevant source found.>\n\n'
)


def _format_sources(sources: list[Source]) -> str:
    if not sources:
        return "(no sources found for this query)\n"
    return "\n".join(f"Source {s.n} ({s.source_id}):\n{s.text}\n" for s in sources)


class AgentLoop:
    """Runs the seed search + bounded ReAct loop, returns a CitedAnswer."""

    def __init__(self, citations: CitationEngine, backend: LLMBackend, max_iterations: int = 3):
        self.citations = citations
        self.backend = backend
        self.max_iterations = max_iterations

    def run(self, question: str, seed_query: str) -> CitedAnswer:
        all_sources: list[Source] = []
        seen_ids: set[str] = set()
        trace: list[str] = []

        def add_round(query: str) -> list[Source]:
            new = self.citations.retrieve_sources(query)
            fresh = [s for s in new if s.source_id not in seen_ids]
            for s in fresh:
                s.n = len(all_sources) + 1
                all_sources.append(s)
                seen_ids.add(s.source_id)
            trace.append(f'Searched RFCs for "{query}" -> {len(new)} source(s) ({len(fresh)} new)')
            return all_sources

        add_round(seed_query)

        transcript = ""
        for i in range(self.max_iterations):
            rounds_left = self.max_iterations - i
            prompt = (
                _TOOL_PROMPT_HEADER.format(rounds_left=rounds_left)
                + _format_sources(all_sources)
                + transcript
                + f"\nQuestion: {question}\n"
            )
            response = self.backend.complete(prompt).strip()

            action_match = _ACTION_RE.match(response)
            if action_match:
                query = action_match.group(1)
                add_round(query)
                transcript += f'\n[Previous ACTION: search_rfcs("{query}") — observation incorporated above.]\n'
                continue

            final_match = _FINAL_RE.match(response)
            answer = final_match.group(1).strip() if final_match else response
            return self._finish(question, answer, all_sources, trace)

        # Bound reached and the backend never emitted FINAL: don't leak the
        # last raw (unparsed) ACTION line as if it were an answer.
        trace.append(f"Reached the {self.max_iterations}-round search limit without a final answer.")
        fallback = (
            f"[search limit reached after {self.max_iterations} round(s)] "
            "The sources gathered below are the best grounding found; no final "
            "answer was produced within the round budget."
        )
        return self._finish(question, fallback, all_sources, trace)

    @staticmethod
    def _finish(question: str, answer: str, sources: list[Source], trace: list[str]) -> CitedAnswer:
        if not sources:
            return CitedAnswer(
                query=question,
                answer=ABSTAIN_MARKER + " — no sufficiently relevant source found.",
                sources=[],
                abstained=True,
                trace=trace,
            )
        abstained = answer.upper().startswith(ABSTAIN_MARKER)
        return CitedAnswer(query=question, answer=answer, sources=sources, abstained=abstained, trace=trace)
