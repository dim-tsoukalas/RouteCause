"""BM25 retrieval + a CitationEngine.

The CitationEngine mirrors the semantics of LlamaIndex's CitationQueryEngine:
numbered sources are shown to the model, it is asked to answer *solely* from
them and cite inline with [n], and — critically — to abstain if none of the
sources are helpful. Retrieval here is a small, dependency-free BM25 so the
whole thing runs offline; swap in hybrid BM25+dense (LlamaIndex/Qdrant) for
production without changing the engine's interface.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from investigator.llm import LLMBackend, NoOpBackend
from investigator.retrieval.corpus import Chunk, _tokenize

# Small stopword set. Without this, BM25 matches on "the/is/for/a" which are
# common in RFC prose, defeating the abstention floor on off-topic queries.
STOPWORDS = frozenset(
    "a an and are as at be by for from how in into is it of on or that the to "
    "was what when where which who why with do does did i you we they this these "
    "those there here best most can could should would".split()
)


# --------------------------------------------------------------------------- #
# Minimal BM25 (Okapi) — no external dependency
# --------------------------------------------------------------------------- #
class BM25:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.docs = [c.tokens() for c in chunks]
        self.doc_len = [len(d) for d in self.docs]
        self.avgdl = (sum(self.doc_len) / len(self.docs)) if self.docs else 0.0
        self.freqs = [Counter(d) for d in self.docs]
        self.df: Counter = Counter()
        for d in self.docs:
            for term in set(d):
                self.df[term] += 1
        self.n = len(self.docs)

    def _idf(self, term: str) -> float:
        n_q = self.df.get(term, 0)
        # BM25 idf with +1 to stay non-negative
        return math.log(1 + (self.n - n_q + 0.5) / (n_q + 0.5))

    def score(self, query: str, top_k: int = 4) -> list[tuple[Chunk, float]]:
        q_terms = [t for t in _tokenize(query) if t not in STOPWORDS]
        scored: list[tuple[Chunk, float]] = []
        for i, freq in enumerate(self.freqs):
            s = 0.0
            for term in q_terms:
                if term not in freq:
                    continue
                idf = self._idf(term)
                tf = freq[term]
                denom = tf + self.k1 * (1 - self.b + self.b * self.doc_len[i] / (self.avgdl or 1))
                s += idf * (tf * (self.k1 + 1)) / denom
            if s > 0:
                scored.append((self.chunks[i], s))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


# --------------------------------------------------------------------------- #
# Citation engine
# --------------------------------------------------------------------------- #
CITATION_QA_TEMPLATE = (
    "Answer the query using ONLY the numbered sources below. Cite the sources "
    "you use inline with their number in square brackets, e.g. [1]. Every claim "
    "must carry at least one citation. If none of the sources are helpful, say "
    "exactly: 'INSUFFICIENT EVIDENCE' and nothing else.\n\n"
    "{sources}\n"
    "Query: {query}\n"
    "Answer: "
)

ABSTAIN_MARKER = "INSUFFICIENT EVIDENCE"


@dataclass
class Source:
    n: int
    source_id: str
    text: str


@dataclass
class CitedAnswer:
    query: str
    answer: str
    sources: list[Source] = field(default_factory=list)
    abstained: bool = False

    def render(self) -> str:
        lines = [self.answer, ""]
        if self.sources:
            lines.append("Sources:")
            for s in self.sources:
                lines.append(f"  [{s.n}] {s.source_id}")
        return "\n".join(lines)


class CitationEngine:
    def __init__(
        self,
        chunks: list[Chunk],
        backend: LLMBackend | None = None,
        top_k: int = 4,
        min_score: float = 1.0,
    ):
        self.bm25 = BM25(chunks)
        self.backend = backend or NoOpBackend()
        self.top_k = top_k
        self.min_score = min_score  # abstain if best hit scores below this

    def query(self, question: str) -> CitedAnswer:
        hits = self.bm25.score(question, self.top_k)

        # Abstention: nothing retrieved, or nothing above the relevance floor.
        if not hits or hits[0][1] < self.min_score:
            return CitedAnswer(
                query=question,
                answer=ABSTAIN_MARKER + " — no sufficiently relevant source found.",
                sources=[],
                abstained=True,
            )

        sources = [Source(n=i + 1, source_id=c.source_id, text=t)
                   for i, (c, t) in enumerate((c, c.text) for c, _ in hits)]

        block = "\n".join(f"Source {s.n} ({s.source_id}):\n{s.text}\n" for s in sources)
        prompt = CITATION_QA_TEMPLATE.format(sources=block, query=question)
        answer = self.backend.complete(prompt).strip()

        # Only a genuine refusal starts with the marker; the prompt itself
        # mentions the marker in its instructions, so a `in` check would
        # false-positive on any echoed/quoted prompt text.
        abstained = answer.upper().startswith(ABSTAIN_MARKER)
        return CitedAnswer(query=question, answer=answer, sources=sources, abstained=abstained)
