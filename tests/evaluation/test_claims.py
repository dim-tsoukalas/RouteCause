from investigator.evaluation.claims import extract_claims


def test_single_sentence_single_citation():
    claims = extract_claims("MOAS indicates a hijack [1].")
    assert len(claims) == 1
    assert claims[0].cited_source_ns == (1,)
    assert "MOAS indicates a hijack" in claims[0].text


def test_multiple_sentences_split_correctly():
    claims = extract_claims(
        "The origin changed unexpectedly [1]. This is consistent with a hijack [2]."
    )
    assert len(claims) == 2
    assert claims[0].cited_source_ns == (1,)
    assert "origin changed" in claims[0].text
    assert claims[1].cited_source_ns == (2,)
    assert "consistent with a hijack" in claims[1].text


def test_multiple_citations_on_one_claim():
    claims = extract_claims("Both sources agree on this point [1][2].")
    assert len(claims) == 1
    assert claims[0].cited_source_ns == (1, 2)


def test_uncited_claim_has_empty_citation_tuple():
    claims = extract_claims("This sentence cites nothing at all.")
    assert len(claims) == 1
    assert claims[0].cited_source_ns == ()


def test_empty_answer_produces_no_claims():
    assert extract_claims("") == []
    assert extract_claims("   ") == []


def test_citation_only_text_produces_no_claim():
    # Degenerate input: nothing but a citation marker, no real claim text.
    assert extract_claims("[1]") == []


def test_trailing_citation_with_no_following_sentence_attaches_to_prior_claim():
    # No uppercase letter follows the final "[2]", so it isn't split into
    # its own chunk -- it's absorbed as a second citation on the one claim.
    claims = extract_claims("Real claim here [1]. [2]")
    assert len(claims) == 1
    assert claims[0].cited_source_ns == (1, 2)
