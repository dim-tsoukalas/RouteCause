"""Claim segmentation: split a narrated answer into individually-checkable
(claim text, cited source numbers) pairs.

Deliberately simple -- a sentence-boundary regex plus `[n]` marker
extraction, not a real NLP sentence splitter. Good enough for the kind of
short, citation-per-clause technical prose `CITATION_QA_TEMPLATE`
(investigator/retrieval/citations.py) asks the LLM for; documented as a
heuristic, same honesty standard as the rest of this project's approximations
(BM25 instead of dense retrieval, the RIB-baseline gap, MOAS's
"presumed-legitimate-origin" quirk).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_CITATION_RE = re.compile(r"\[(\d+)\]")
# Split after sentence-ending punctuation, but only when the *next* sentence
# clearly starts (an uppercase letter) -- not right after the punctuation
# itself, so a trailing "[1]" or "[1][2]" stays attached to the sentence it
# cites rather than becoming its own empty "claim".
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Claim:
    text: str                         # claim text, citation markers stripped
    cited_source_ns: tuple[int, ...]  # [n] markers attached to it (maybe empty)


def extract_claims(answer_text: str) -> list[Claim]:
    text = answer_text.strip()
    if not text:
        return []

    claims: list[Claim] = []
    for chunk in _SENTENCE_SPLIT_RE.split(text):
        chunk = chunk.strip()
        if not chunk:
            continue
        ns = tuple(int(n) for n in _CITATION_RE.findall(chunk))
        clean = _WHITESPACE_RE.sub(" ", _CITATION_RE.sub("", chunk)).strip()
        if not clean:
            continue  # the chunk was only a citation marker, no claim text
        claims.append(Claim(text=clean, cited_source_ns=ns))
    return claims
