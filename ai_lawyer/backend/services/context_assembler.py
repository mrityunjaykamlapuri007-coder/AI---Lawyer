"""Compact case context for retrieval, reasoning and the UI."""
from __future__ import annotations

from datetime import date
from typing import Any

from ai_lawyer.contracts.ids import parse_iso_date, today_utc
from ai_lawyer.contracts.models import Fact, TimelineItem
from ai_lawyer.legal_engine.applicability import active_facts

_DATE_LABELS = {
    "purchase_date": "Purchase",
    "cancellation_date": "Cancellation",
    "return_requested_date": "Return requested",
    "return_approved_date": "Return approved",
    "pickup_date": "Pickup",
    "refund_initiated_date": "Refund initiated",
    "support_contact_date": "Support contacted",
    "grievance_contact_date": "Grievance officer contacted",
}


def choose_as_of_date(facts: list[Fact], as_of: date | None = None) -> tuple[date, str]:
    """The date used for elapsed-day calculations and source validity.

    It is the current date unless the caller supplies an explicit date (the
    evaluation harness freezes it to the scenario's ``now``).  Event dates in
    the case are *not* used here: using them would make every elapsed-day
    calculation zero.
    """
    return (as_of or today_utc()), "explicit as-of date" if as_of else "today (UTC)"


def build_timeline(facts: list[Fact]) -> list[TimelineItem]:
    items: list[TimelineItem] = []
    for fact in active_facts(facts):
        if fact.fact_type in _DATE_LABELS:
            parsed = parse_iso_date(fact.normalised_value)
            items.append(
                TimelineItem(
                    event_type=fact.fact_type,
                    date=parsed,
                    date_label=fact.raw_value,
                    precision="exact" if parsed else "unknown",
                    source_id=fact.source_id,
                    source_status=fact.status,
                    summary=f"{_DATE_LABELS[fact.fact_type]}: {fact.raw_value}",
                    conflict_flag=fact.ambiguity_flag,
                )
            )
    items.sort(key=lambda i: (i.date or date.min, i.event_type))
    return items


def assemble_context(
    *,
    case_id: str,
    case_summary: dict[str, Any],
    facts: list[Fact],
    message: str,
    as_of_date: date,
    as_of_basis: str,
) -> dict[str, Any]:
    active = active_facts(facts)
    grouped: dict[str, list[dict[str, Any]]] = {
        "user_reported": [],
        "document_supported": [],
        "disputed": [],
        "unknown": [],
    }
    for fact in active:
        grouped.setdefault(fact.status, []).append(
            {
                "fact_id": fact.fact_id,
                "fact_type": fact.fact_type,
                "value": fact.normalised_value,
                "raw_value": fact.raw_value,
                "source_type": fact.source_type,
                "evidence_id": fact.evidence_id,
                "page_number": fact.page_number,
                "ambiguity_flag": fact.ambiguity_flag,
            }
        )
    conflicts = [
        {
            "fact_id": f.fact_id,
            "fact_type": f.fact_type,
            "raw_value": f.raw_value,
            "normalised_value": f.normalised_value,
        }
        for f in active
        if f.ambiguity_flag
    ]
    timeline = [i.model_dump(mode="json") for i in build_timeline(facts)]
    return {
        "case_id": case_id,
        "case_summary": case_summary,
        "current_message": message,
        "facts": grouped,
        "timeline": timeline,
        "conflicts": conflicts,
        "as_of_date": as_of_date.isoformat(),
        "as_of_basis": as_of_basis,
    }


def facts_for_prompt(facts: list[Fact]) -> list[dict[str, Any]]:
    return [
        {
            "fact_id": f.fact_id,
            "fact_type": f.fact_type,
            "raw_value": f.raw_value,
            "normalised_value": f.normalised_value,
            "status": f.status,
            "source_type": f.source_type,
            "page_number": f.page_number,
            "ambiguity_flag": f.ambiguity_flag,
        }
        for f in active_facts(facts)
    ]
