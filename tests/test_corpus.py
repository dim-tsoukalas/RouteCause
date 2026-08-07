from investigator.retrieval.corpus import _clean_rfc_text, _SECTION_RE, load_corpus

# A synthetic but structurally real IETF-shaped RFC: form-feed page breaks,
# running header/footer pairs, a Status-of-Memo/Copyright preamble, a Table
# of Contents with dot-leader page numbers, a numbered body section with an
# indented ordered list (the TOC-entry-vs-real-header ambiguity that broke
# the old _SECTION_RE), and a References-onward tail that should be dropped.
_FAKE_RFC = """\
Network Working Group                                        A. Author
Request for Comments: 9999                          Standards Track

                       A Fake Protocol For Testing

Status of This Memo

   This document specifies an Internet standards track protocol.

Copyright Notice

   Copyright (C) The Internet Society (2026).

Table of Contents

   1. Introduction ..................................................2
      1.1. Scope .....................................................2
   2. Hijack Considerations ..........................................3

1.  Introduction

   This document is a fake RFC used only for testing the corpus loader.

   Ordered steps to validate a route:
   1. Check the origin AS.
   2. Check the AS_PATH for loops.
\x0c
Author                        Standards Track                  [Page 1]

RFC 9999                    Fake Protocol                  January 2026


1.1.  Scope

   This section is in scope for the test.

2.  Hijack Considerations

   An unexpected change in origin AS for a prefix is a strong indicator
   of a prefix hijack or misconfiguration.

References

   [RFC0001] Someone, "An Old RFC", RFC 1, January 1970.

Author's Address

   A. Author
   EMail: author@example.com


Full Copyright Statement

   Copyright (C) The Internet Society (2026). All Rights Reserved.
"""


def test_section_re_ignores_indented_toc_and_list_items():
    # TOC entries and body list items are indented -- must NOT match.
    assert _SECTION_RE.match("   1. Introduction ....................2") is None
    assert _SECTION_RE.match("   1. Check the origin AS.") is None
    # A real, flush-left section header must match.
    assert _SECTION_RE.match("1.  Introduction") is not None
    assert _SECTION_RE.match("1.1.  Scope") is not None


def test_clean_rfc_text_strips_preamble_toc_and_page_furniture():
    cleaned = _clean_rfc_text(_FAKE_RFC)

    assert "Status of This Memo" not in cleaned
    assert "Copyright Notice" not in cleaned
    assert "Table of Contents" not in cleaned
    # The TOC's dot-leader page-number line for section 2 must be gone too,
    # not just the "Table of Contents" heading itself.
    assert "Hijack Considerations .." not in cleaned
    assert "[Page 1]" not in cleaned
    assert "RFC 9999                    Fake Protocol" not in cleaned

    # Real body content survives.
    assert "This document is a fake RFC used only for testing" in cleaned
    assert "1.1.  Scope" in cleaned
    assert "2.  Hijack Considerations" in cleaned
    assert "An unexpected change in origin AS" in cleaned

    # The body's own numbered list (indented, not a section header) survives.
    assert "1. Check the origin AS." in cleaned


def test_clean_rfc_text_drops_references_onward():
    cleaned = _clean_rfc_text(_FAKE_RFC)
    assert "References" not in cleaned
    assert "RFC0001" not in cleaned
    assert "Author's Address" not in cleaned
    assert "author@example.com" not in cleaned
    assert "Full Copyright Statement" not in cleaned


def test_clean_rfc_text_is_a_noop_on_hand_picked_excerpt_style_text():
    excerpt = (
        "RFC 7908 - Problem Definition and Classification of BGP Route Leaks\n"
        "NOTE: condensed excerpt.\n\n"
        "4. Origin and Hijack Considerations\n"
        "A prefix normally originated by a single AS may appear originated by a\n"
        "different AS (a Multiple Origin AS, MOAS, condition).\n"
    )
    # splitlines()+join() drops a trailing newline, which load_corpus (line-
    # based) doesn't care about -- compare content, not exact trailing bytes.
    assert _clean_rfc_text(excerpt) == excerpt.rstrip("\n")


def test_load_corpus_labels_chunks_with_the_real_section_not_a_toc_entry(tmp_path):
    (tmp_path / "rfc9999_fake.txt").write_text(_FAKE_RFC, encoding="utf-8")
    chunks = load_corpus(str(tmp_path), target_words=5)

    hijack_chunks = [c for c in chunks if "unexpected change in origin AS" in c.text]
    assert hijack_chunks, "expected the Hijack Considerations body text to survive chunking"
    assert hijack_chunks[0].source_id == "RFC 9999 §2"

    # References-onward content must not appear in any chunk at all.
    assert not any("RFC0001" in c.text for c in chunks)
