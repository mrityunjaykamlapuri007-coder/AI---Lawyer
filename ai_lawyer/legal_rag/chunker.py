"""One chunk per provision by default; long provisions split at clause boundaries.

Provision ids never depend on chunking.  ``original_text`` is never rewritten.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ai_lawyer.contracts.models import Provision
from ai_lawyer.legal_rag.corpus_loader import Corpus

_BOUNDARY_RE = re.compile(
    r"(?m)(?=^\s*(?:\(\w+\)|\(\d+\)|Provided that|Explanation\.?|Exception\.?)\s)"
)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    provision_id: str
    parent_provision_id: str | None
    chunk_order: int
    source_id: str
    citation: str
    hierarchy_type: str
    text: str
    original_text: str
    search_text: str
    page_start: int
    page_end: int

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "provision_id": self.provision_id,
            "parent_provision_id": self.parent_provision_id,
            "chunk_order": self.chunk_order,
            "source_id": self.source_id,
            "citation": self.citation,
            "hierarchy_type": self.hierarchy_type,
            "text": self.text,
            "original_text": self.original_text,
            "search_text": self.search_text,
            "page_start": self.page_start,
            "page_end": self.page_end,
        }


def _split_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    boundaries = [m.start() for m in _BOUNDARY_RE.finditer(text) if m.start() > 0]
    cuts: list[int] = [0]
    while cuts[-1] < len(text):
        start = cuts[-1]
        remaining = len(text) - start
        if remaining <= max_chars:
            cuts.append(len(text))
            break
        candidates = [b for b in boundaries if start < b <= start + max_chars]
        cut = candidates[-1] if candidates else start + max_chars
        cuts.append(cut)
    out: list[str] = []
    for a, b in zip(cuts, cuts[1:]):
        piece = text[a:b]
        if piece.strip():
            out.append(piece)
    return out or [text]


def chunk_provision(provision: Provision, max_chars: int = 1800) -> list[Chunk]:
    pieces = _split_text(provision.original_text, max_chars)
    chunks: list[Chunk] = []
    for order, piece in enumerate(pieces):
        chunk_id = f"{provision.provision_id}::c{order}" if len(pieces) > 1 else f"{provision.provision_id}::c0"
        search_blob = " ".join(
            x for x in [provision.citation, provision.search_text, piece] if x
        )
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                provision_id=provision.provision_id,
                parent_provision_id=provision.parent_provision_id,
                chunk_order=order,
                source_id=provision.source_id,
                citation=provision.citation,
                hierarchy_type=provision.hierarchy_type,
                text=piece,
                original_text=provision.original_text,
                search_text=search_blob,
                page_start=provision.page_start,
                page_end=provision.page_end,
            )
        )
    return chunks


def chunk_corpus(corpus: Corpus, max_chars: int = 1800) -> list[Chunk]:
    chunks: list[Chunk] = []
    for provision in corpus.provisions.values():
        chunks.extend(chunk_provision(provision, max_chars=max_chars))
    return chunks
