"""Entailment checking: does a source's text actually support a claim.

Two backends behind one interface, mirroring `investigator/llm.py`'s
NoOp/LiteLLM split:

* `LexicalOverlapChecker` (default) -- dependency-free, offline, deterministic.
  An approximation, not real natural-language inference: it measures token
  overlap plus a crude negation-mismatch check. Same honesty standard as
  choosing BM25 over dense embeddings for retrieval -- documented as a
  heuristic, not asserted as equivalent to a real entailment model.
* `CrossEncoderNLIChecker` (optional, real) -- a small HuggingFace MNLI
  cross-encoder. Guarded import exactly like `LiteLLMBackend`: this module
  imports fine without `transformers`/`torch` installed; only instantiating
  this specific checker requires them.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from investigator.retrieval.citations import STOPWORDS
from investigator.retrieval.corpus import _tokenize

_NEGATION_RE = re.compile(r"\b(not|no|never|cannot|n't)\b", re.IGNORECASE)

# Token-overlap thresholds for the lexical heuristic. High: the claim's own
# vocabulary is substantially present in the source -> plausibly entailed.
# Low: the source barely mentions what the claim is even about -> not
# entailed. Between the two: genuinely unclear from lexical evidence alone.
_HIGH_OVERLAP = 0.5
_LOW_OVERLAP = 0.15


class EntailmentLabel(str, Enum):
    ENTAILED = "entailed"
    NOT_ENTAILED = "not_entailed"
    UNCLEAR = "unclear"


@dataclass
class EntailmentVerdict:
    label: EntailmentLabel
    score: float
    checker_name: str


@runtime_checkable
class EntailmentChecker(Protocol):
    def check(self, claim: str, source_text: str) -> EntailmentVerdict: ...
    def name(self) -> str: ...


class LexicalOverlapChecker:
    """Token-overlap ratio + negation-mismatch. Not real NLI -- a
    dependency-free proxy, documented as such wherever it's used."""

    def name(self) -> str:
        return "lexical_overlap"

    def check(self, claim: str, source_text: str) -> EntailmentVerdict:
        claim_tokens = {t for t in _tokenize(claim) if t not in STOPWORDS}
        source_tokens = {t for t in _tokenize(source_text) if t not in STOPWORDS}

        if not claim_tokens:
            return EntailmentVerdict(EntailmentLabel.UNCLEAR, 0.0, self.name())

        overlap = len(claim_tokens & source_tokens) / len(claim_tokens)

        claim_negated = bool(_NEGATION_RE.search(claim))
        source_negated = bool(_NEGATION_RE.search(source_text))
        negation_mismatch = claim_negated != source_negated

        if negation_mismatch and overlap >= _LOW_OVERLAP:
            # Substantial shared vocabulary, but one asserts and the other
            # negates it -- the classic case lexical overlap alone would
            # otherwise mistake for entailment.
            return EntailmentVerdict(EntailmentLabel.NOT_ENTAILED, overlap, self.name())
        if overlap >= _HIGH_OVERLAP:
            return EntailmentVerdict(EntailmentLabel.ENTAILED, overlap, self.name())
        if overlap < _LOW_OVERLAP:
            return EntailmentVerdict(EntailmentLabel.NOT_ENTAILED, overlap, self.name())
        return EntailmentVerdict(EntailmentLabel.UNCLEAR, overlap, self.name())


class CrossEncoderNLIChecker:
    """Real MNLI entailment via a small HuggingFace cross-encoder model.
    Deliberately not Bespoke-MiniCheck-7B -- that needs a GPU or patience via
    Ollama (the source build plan flags this as a real risk); this uses a
    CPU-friendly model instead, at the cost of being a lighter-weight NLI
    model than the one originally referenced."""

    DEFAULT_MODEL = "cross-encoder/nli-deberta-v3-xsmall"

    def __init__(self, model_name: str | None = None):
        try:
            from sentence_transformers import CrossEncoder  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "sentence-transformers/transformers/torch are not installed. "
                "`pip install sentence-transformers` or use the default "
                "LexicalOverlapChecker."
            ) from exc
        self.model_name = model_name or self.DEFAULT_MODEL
        self._model = CrossEncoder(self.model_name)
        # This model's label order (contradiction/entailment/neutral) is a
        # property of the specific checkpoint -- cross-encoder/nli-deberta-v3
        # models use this order; verify against the model card if swapped.
        self._labels = ("contradiction", "entailment", "neutral")

    def name(self) -> str:
        return f"cross_encoder:{self.model_name}"

    def check(self, claim: str, source_text: str) -> EntailmentVerdict:
        scores = self._model.predict([(source_text, claim)])[0]
        label_idx = int(scores.argmax())
        label_name = self._labels[label_idx]
        score = float(scores[label_idx])
        label = {
            "entailment": EntailmentLabel.ENTAILED,
            "contradiction": EntailmentLabel.NOT_ENTAILED,
            "neutral": EntailmentLabel.UNCLEAR,
        }[label_name]
        return EntailmentVerdict(label, score, self.name())


def default_checker(checker_name: str | None = None) -> EntailmentChecker:
    """`checker_name` (typically `[citation_eval].checker` from
    toolsets.toml) takes priority; falls back to the CITATION_CHECKER env
    var (mirrors `investigator.llm.default_backend()`'s INVESTIGATOR_MODEL
    pattern), then to the lexical checker if neither selects the
    cross-encoder or its dependency isn't importable."""
    name = checker_name or os.environ.get("CITATION_CHECKER")
    if name == "cross_encoder":
        try:
            return CrossEncoderNLIChecker()
        except RuntimeError:
            pass
    return LexicalOverlapChecker()
