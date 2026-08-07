import pytest

from investigator.evaluation.entailment import (
    CrossEncoderNLIChecker,
    EntailmentLabel,
    LexicalOverlapChecker,
    MarginNLIContradictionChecker,
    MiniCheckSupportChecker,
    default_checker,
    default_contradiction_checker,
    default_support_checker,
)

SOURCE = (
    "An unexpected change in origin AS for a prefix is a strong indicator "
    "of a prefix hijack, a MOAS condition, and warrants RPKI validation."
)


def test_entails_when_claim_vocabulary_overlaps_strongly():
    checker = LexicalOverlapChecker()
    verdict = checker.check("An unexpected origin AS change indicates a prefix hijack (MOAS).", SOURCE)
    assert verdict.label == EntailmentLabel.ENTAILED


def test_not_entailed_when_claim_is_unrelated():
    checker = LexicalOverlapChecker()
    verdict = checker.check("Sourdough bread requires a long fermentation time.", SOURCE)
    assert verdict.label == EntailmentLabel.NOT_ENTAILED


def test_contradicts_on_negation_mismatch():
    checker = LexicalOverlapChecker()
    # Shares plenty of vocabulary with SOURCE, but asserts the opposite --
    # a genuine refutation signal (CONTRADICTS), distinct from
    # test_not_entailed_when_claim_is_unrelated's plain "doesn't address
    # this at all" (NOT_ENTAILED) case above.
    claim = "A change in origin AS for a prefix is not an indicator of a prefix hijack or MOAS."
    verdict = checker.check(claim, SOURCE)
    assert verdict.label == EntailmentLabel.CONTRADICTS


def test_unclear_on_empty_claim_tokens():
    checker = LexicalOverlapChecker()
    verdict = checker.check("the a of", SOURCE)  # all stopwords
    assert verdict.label == EntailmentLabel.UNCLEAR


def test_default_checker_falls_back_to_lexical_without_selection():
    checker = default_checker()
    assert isinstance(checker, LexicalOverlapChecker)


def test_default_checker_selects_cross_encoder_when_requested_and_available():
    pytest.importorskip("sentence_transformers")
    checker = default_checker("cross_encoder")
    assert isinstance(checker, CrossEncoderNLIChecker)


def test_default_checker_falls_back_to_lexical_for_unknown_name():
    checker = default_checker("something_unrecognized")
    assert isinstance(checker, LexicalOverlapChecker)


def test_cross_encoder_checker_real_model():
    pytest.importorskip("sentence_transformers")
    checker = CrossEncoderNLIChecker()
    verdict = checker.check(
        "An unexpected origin AS change indicates a prefix hijack.", SOURCE
    )
    assert verdict.label == EntailmentLabel.ENTAILED

    contradiction = checker.check(
        "An unexpected origin AS change is completely normal and never a hijack signal.", SOURCE
    )
    assert contradiction.label == EntailmentLabel.CONTRADICTS


# --------------------------------------------------------------------------- #
# Phase 3/4 checker split (docs/alignment-plan.md item 3)
# --------------------------------------------------------------------------- #

def test_default_support_checker_falls_back_to_lexical_without_selection():
    checker = default_support_checker()
    assert isinstance(checker, LexicalOverlapChecker)


def test_default_support_checker_selects_minicheck_when_requested_and_available():
    pytest.importorskip("minicheck.minicheck")
    checker = default_support_checker("minicheck")
    assert isinstance(checker, MiniCheckSupportChecker)


def test_default_contradiction_checker_falls_back_to_lexical_without_selection():
    checker = default_contradiction_checker()
    assert isinstance(checker, LexicalOverlapChecker)


def test_default_contradiction_checker_selects_nli_margin_when_requested_and_available():
    pytest.importorskip("transformers")
    checker = default_contradiction_checker("nli_margin")
    assert isinstance(checker, MarginNLIContradictionChecker)


def test_minicheck_support_checker_real_model():
    pytest.importorskip("minicheck.minicheck")
    checker = MiniCheckSupportChecker()

    supported = checker.check(
        "An unexpected origin AS change is a strong indicator of a prefix hijack.", SOURCE
    )
    assert supported.label == EntailmentLabel.ENTAILED

    unsupported = checker.check("Sourdough bread requires a long fermentation time.", SOURCE)
    assert unsupported.label == EntailmentLabel.NOT_ENTAILED

    # Binary by design -- MiniCheck has no CONTRADICTS/UNCLEAR concept, so a
    # flat negation of SOURCE must still land on one of the two labels it
    # actually supports, not silently produce a label outside its contract.
    negated = checker.check(
        "An unexpected origin AS change is never an indicator of a prefix hijack.", SOURCE
    )
    assert negated.label in (EntailmentLabel.ENTAILED, EntailmentLabel.NOT_ENTAILED)


# The exact documented false positive (docs/design.md's Phase 4 section,
# contradiction.py's module docstring): RFC 4271 §9.1.2's AS_PATH
# loop-detection text, flagged CONTRADICTS against a MOAS hypothesis, by
# both the lexical checker and the original nli-deberta-v3-xsmall cross-
# encoder. Real text pulled verbatim from the loaded corpus and the real
# MOAS analyzer's statement format, not paraphrased.
_AS_PATH_LOOP_SECTION = (
    "If the AS_PATH attribute of a BGP route contains an AS loop, the BGP route "
    "should be excluded from the Phase 2 decision function.  AS loop detection "
    "is done by scanning the full AS path (as specified in the AS_PATH "
    "attribute), and checking that the autonomous system number of the local "
    "system does not appear in the AS path.  Operations of a BGP speaker that "
    "is configured to accept routes with its own autonomous system number in "
    "the AS path are outside the scope of this document. It is critical that "
    "BGP speakers within an AS do not make conflicting decisions regarding "
    "route selection that would cause forwarding loops to occur."
)
_MOAS_CLAIM = "2 origin ASNs observed for a single prefix."


def test_margin_nli_contradiction_checker_fixes_the_documented_as_path_false_positive():
    pytest.importorskip("transformers")
    checker = MarginNLIContradictionChecker()
    verdict = checker.check(_MOAS_CLAIM, _AS_PATH_LOOP_SECTION)
    # The documented failure was CONTRADICTS; a genuinely unrelated passage
    # should be UNCLEAR (neutral), not a confident refutation.
    assert verdict.label == EntailmentLabel.UNCLEAR


def test_margin_nli_contradiction_checker_still_detects_genuine_contradiction():
    pytest.importorskip("transformers")
    checker = MarginNLIContradictionChecker()
    verdict = checker.check(
        "AS loop detection is never performed by scanning the AS_PATH.",
        _AS_PATH_LOOP_SECTION,
    )
    assert verdict.label == EntailmentLabel.CONTRADICTS
