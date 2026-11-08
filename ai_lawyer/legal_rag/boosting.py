"""Legal-safe analogue of the reference project's "section boosting".

The reference RAG assistant adds a fixed bonus to chunks whose detected paper
section is ``abstract``/``result``/etc.  That rule does not transfer to
statutes: a generic section bonus can outrank the provision the user actually
named, and a proviso can be pushed out of the context window by the clause it
qualifies.

Two separate mechanisms replace it:

1. **explicit reference** (score bonus) - the query says "section 35" and the
   provision is section 35.  This is the only bonus added to the fused score,
   because it must be able to override a dense/sparse disagreement.
2. **qualifying material** (tie-break only) - the provision carries provisos or
   exceptions.  It never changes a score; it only orders candidates whose RRF
   scores are exactly equal.  A qualifier therefore cannot displace a relevant
   provision, but it is never dropped when scores tie.

Calibration matters: RRF scores at k=60 are roughly 0.016 per list, so an
additive bonus of 0.02 is larger than the entire fusion spread.  An earlier
version of this module used such a bonus and moved hybrid MRR from 0.82 to
0.48 on the fixture set.  Any additive bonus must be justified against the RRF
scale, not copied from a different scoring system.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Sequence

from ai_lawyer.config.settings import Settings
from ai_lawyer.legal_rag.rrf import FusedResult

# "section 35", "sec. 35(2)", "rule 12", "regulation 3", "article 21",
# "clause 4.2", plus lettered forms such as "Article A1".
_REF_RE = re.compile(
    r"\b(?:section|sec\.?|rule|regulation|article|clause)\s+"
    r"(\d+[A-Za-z]?|[A-Z]\d+[A-Za-z]?)(?:\s*\(\s*\d+\s*\))?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Boost:
    exact: float = 0.0
    qualifier: bool = False
    reasons: tuple[str, ...] = ()


def _norm(kind: str, number: str) -> str:
    kind = kind.lower().rstrip(".")
    if kind in {"sec", "sect"}:
        kind = "section"
    return f"{kind}:{number.upper()}"


def query_references(query: str) -> set[str]:
    out: set[str] = set()
    for match in _REF_RE.finditer(query or ""):
        out.add(_norm(match.group(0).split()[0], match.group(1)))
    return out


def citation_references(citation: str) -> set[str]:
    return query_references(citation or "")


def has_qualifiers(provisos: Sequence[str] | None, exceptions: Sequence[str] | None) -> bool:
    return bool(list(provisos or [])) or bool(list(exceptions or []))


def boost_for(
    *,
    query_refs: set[str],
    citation: str,
    provisos: Sequence[str] | None,
    exceptions: Sequence[str] | None,
    hierarchy_type: str = "",
    settings: Settings,
) -> Boost:
    reasons: list[str] = []
    exact = 0.0

    overlap = query_refs & citation_references(citation)
    if overlap:
        exact = settings.exact_reference_boost
        reasons.append("explicit reference: " + ", ".join(sorted(overlap)))

    qualifier = has_qualifiers(provisos, exceptions) or hierarchy_type == "proviso"
    if qualifier:
        reasons.append("carries qualifying material")

    return Boost(exact=exact, qualifier=qualifier, reasons=tuple(reasons))


def apply_boosts(
    fused: list[FusedResult],
    *,
    query: str,
    chunk_lookup: Callable[[str], dict | None],
    corpus,
    settings: Settings,
) -> list[FusedResult]:
    """Re-score explicit references, tie-break on qualifiers, stay deterministic."""
    if not fused:
        return fused

    query_refs = query_references(query)
    scored: list[tuple[float, int, str, FusedResult]] = []

    for item in fused:
        chunk = chunk_lookup(item.chunk_id) or {}
        provision_id = chunk.get("provision_id")
        provision = corpus.get(provision_id) if provision_id else None
        citation = getattr(provision, "citation", None) or chunk.get("citation", "")
        boost = boost_for(
            query_refs=query_refs,
            citation=citation,
            provisos=getattr(provision, "provisos", None),
            exceptions=getattr(provision, "exceptions", None),
            hierarchy_type=getattr(provision, "hierarchy_type", "") or chunk.get("hierarchy_type", ""),
            settings=settings,
        )
        score = item.score + boost.exact
        qualifier_rank = 1 if (boost.qualifier and settings.qualifier_tiebreak) else 0
        scored.append((score, qualifier_rank, item.chunk_id, item))

    scored.sort(key=lambda row: (-row[0], -row[1], row[2]))
    return [
        FusedResult(chunk_id=row[3].chunk_id, score=row[0], ranks=row[3].ranks)
        for row in scored
    ]
