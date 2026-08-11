"""Entailment checking: does a source's text actually support a claim.

One `EntailmentChecker` interface, four implementations, mirroring
`investigator/llm.py`'s NoOp/LiteLLM split for the dependency-free-vs-real
pattern -- plus a Phase-3-vs-Phase-4 split within the "real" tier, added
after a documented false positive traced to one checker doing two different
jobs (see `MarginNLIContradictionChecker`'s docstring):

* `LexicalOverlapChecker` (default) -- dependency-free, offline, deterministic.
  An approximation, not real natural-language inference: it measures token
  overlap plus a crude negation-mismatch check. Same honesty standard as
  choosing BM25 over dense embeddings for retrieval -- documented as a
  heuristic, not asserted as equivalent to a real entailment model.
* `CrossEncoderNLIChecker` (optional, real, general-purpose) -- a HuggingFace
  MNLI cross-encoder. Guarded import exactly like `LiteLLMBackend`: this
  module imports fine without `transformers`/`torch` installed; only
  instantiating this specific checker requires them.
* `MiniCheckSupportChecker` (optional, real, Phase 3) -- purpose-trained
  claim-vs-document grounding, binary by design. Use via
  `default_support_checker()`.
* `MarginNLIContradictionChecker` (optional, real, Phase 4) -- genuine 3-way
  NLI (entailment/neutral/contradiction) with a margin requirement, for
  telling "refutes" apart from "doesn't address it." Use via
  `default_contradiction_checker()`.
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
    NOT_ENTAILED = "not_entailed"    # source doesn't address the claim at all
    CONTRADICTS = "contradicts"      # source actively refutes the claim
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
            # otherwise mistake for entailment. This is a genuine refutation
            # signal (Phase 4 relies on it), distinct from the plain
            # low-overlap "doesn't even address this" case below.
            return EntailmentVerdict(EntailmentLabel.CONTRADICTS, overlap, self.name())
        if overlap >= _HIGH_OVERLAP:
            return EntailmentVerdict(EntailmentLabel.ENTAILED, overlap, self.name())
        if overlap < _LOW_OVERLAP:
            return EntailmentVerdict(EntailmentLabel.NOT_ENTAILED, overlap, self.name())
        return EntailmentVerdict(EntailmentLabel.UNCLEAR, overlap, self.name())


class CrossEncoderNLIChecker:
    """Real MNLI entailment via a HuggingFace cross-encoder model.
    Deliberately not Bespoke-MiniCheck-7B -- that needs a GPU or patience via
    Ollama (the source build plan flags this as a real risk); this uses a
    CPU-friendly model instead, at the cost of being a lighter-weight NLI
    model than the one originally referenced.

    Model size was tuned empirically, not guessed: `nli-deberta-v3-xsmall`
    (~22M params, the original choice here, picked for speed) mislabeled a
    topically-unrelated RFC passage as CONTRADICTS a MOAS claim -- a
    documented NLI failure mode (models over-relying on negation-word
    *presence* as a shortcut cue rather than reasoning about what's negated).
    Tested `-base` (~184M) and `-large` (~435M) against the same case: both
    correctly returned UNCLEAR, and both still correctly returned
    ENTAILED/CONTRADICTS on the original clear-cut test cases -- i.e. `-base`
    isn't just trading this false positive for a different failure, it's
    genuinely more accurate. `-base` is the default; `-large` is slower with
    no observed accuracy gain over `-base` on the cases checked so far."""

    DEFAULT_MODEL = "cross-encoder/nli-deberta-v3-base"

    def __init__(self, model_name: str | None = None):
        try:
            from sentence_transformers import CrossEncoder
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
            "contradiction": EntailmentLabel.CONTRADICTS,
            "neutral": EntailmentLabel.UNCLEAR,
        }[label_name]
        return EntailmentVerdict(label, score, self.name())


class MiniCheckSupportChecker:
    """Real, purpose-built claim-vs-document grounding via MiniCheck (Tang
    et al., EMNLP 2024, arXiv:2404.10774) -- `lytang/MiniCheck-Flan-T5-Large`,
    MIT licensed, 0.8B params, CPU-feasible, reported at GPT-4 parity for
    fact-checking under 1B params. Deliberately not `Bespoke-MiniCheck-7B`
    (the source plan's original pick): that checkpoint is CC BY-NC 4.0 --
    non-commercial, wrong as the default dependency path of an open-source
    portfolio tool -- and needs a GPU/vLLM for usable throughput, a risk the
    source plan itself flagged for the 7B model. Same authors, same paper,
    same `minicheck` package. NOTE the package name collides with an
    unrelated formal-verification tool on PyPI -- install from GitHub:
    `pip install "minicheck @ git+https://github.com/Liyan06/MiniCheck.git@main"`.

    Binary by design -- MiniCheck answers "does this document support this
    claim," full stop, no contradiction/neutral distinction. That's the
    right shape for Phase 3 (citation correctness: does the *cited* source
    actually say what the claim says) and the wrong shape for Phase 4
    (needs to tell "refutes" apart from "doesn't address it at all") -- see
    `MarginNLIContradictionChecker` for that job. Only ever returns
    `ENTAILED` or `NOT_ENTAILED`; never `CONTRADICTS`/`UNCLEAR`, documented
    honestly rather than faking a distinction the model can't make."""

    DEFAULT_MODEL = "flan-t5-large"

    def __init__(self, model_name: str | None = None, cache_dir: str = "./.minicheck_cache"):
        try:
            from minicheck.minicheck import MiniCheck
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "minicheck is not installed, or the wrong package of that name is "
                "(PyPI's 'minicheck' is an unrelated formal-verification tool). "
                'Install with `pip install "minicheck @ '
                'git+https://github.com/Liyan06/MiniCheck.git@main"`, or use the '
                "default LexicalOverlapChecker."
            ) from exc
        self.model_name = model_name or self.DEFAULT_MODEL
        self._model = MiniCheck(model_name=self.model_name, cache_dir=cache_dir)

    def name(self) -> str:
        return f"minicheck:{self.model_name}"

    def check(self, claim: str, source_text: str) -> EntailmentVerdict:
        pred_label, raw_prob, _, _ = self._model.score(docs=[source_text], claims=[claim])
        label = EntailmentLabel.ENTAILED if pred_label[0] == 1 else EntailmentLabel.NOT_ENTAILED
        return EntailmentVerdict(label, float(raw_prob[0]), self.name())


class MarginNLIContradictionChecker:
    """Genuine 3-way NLI for Phase 4 (does this passage *refute* this
    hypothesis, as opposed to simply not addressing it) --
    `MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli` (435M, MIT),
    trained on MNLI + FEVER-NLI + ANLI + LingNLI + WANLI. ANLI in particular
    is adversarially collected specifically to break the lexical-overlap and
    negation-shortcut heuristics behind this project's documented false
    positive: RFC 4271 §9.1.2's AS_PATH loop-detection text flagged as
    `CONTRADICTS`-ing an unrelated MOAS claim, apparently because both texts
    contain "not" (see `contradiction.py`'s module docstring for the full
    history, including that `cross-encoder/nli-deberta-v3-base` already
    fixed *this specific* case -- this model targets the case that one
    didn't: RouteLeak vs. the same RFC section, a genuinely closer,
    borderline pairing). **Re-tested directly against the original MOAS
    case, not just theorized to be better:** this model scores it 99.5%
    NEUTRAL, 0.4% CONTRADICTS.

    Requires CONTRADICTION to beat *both* ENTAILMENT and NEUTRAL by
    `margin` before returning `CONTRADICTS` -- being the argmax isn't
    enough on its own; a close 3-way call is exactly the "genuinely
    borderline" shape documented in `contradiction.py`, and should read as
    `UNCLEAR`, not a confident refutation."""

    DEFAULT_MODEL = "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli"
    DEFAULT_MARGIN = 0.1

    def __init__(self, model_name: str | None = None, margin: float | None = None):
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "transformers/torch are not installed. `pip install -e "
                "\".[nli]\"` or use the default LexicalOverlapChecker."
            ) from exc
        self.model_name = model_name or self.DEFAULT_MODEL
        self.margin = self.DEFAULT_MARGIN if margin is None else margin
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
        self._model.eval()
        # This checkpoint's label order is a property of its own config, not
        # assumed from the general nli-deberta-v3 family (CrossEncoderNLIChecker
        # above uses a different order for a different checkpoint) -- read
        # from the model's own id2label, verified empirically to be
        # {0: entailment, 1: neutral, 2: contradiction}.
        self._id2label = {i: label.lower() for i, label in self._model.config.id2label.items()}

    def name(self) -> str:
        return f"nli_margin:{self.model_name}"

    def check(self, claim: str, source_text: str) -> EntailmentVerdict:
        inputs = self._tokenizer(source_text, claim, truncation=True, return_tensors="pt")
        with self._torch.no_grad():
            logits = self._model(**inputs).logits
        probs = self._torch.softmax(logits, dim=-1)[0]
        scores = {self._id2label[i]: float(p) for i, p in enumerate(probs)}
        entailment, neutral, contradiction = scores["entailment"], scores["neutral"], scores["contradiction"]

        if contradiction > entailment + self.margin and contradiction > neutral + self.margin:
            return EntailmentVerdict(EntailmentLabel.CONTRADICTS, contradiction, self.name())
        if entailment >= neutral and entailment >= contradiction:
            return EntailmentVerdict(EntailmentLabel.ENTAILED, entailment, self.name())
        return EntailmentVerdict(EntailmentLabel.UNCLEAR, neutral, self.name())


def default_checker(checker_name: str | None = None) -> EntailmentChecker:
    """The CITATION_CHECKER env var takes priority when set -- a deliberate
    override for one run, without editing toolsets.toml (mirrors
    `investigator.llm.default_backend()`'s INVESTIGATOR_MODEL pattern).
    Otherwise falls back to `checker_name` (typically `[citation_eval].checker`
    from toolsets.toml), then to the lexical checker if neither selects the
    cross-encoder or its dependency isn't importable.

    Bug fixed here, not just a hypothetical: toolsets.toml's default manifest
    hardcodes `checker = "lexical"`, so with the env var as a mere fallback
    (the original design), CITATION_CHECKER could never actually take effect
    through the CLI -- the TOML value is always present and always won."""
    name = os.environ.get("CITATION_CHECKER") or checker_name
    if name == "cross_encoder":
        try:
            return CrossEncoderNLIChecker()
        except RuntimeError:
            pass
    return LexicalOverlapChecker()


def default_support_checker(checker_name: str | None = None) -> EntailmentChecker:
    """Phase 3 (citation correctness, `investigator/evaluation/scorer.py`):
    does the cited source support the claim -- a binary question, so
    `MiniCheckSupportChecker` is in scope here alongside the general-purpose
    options. `CITATION_SUPPORT_CHECKER` takes priority when set, then the
    generic `CITATION_CHECKER` (back-compat with the single-checker config
    this project shipped with before Phase 3 and Phase 4 were split to use
    different checkers -- see `MarginNLIContradictionChecker`'s docstring
    for why one checker doing both jobs produced a documented false
    positive), then `checker_name` (typically
    `[citation_eval].support_checker` from toolsets.toml), then lexical if
    nothing selects a real checker or its dependency isn't importable."""
    name = os.environ.get("CITATION_SUPPORT_CHECKER") or os.environ.get("CITATION_CHECKER") or checker_name
    if name == "minicheck":
        try:
            return MiniCheckSupportChecker()
        except RuntimeError:
            pass
    if name == "cross_encoder":
        try:
            return CrossEncoderNLIChecker()
        except RuntimeError:
            pass
    return LexicalOverlapChecker()


def default_contradiction_checker(checker_name: str | None = None) -> EntailmentChecker:
    """Phase 4 (adversarial retrieval / ACH, `investigator/retrieval/contradiction.py`):
    does this passage refute the hypothesis -- needs a genuine 3-way
    ENTAILED/UNCLEAR/CONTRADICTS distinction, so `MarginNLIContradictionChecker`
    is in scope here. Same override pattern and back-compat rationale as
    `default_support_checker()`, with `CITATION_CONTRADICTION_CHECKER` as
    the job-specific env var and `[citation_eval].contradiction_checker` as
    the job-specific toolsets.toml key."""
    name = os.environ.get("CITATION_CONTRADICTION_CHECKER") or os.environ.get("CITATION_CHECKER") or checker_name
    if name == "nli_margin":
        try:
            return MarginNLIContradictionChecker()
        except RuntimeError:
            pass
    if name == "cross_encoder":
        try:
            return CrossEncoderNLIChecker()
        except RuntimeError:
            pass
    return LexicalOverlapChecker()
