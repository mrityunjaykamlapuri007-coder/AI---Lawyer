"""Acceptance policy and candidate roles (v3 Section 6 step 9)."""
from __future__ import annotations

from datetime import date

from ai_lawyer.contracts.models import Candidate, Fact, RelevanceGrade
from ai_lawyer.legal_engine.applicability import evaluate_provision
from ai_lawyer.legal_engine.source_validity import evaluate_source_validity
from ai_lawyer.legal_rag.corpus_loader import Corpus

_ROLE_ORDER = {
    "primary": 0,
    "supporting": 1,
    "mandatory_qualifier": 2,
    "background": 3,
    "rejected": 4,
}


def _mandatory_ids(corpus: Corpus) -> set[str]:
    out: set[str] = set()
    for provision in corpus.provisions.values():
        out.update(provision.mandatory_context)
    return out


def assign_roles(
    candidates: list[Candidate],
    corpus: Corpus,
    facts: list[Fact],
    as_of_date: date | None,
    grades: dict[str, RelevanceGrade],
    min_grade: int = 2,
) -> list[Candidate]:
    mandatory = _mandatory_ids(corpus)
    for cand in candidates:
        provision = corpus.get(cand.provision_id)
        grade = grades.get(cand.provision_id)
        cand.relevance_grade = grade.grade if grade else 0
        cand.relevance_reason = grade.reason if grade else "not graded"
        if provision is None:
            cand.role = "rejected"
            cand.rejection_reason = "provision not found in corpus"
            cand.accepted = False
            continue

        validity, validity_reason = evaluate_source_validity(
            corpus.sources[provision.source_id], as_of_date
        )
        cand.source_validity = validity
        applicability = evaluate_provision(provision, facts)
        cand.applicability = applicability.label  # type: ignore[assignment]
        cand.applicability_reasons = [applicability.reason]
        cand.citation = provision.citation

        usable = corpus.is_usable(provision.provision_id)
        if not usable:
            cand.role = "rejected"
            cand.rejection_reason = "source is not human_verified; not citable"
            cand.accepted = False
            continue
        if validity != "current_for_date":
            cand.role = "rejected"
            cand.rejection_reason = f"source not current for date: {validity} ({validity_reason})"
            cand.accepted = False
            continue

        if provision.provision_id in mandatory:
            cand.role = "mandatory_qualifier"
            cand.accepted = True
            cand.conditional = applicability.value is None
            cand.rejection_reason = None
            continue

        if applicability.value is False:
            cand.role = "rejected"
            cand.rejection_reason = f"conditions not met: {applicability.reason}"
            cand.accepted = False
            continue

        if cand.relevance_grade < min_grade:
            if cand.relevance_grade >= 1:
                cand.role = "background"
                cand.rejection_reason = f"relevance grade {cand.relevance_grade} below {min_grade}"
            else:
                cand.role = "rejected"
                cand.rejection_reason = f"relevance grade {cand.relevance_grade} below {min_grade}"
            cand.accepted = False
            continue

        cand.accepted = True
        cand.conditional = applicability.value is None
        cand.role = (
            "primary"
            if applicability.value is True and cand.relevance_grade >= 3
            else "supporting"
        )
        cand.rejection_reason = None

    return sorted(
        candidates,
        key=lambda c: (_ROLE_ORDER.get(c.role, 9), -(c.relevance_grade or 0), -c.rrf_score, c.provision_id),
    )


def accepted(candidates: list[Candidate]) -> list[Candidate]:
    return [c for c in candidates if c.accepted]


def accepted_ids(candidates: list[Candidate]) -> list[str]:
    return [c.provision_id for c in candidates if c.accepted]


def has_consumer_commission_route(candidates: list[Candidate], corpus: Corpus) -> bool:
    for cand in candidates:
        if not cand.accepted:
            continue
        provision = corpus.get(cand.provision_id)
        if not provision:
            continue
        blob = f"{provision.original_text} {provision.search_text} {provision.citation}".lower()
        if "consumer commission" in blob or "consumer commissions" in blob:
            return True
    return False
