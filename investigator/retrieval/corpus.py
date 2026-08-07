"""RFC corpus loading + chunking.

Loads plain-text RFC files from a directory and splits them into
citation-sized chunks, keeping a section-aware source label (e.g.
"RFC 4271 §9.1.2") so citations resolve to something a human can look up.

For Phase 1 we shipped a few hand-picked RFC excerpts. As of the corpus
expansion (docs/alignment-plan.md item 4b) real full-text RFCs from
rfc-editor.org are supported too — the loader is format-agnostic about
which/how many files are present, but full RFC text needs a cleaning pass
first (see `_clean_rfc_text`) that the hand-picked excerpts never needed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Real section headers in IETF plain-text RFCs are flush against column 0
# ("3.  Summary of Operation", "8.2.1.5.  FSM Actions..."); Table-of-Contents
# entries and body numbered-list items are always indented (RFC body text is
# conventionally indented 3 spaces). The old `^\s*` prefix matched both,
# mislabeling TOC/list-item lines as section headers -- a bug that only
# showed up against real RFC text, never the hand-picked excerpts (which
# have no TOC and no numbered lists). Anchoring to column 0 and requiring
# the trailing period IETF headers always have fixes it.
_SECTION_RE = re.compile(r"^(\d+(?:\.\d+)*)\.\s+\S")
_RFC_ID_RE = re.compile(r"rfc[_-]?(\d+)", re.IGNORECASE)

# Running footer: "Rekhter, et al.             Standards Track     [Page 1]"
_PAGE_FOOTER_RE = re.compile(r"^\S.*\[Page \d+\]\s*$")
# Running header: "RFC 4271                         BGP-4              January 2006"
_PAGE_HEADER_RE = re.compile(
    r"^RFC \d+\s{2,}\S.*\s{2,}"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r" \d{4}\s*$"
)
# Trailing boilerplate: References (any variant) through end of file also
# sweeps up Authors'/Editors' Addresses and the Full Copyright Statement /
# IPR boilerplate that always follow it in IETF RFCs -- one cut, not three.
_REFERENCES_HEADING_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*\.\s+)?(?:normative |informative )?references\s*$", re.IGNORECASE
)
_PREAMBLE_HEADING_RE = re.compile(r"^(Status of This Memo|Copyright Notice)\s*$")
_TOC_HEADING_RE = re.compile(r"^Table of Contents\s*$")
# Any flush-left, non-blank line -- RFC body text is conventionally indented
# 3 spaces, so column 0 is reserved for headings (numbered like "3.  Summary
# of Operation", or bare like "Abstract"/"Introduction" -- pre-~2000 RFCs
# routinely skip numbering entirely). Used to find where a preamble/TOC skip
# should end: the *first* heading of either style, not specifically a
# numbered one -- an earlier version of this function only recognized
# numbered headers, so on an RFC using bare headings throughout (e.g.
# RFC 1997, which never numbers a single section) the skip never found
# anywhere to stop and ate the entire body. Caught by running this over all
# 16 target RFCs, not assumed to work from RFC 4271 alone.
_FLUSH_LEFT_HEADING_RE = re.compile(r"^\S")


def _clean_rfc_text(raw: str) -> str:
    """Strip the page furniture real IETF RFC text has that the Phase 1
    hand-picked excerpts never did: form-feed page breaks + running
    header/footer pairs, the Status-of-This-Memo/Copyright-Notice preamble,
    the Table of Contents (dense with section titles that would otherwise
    outrank real body text on exactly the queries that matter), and
    everything from References onward (bibliography + address + copyright
    boilerplate, not investigatable content). A no-op on text that has none
    of these markers, so it's safe to run over the existing hand-picked
    excerpts too."""
    lines = raw.replace("\f", "\n").splitlines()

    kept: list[str] = []
    skip_until_heading = False  # inside Status-of-Memo/Copyright/TOC block
    for line in lines:
        if _REFERENCES_HEADING_RE.match(line):
            break  # References onward: bibliography + addresses + copyright, all dropped

        if _PAGE_FOOTER_RE.match(line) or _PAGE_HEADER_RE.match(line):
            continue  # dropped unconditionally, including mid-skip

        if _PREAMBLE_HEADING_RE.match(line) or _TOC_HEADING_RE.match(line):
            skip_until_heading = True
            continue
        if skip_until_heading:
            if _FLUSH_LEFT_HEADING_RE.match(line):
                skip_until_heading = False  # fall through, this line is real body content
            else:
                continue

        kept.append(line)

    return "\n".join(kept)


@dataclass(frozen=True)
class Chunk:
    source_id: str   # e.g. "RFC 4271 §9.1.2"
    text: str

    def tokens(self) -> list[str]:
        return _tokenize(self.text)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _rfc_label(path: Path) -> str:
    m = _RFC_ID_RE.search(path.stem)
    return f"RFC {m.group(1)}" if m else path.stem


def load_corpus(directory: str | Path, target_words: int = 90) -> list[Chunk]:
    """Load and chunk every .txt file in `directory`.

    Chunks break on blank lines and are grown until ~target_words, tagging each
    with the most recent section number seen (best-effort).
    """
    directory = Path(directory)
    chunks: list[Chunk] = []

    for path in sorted(directory.glob("*.txt")):
        rfc = _rfc_label(path)
        section = ""
        buf: list[str] = []
        buf_words = 0

        def flush():
            nonlocal buf, buf_words
            if buf:
                label = f"{rfc} §{section}" if section else rfc
                chunks.append(Chunk(source_id=label, text=" ".join(buf).strip()))
                buf, buf_words = [], 0

        cleaned = _clean_rfc_text(path.read_text(errors="ignore"))
        for line in cleaned.splitlines():
            stripped = line.strip()
            m = _SECTION_RE.match(line)
            if m:
                flush()
                section = m.group(1)
            if not stripped:
                if buf_words >= target_words:
                    flush()
                continue
            buf.append(stripped)
            buf_words += len(stripped.split())
            if buf_words >= target_words * 1.6:
                flush()
        flush()

    return chunks
