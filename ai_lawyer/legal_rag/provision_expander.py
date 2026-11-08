"""Depth-1 provision expansion over stored corpus links.

Never drops a proviso or exception because of a low similarity score.  Every
added unit records why it was added.
"""
from __future__ import annotations

from ai_lawyer.contracts.models import Candidate
from ai_lawyer.legal_rag.corpus_loader import Corpus

_RELATIONS = (
    ("parent", "parent_provision_id"),
    ("proviso", "provisos"),
    ("exception", "exceptions"),
    ("definition", "definitions_used"),
    ("cross_reference", "cross_references"),
    ("mandatory_context", "mandatory_context"),
)


def expand(candidates: list[Candidate], corpus: Corpus) -> list[Candidate]:
    out: list[Candidate] = list(candidates)
    seen = {c.provision_id for c in out}

    for candidate in list(candidates):
        provision = corpus.get(candidate.provision_id)
        if provision is None:
            continue
        for label, attr in _RELATIONS:
            raw = getattr(provision, attr)
            refs = [raw] if isinstance(raw, str) else list(raw or [])
            for ref in refs:
                if not ref or ref in seen:
                    continue
                target = corpus.get(ref)
                if target is None:
                    continue
                seen.add(ref)
                out.append(
                    Candidate(
                        chunk_id=f"{ref}::expanded",
                        provision_id=ref,
                        source_id=target.source_id,
                        rrf_score=0.0,
                        added_because=f"{label}:{provision.provision_id}",
                        citation=target.citation,
                    )
                )
    return out
