"""Deterministic citation / section-number guard.

Every provision id the model cites must be in the accepted set.  Section/rule
numbers in free text must match a rendered citation from an accepted provision.
Unsupported material is removed, never quietly tolerated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from ai_lawyer.contracts.models import Candidate, LegalDraft
from ai_lawyer.legal_rag.corpus_loader import Corpus

_SECTION_RE = re.compile(r"\b(?:Section|Sec\.?|Rule)\s+\d+[A-Za-z]?(?:\([0-9]+\))?", re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass
class GuardResult:
    draft: LegalDraft
    blocked_claims: list[dict[str, Any]] = field(default_factory=list)
    rewrites: list[dict[str, Any]] = field(default_factory=list)


def _normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _allowed_matches(accepted: list[Candidate], corpus: Corpus) -> set[str]:
    allowed: set[str] = set()
    for cand in accepted:
        if not cand.accepted:
            continue
        provision = corpus.get(cand.provision_id)
        if provision:
            allowed.add(_normalise(provision.citation))
    return allowed


def _strip_unsupported_text(
    text: str, allowed_citations: set[str], field_name: str, blocked: list[dict[str, Any]]
) -> str:
    if not text:
        return text
    pieces = _SENTENCE_SPLIT.split(text)
    kept: list[str] = []
    for piece in pieces:
        match = _SECTION_RE.search(piece)
        if match and _normalise(match.group(0)) not in " ".join(allowed_citations):
            blocked.append(
                {
                    "type": "citation_blocked",
                    "field": field_name,
                    "detail": f"unsupported section/rule reference removed: {match.group(0)}",
                }
            )
            continue
        kept.append(piece)
    return " ".join(kept).strip() if len(kept) != len(pieces) else text


def _list_fields(draft: LegalDraft) -> Iterable[tuple[str, list[str]]]:
    yield "user_reported_facts", draft.user_reported_facts
    yield "document_supported_facts", draft.document_supported_facts
    yield "missing_facts", draft.missing_facts
    yield "assumptions", draft.assumptions
    yield "uncertainties", draft.uncertainties
    yield "possible_options", draft.possible_options


def validate_draft(
    draft: LegalDraft,
    accepted: list[Candidate],
    corpus: Corpus,
) -> GuardResult:
    blocked: list[dict[str, Any]] = []
    clean = draft.model_copy(deep=True)
    accepted_ids = {c.provision_id for c in accepted if c.accepted}

    for pid in list(clean.relevant_provision_ids):
        if pid not in accepted_ids:
            clean.relevant_provision_ids.remove(pid)
            blocked.append(
                {
                    "type": "unknown_provision_id",
                    "field": "relevant_provision_ids",
                    "detail": f"removed uncited/invented provision id: {pid}",
                }
            )
    kept_analysis = []
    for item in clean.application_analysis:
        if item.provision_id not in accepted_ids:
            blocked.append(
                {
                    "type": "unknown_provision_id",
                    "field": "application_analysis",
                    "detail": f"removed analysis for uncited provision id: {item.provision_id}",
                }
            )
            continue
        kept_analysis.append(item)
    clean.application_analysis = kept_analysis

    allowed = _allowed_matches(accepted, corpus)
    clean.issue_summary = _strip_unsupported_text(
        clean.issue_summary, allowed, "issue_summary", blocked
    )
    clean.proposed_next_step = _strip_unsupported_text(
        clean.proposed_next_step, allowed, "proposed_next_step", blocked
    )
    for field_name, values in _list_fields(clean):
        for i, value in enumerate(list(values)):
            values[i] = _strip_unsupported_text(value, allowed, field_name, blocked)
    for item in clean.application_analysis:
        item.conditional_statement = _strip_unsupported_text(
            item.conditional_statement, allowed, "conditional_statement", blocked
        )

    return GuardResult(draft=clean, blocked_claims=blocked)
