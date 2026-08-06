import pytest

from investigator.evaluation.entailment import (
    CrossEncoderNLIChecker,
    EntailmentLabel,
    LexicalOverlapChecker,
    default_checker,
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
