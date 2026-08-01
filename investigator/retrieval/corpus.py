"""RFC corpus loading + chunking.

Loads plain-text RFC files from a directory and splits them into
citation-sized chunks, keeping a section-aware source label (e.g.
"RFC 4271 §9.1.2") so citations resolve to something a human can look up.

For Phase 1 we ship a few hand-picked RFC excerpts. To scale to the full
corpus, drop the IETF bulk text dump into the same directory — the loader is
format-agnostic about which/how many files are present.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SECTION_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+\S")
_RFC_ID_RE = re.compile(r"rfc[_-]?(\d+)", re.IGNORECASE)


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

        for line in path.read_text(errors="ignore").splitlines():
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
