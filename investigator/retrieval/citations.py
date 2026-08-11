"""BM25 retrieval + a CitationEngine.

The CitationEngine mirrors the semantics of LlamaIndex's CitationQueryEngine:
numbered sources are shown to the model, it is asked to answer *solely* from
them and cite inline with [n], and — critically — to abstain if none of the
sources are helpful. Retrieval here is a small, dependency-free BM25 so the
whole thing runs offline; swap in hybrid BM25+dense (LlamaIndex/Qdrant) for
production without changing the engine's interface.
"""
from __future__ import annotations

import contextlib
import math
from collections import Counter
from dataclasses import dataclass, field

from investigator.llm import LLMBackend, NoOpBackend
from investigator.retrieval.corpus import Chunk, _tokenize

# Small stopword set. Without this, BM25 matches on "the/is/for/a" which are
# common in RFC prose, defeating the abstention floor on off-topic queries.
STOPWORDS = frozenset(
    ["a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "into", "is", "it", "of", "on", "or", "that", "the", "to", "was", "what", "when", "where", "which", "who", "why", "with", "do", "does", "did", "i", "you", "we", "they", "this", "these", "those", "there", "here", "best", "most", "can", "could", "should", "would"]
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

    def max_possible_score(self, query: str) -> float:
        """Upper bound on any single chunk's score for this query: each
        distinct query term's BM25 contribution saturates toward
        idf(term) * (k1 + 1) as tf grows / doc length shrinks. Only terms
        that actually appear somewhere in the corpus count (a term absent
        from every chunk can never be matched, so including it would only
        inflate the ceiling with a contribution nothing can ever earn).

        This ceiling scales with corpus size the same way real per-term
        scores do, since both come from the same idf() -- see
        `CitationEngine`'s `min_score_fraction` for why that makes the
        *ratio* between an actual top score and this ceiling a scale-
        invariant relevance signal, unlike a fixed absolute score floor."""
        q_terms = {t for t in _tokenize(query) if t not in STOPWORDS}
        return sum(self._idf(t) * (self.k1 + 1) for t in q_terms if t in self.df)

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
# Dense (embedding) retrieval -- optional, hybrid with BM25
# --------------------------------------------------------------------------- #
class DenseIndex:
    """Semantic retrieval via sentence embeddings, layered on top of BM25 for
    hybrid search (docs/alignment-plan.md item 7). `sentence-transformers` is
    already an optional dependency (entailment.py's CrossEncoderNLIChecker),
    so this adds no new toolchain -- opt-in, same pattern as everything else
    real in this project.

    Motivating failure, measured not assumed: BM25 is lexical, and RFC prose
    is full of near-synonyms an analyzer's own hypothesis wording doesn't
    share. `WithdrawalStorm`'s real statement ("Total 403 withdrawals; peak
    burst 63 in window.") retrieves BM25 matches on the bare digits "403"/
    "63" as if they were meaningful terms (RFC 2439's numeric tables, RFC
    4272's unrelated TCP-RST section) instead of the actual concept. Worse,
    `RouteLeak`'s real statement ("...transit AS(es) appeared mid-window
    across peers, origin unchanged") returns *zero* BM25 hits -- it abstains
    outright -- despite RFC 7908 having an entire route-leak type taxonomy;
    the analyzer's phrasing just doesn't share vocabulary with the RFC's.
    Dense retrieval on the same two queries surfaces RFC 2439 (BGP Route
    Flap Damping -- the actually-relevant RFC for "withdrawal storm") and
    RFC 7908's route-leak type definitions, neither meaningfully found by
    BM25 alone.

    `BAAI/bge-small-en-v1.5` (33M params, CPU-fast): a small, well-
    established general embedding model, not tuned for BGP/RFC text
    specifically -- an approximation, documented as such, same honesty
    standard as the lexical BM25 default. BGE's asymmetric retrieval design
    expects queries (not passages) prefixed with its documented instruction
    string; skipping it is a real, silent quality regression, not a
    micro-optimization -- verified directly, not assumed: with the prefix,
    RFC 2439 (flap damping) surfaces in the WithdrawalStorm query's top 3;
    without it, it doesn't appear at all."""

    DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
    QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

    def __init__(self, chunks: list[Chunk], model_name: str | None = None):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "sentence-transformers is not installed. `pip install -e "
                "\".[nli]\"` or use BM25-only retrieval (the default)."
            ) from exc
        self.chunks = chunks
        self.model_name = model_name or self.DEFAULT_MODEL
        self._model = SentenceTransformer(self.model_name)
        self._embeddings = (
            self._model.encode([c.text for c in chunks], normalize_embeddings=True, show_progress_bar=False)
            if chunks else None
        )

    def name(self) -> str:
        return f"dense:{self.model_name}"

    def score(self, query: str, top_k: int = 4) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        q_emb = self._model.encode([self.QUERY_INSTRUCTION + query], normalize_embeddings=True)[0]
        sims = self._embeddings @ q_emb  # cosine similarity, since both sides are L2-normalized
        ranked_idx = sims.argsort()[::-1][:top_k]
        return [(self.chunks[i], float(sims[i])) for i in ranked_idx]


def _reciprocal_rank_fusion(
    ranked_lists: list[list[Chunk]], top_k: int, k: int = 60
) -> list[tuple[Chunk, float]]:
    """Combines multiple ranked candidate lists (e.g. BM25's and DenseIndex's)
    into one ranking, by rank position rather than raw score -- BM25 scores
    and cosine similarities live on incomparable scales, so summing or
    averaging them directly would silently let whichever retriever's numbers
    happen to run larger dominate. RRF (Cormack et al., 2009) sidesteps that
    entirely: score(chunk) = sum over lists of 1/(k + rank_in_that_list).
    `k=60` is the standard constant from the original paper and widely reused
    (Elasticsearch, Azure AI Search) unchanged -- not tuned here, since its
    job is just to flatten how much rank 1 dominates rank 2, not to encode
    any BGP/RFC-specific judgment."""
    scores: dict[Chunk, float] = {}
    for ranked in ranked_lists:
        for rank, chunk in enumerate(ranked, start=1):
            scores[chunk] = scores.get(chunk, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_k]


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

# Default for production CitationEngine construction (investigator/engine.py,
# investigator/evaluate.py). Calibrated empirically against the real 16-RFC
# corpus (docs/alignment-plan.md item 4b), not guessed -- and the first
# number tried (0.2) was wrong: on real multi-term incident questions
# against real RFC text, ratio-to-ceiling does NOT cleanly separate on-topic
# from off-topic the way it did on the synthetic single/double-term test
# case. The flagship MOAS query ("why is a prefix announced by two distinct
# origin ASNs...") scored ratio 0.161 -- genuinely on-topic, but *below* an
# unrelated "kubernetes ingress controller" query's 0.219. A multi-term
# on-topic query has a larger ceiling (more distinct terms each contribute)
# but rarely saturates every term, while a short off-topic query can spike
# on one coincidentally-rare corpus term -- the same lexical-coincidence
# weakness BM25 already has, just visible here too.
#
# So this constant is deliberately conservative (comfortably below every
# on-topic ratio observed, ~0.16-0.37) and MUST NOT be read as "0.1 = the
# relevance bar." Its actual, narrower job: stop a fixed absolute min_score
# from drifting to look easier to clear purely because the corpus grew (the
# bug this item fixes -- see max_possible_score's docstring). It is not, and
# isn't meant to be, a general relevance classifier. CORRECTION once item 7
# (hybrid dense retrieval) was actually implemented, not just deferred: dense
# cosine similarity has the *same* separation weakness, not a fix for it --
# see DEFAULT_MIN_DENSE_SCORE below, where the identical "kubernetes ingress
# controller" query scores *higher* than the real WithdrawalStorm query too.
# BM25's lexical-coincidence false-positive rate on adjacent-technical-domain
# queries turns out to be shared with dense retrieval on this corpus, not a
# BM25-specific gap -- a genuinely different, more pessimistic conclusion
# than this comment originally predicted.
DEFAULT_MIN_SCORE_FRACTION = 0.1

# Default for production hybrid retrieval when enabled ([rfc_search].retrieval
# = "hybrid" in toolsets.toml). Calibrated the same way as
# DEFAULT_MIN_SCORE_FRACTION -- against real queries, not guessed -- and hit
# the *same* separation problem: cosine similarity never naturally "finds
# nothing" the way BM25 does (embeddings always have *some* similarity to
# *something*), so without a floor here hybrid retrieval stops abstaining on
# off-topic queries entirely, a direct threat to this project's whole
# abstain-rather-than-guess thesis. Measured against the real corpus: every
# real analyzer hypothesis template scores >= 0.63 (WithdrawalStorm 0.631,
# RouteLeak 0.659, ASPathLoop 0.710, MOAS 0.740); genuinely off-topic queries
# (bread, weather, cooking, movies) score <= 0.563. 0.6 sits in that gap.
# One query does NOT separate cleanly, reported rather than hidden: "what is
# the best way to configure a kubernetes ingress controller" scores 0.642 --
# *above* WithdrawalStorm's on-topic score -- for the same reason as
# DEFAULT_MIN_SCORE_FRACTION's kubernetes case: technical-register vocabulary
# overlap ("configure," "controller," routing-adjacent phrasing) reads as
# similar to BGP RFC prose even when the topic is unrelated. Dense retrieval
# does not fix this failure mode; it reproduces it.
DEFAULT_MIN_DENSE_SCORE = 0.6


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
    trace: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [self.answer, ""]
        if self.sources:
            lines.append("Sources:")
            for s in self.sources:
                lines.append(f"  [{s.n}] {s.source_id}")
        if self.trace:
            lines.append("")
            lines.append("Investigation trace:")
            for step in self.trace:
                lines.append(f"  - {step}")
        return "\n".join(lines)


class CitationEngine:
    def __init__(
        self,
        chunks: list[Chunk],
        backend: LLMBackend | None = None,
        top_k: int = 4,
        min_score: float = 1.0,
        min_score_fraction: float | None = None,
        dense_index: DenseIndex | None = None,
        min_dense_score: float | None = None,
    ):
        self.bm25 = BM25(chunks)
        self.backend = backend or NoOpBackend()
        self.top_k = top_k
        self.min_score = min_score  # abstain if best hit scores below this
        # Opt-in, additive on top of min_score (not a replacement -- every
        # existing caller that passes an explicit min_score and leaves this
        # unset keeps today's exact behavior; small hand-built test corpora
        # never need it). When set, ALSO requires the top hit to clear this
        # fraction of BM25.max_possible_score(query) for that query. A fixed
        # absolute min_score is corpus-size dependent: idf(term) rises with
        # corpus size N for a term whose document frequency stays flat, so a
        # threshold calibrated against a small corpus gets easier to clear,
        # for reasons unrelated to relevance, as the corpus grows (see
        # docs/alignment-plan.md item 4b). max_possible_score scales with N
        # the same way real per-term scores do -- both come from the same
        # idf() -- so the *ratio* between an actual top score and that
        # ceiling stays roughly constant regardless of corpus size.
        self.min_score_fraction = min_score_fraction
        # Opt-in hybrid retrieval (docs/alignment-plan.md item 7). None (the
        # default) keeps every existing caller BM25-only, byte-for-byte.
        # When set, dense retrieval widens the candidate pool BM25 alone
        # would return -- crucially including queries BM25 abstains on
        # outright (see DenseIndex's docstring for a real, measured case) --
        # and the two candidate lists are combined via reciprocal rank
        # fusion rather than BM25 alone deciding the final ranking.
        self.dense_index = dense_index
        # Cosine-similarity floor for dense's *own* abstention contribution.
        # Unlike BM25 (zero shared terms -> zero score -> naturally "found
        # nothing"), embeddings always have *some* similarity to *something*,
        # so dense retrieval has no free abstention signal -- this floor is
        # what gives it one. None means dense never independently overrides
        # a BM25 abstention (still fuses into ranking when BM25 does pass).
        self.min_dense_score = min_dense_score

    def retrieve_sources(self, query: str) -> list[Source]:
        """Pure retrieval: hits -> numbered Sources, no LLM call. Returns []
        if nothing clears the relevance floor. This is the reusable piece
        `investigator.agent.AgentLoop` calls as its `search_rfcs` tool; `query()`
        below is unchanged and just uses it for the original single-shot path."""
        wide_k = max(self.top_k * 4, 15)
        bm25_hits = self.bm25.score(query, wide_k)
        bm25_floor = self.min_score
        if self.min_score_fraction is not None:
            ceiling = self.bm25.max_possible_score(query)
            bm25_floor = max(bm25_floor, self.min_score_fraction * ceiling)
        bm25_passes = bool(bm25_hits) and bm25_hits[0][1] >= bm25_floor

        if self.dense_index is None:
            if not bm25_passes:
                return []
            hits = bm25_hits[: self.top_k]
            return [Source(n=i + 1, source_id=c.source_id, text=c.text) for i, (c, _) in enumerate(hits)]

        dense_hits = self.dense_index.score(query, wide_k)
        dense_passes = bool(dense_hits) and (
            self.min_dense_score is None or dense_hits[0][1] >= self.min_dense_score
        )
        if not bm25_passes and not dense_passes:
            return []

        ranked = _reciprocal_rank_fusion(
            [[c for c, _ in bm25_hits], [c for c, _ in dense_hits]], top_k=self.top_k
        )
        return [Source(n=i + 1, source_id=c.source_id, text=c.text) for i, (c, _) in enumerate(ranked)]

    def query(self, question: str) -> CitedAnswer:
        sources = self.retrieve_sources(question)

        # Abstention: nothing retrieved, or nothing above the relevance floor.
        if not sources:
            return CitedAnswer(
                query=question,
                answer=ABSTAIN_MARKER + " — no sufficiently relevant source found.",
                sources=[],
                abstained=True,
            )

        block = "\n".join(f"Source {s.n} ({s.source_id}):\n{s.text}\n" for s in sources)
        prompt = CITATION_QA_TEMPLATE.format(sources=block, query=question)
        answer = self.backend.complete(prompt).strip()

        # Only a genuine refusal starts with the marker; the prompt itself
        # mentions the marker in its instructions, so a `in` check would
        # false-positive on any echoed/quoted prompt text.
        abstained = answer.upper().startswith(ABSTAIN_MARKER)
        return CitedAnswer(query=question, answer=answer, sources=sources, abstained=abstained)


def build_citation_engine(
    chunks: list[Chunk], rfc_search_config: dict, backend: LLMBackend | None = None
) -> CitationEngine:
    """Shared construction path for investigator/engine.py and
    investigator/evaluate.py: builds a CitationEngine from an `[rfc_search]`
    toolsets.toml config dict, enabling hybrid retrieval when
    `[rfc_search].retrieval = "hybrid"` (docs/alignment-plan.md item 7).
    Falls back to BM25-only if the dense dependency isn't installed --
    same guarded-fallback pattern as the EntailmentChecker family."""
    dense_index = None
    if rfc_search_config.get("retrieval") == "hybrid":
        with contextlib.suppress(RuntimeError):
            dense_index = DenseIndex(chunks)
    return CitationEngine(
        chunks,
        backend=backend,
        min_score_fraction=DEFAULT_MIN_SCORE_FRACTION,
        dense_index=dense_index,
        min_dense_score=DEFAULT_MIN_DENSE_SCORE if dense_index is not None else None,
    )
