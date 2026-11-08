"""Exact-ID case matching, clarification, reopening and append-only facts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_lawyer.backend.db.repo import Database
from ai_lawyer.contracts.ids import new_id
from ai_lawyer.contracts.models import Fact


@dataclass
class CaseResolution:
    case_id: str | None
    clarification: str | None = None
    split_required: bool = False
    is_new: bool = False
    reopened: bool = False


def _identifiers(facts: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    orders = list(dict.fromkeys(f["raw_value"] for f in facts if f["fact_type"] == "order_id"))
    txns = list(dict.fromkeys(f["raw_value"] for f in facts if f["fact_type"] == "transaction_id"))
    return orders, txns


def _summary_from_facts(facts: list[dict[str, Any]], identifiers: list[str]) -> dict[str, Any]:
    def latest(fact_type: str):
        vals = [f for f in facts if f["fact_type"] == fact_type and f["normalised_value"] is not None]
        return vals[-1]["normalised_value"] if vals else None

    amount = latest("refund_amount")
    return {
        "identifiers": identifiers,
        "merchant": latest("merchant_name"),
        "platform": latest("platform_name"),
        "amount_minor": amount,
        "currency": "INR",
        "refund_status": latest("refund_status"),
    }


def resolve_case(
    db: Database,
    *,
    user_id: str,
    conversation_id: str,
    facts: list[dict[str, Any]],
    message: str,
    case_id_hint: str | None = None,
) -> CaseResolution:
    orders, txns = _identifiers(facts)
    if len(orders) >= 2:
        return CaseResolution(
            case_id=None,
            clarification=(
                "I found two different order references in one message ("
                + ", ".join(orders)
                + "). Please send one message per order so the facts are not mixed. "
                "Which order would you like to discuss first?"
            ),
            split_required=True,
        )

    identifiers = orders + [t for t in txns if t not in orders]
    if case_id_hint:
        case = db.get_case(case_id_hint)
        if case and case.user_id == user_id:
            return CaseResolution(case_id=case.case_id, is_new=False)

    if identifiers:
        matches: list = []
        for identifier in identifiers:
            for case in db.find_cases_by_identifier(user_id, identifier):
                if all(case.case_id != m.case_id for m in matches):
                    matches.append(case)
        if len(matches) > 1:
            return CaseResolution(
                case_id=None,
                clarification=(
                    "Those identifiers match more than one existing case. Please confirm which case "
                    "this message is about."
                ),
            )
        if len(matches) == 1:
            case = matches[0]
            summary = dict(case.summary)
            summary.update(_summary_from_facts(facts, identifiers))
            summary["identifiers"] = list(dict.fromkeys(list(summary.get("identifiers", [])) + identifiers))
            reopened = False
            if case.status == "resolved":
                db.update_case(case.case_id, status="reopened", summary=summary)
                db.append_event(case.case_id, "case_reopened", {"reason": "new message on resolved case"})
                reopened = True
            else:
                db.update_case(case.case_id, summary=summary)
            return CaseResolution(case_id=case.case_id, is_new=False, reopened=reopened)
        summary = _summary_from_facts(facts, identifiers)
        case_id = db.create_case(user_id, summary, conversation_id)
        return CaseResolution(case_id=case_id, is_new=True)

    # No identifier in this message.
    same_conversation = [
        c for c in db.cases_for_conversation(conversation_id) if c.status in {"open", "reopened"}
    ]
    if len(same_conversation) == 1:
        case = same_conversation[0]
        summary = dict(case.summary)
        summary.update({k: v for k, v in _summary_from_facts(facts, []).items() if v is not None})
        summary["identifiers"] = summary.get("identifiers", [])
        reopened = False
        if case.status == "resolved":
            db.update_case(case.case_id, status="reopened", summary=summary)
            db.append_event(case.case_id, "case_reopened", {"reason": "new message on resolved case"})
            reopened = True
        else:
            db.update_case(case.case_id, summary=summary)
        return CaseResolution(case_id=case.case_id, is_new=False, reopened=reopened)

    # A new chat without an order id starts its own case.  Cases from other chats
    # are linked only by an explicit order or transaction id (handled above);
    # asking "which open case?" on a first vague message confused real users.
    summary = _summary_from_facts(facts, [])
    case_id = db.create_case(user_id, summary, conversation_id)
    return CaseResolution(case_id=case_id, is_new=True)


def persist_facts(
    db: Database,
    case_id: str,
    fact_dicts: list[dict[str, Any]],
    *,
    correction: bool = False,
) -> list[Fact]:
    existing = db.get_facts(case_id)
    saved: list[Fact] = []
    for item in fact_dicts:
        supersedes = item.get("supersedes_fact_id")
        if correction and not supersedes:
            same_type = [f for f in existing if f.fact_type == item["fact_type"]]
            if same_type:
                supersedes = same_type[-1].fact_id
        fact = Fact(
            case_id=case_id,
            fact_type=item["fact_type"],
            raw_value=item["raw_value"],
            normalised_value=item.get("normalised_value"),
            source_type=item.get("source_type", "user_message"),
            source_id=item.get("source_id", "user"),
            evidence_id=item.get("evidence_id"),
            page_number=item.get("page_number"),
            status=item.get("status", "user_reported"),
            inferred=bool(item.get("inferred", False)),
            ambiguity_flag=bool(item.get("ambiguity_flag", False)),
            supersedes_fact_id=supersedes,
        )
        db.add_fact(fact)
        db.append_event(
            case_id,
            "fact_added",
            {
                "fact_id": fact.fact_id,
                "fact_type": fact.fact_type,
                "source_type": fact.source_type,
                "status": fact.status,
            },
        )
        existing.append(fact)
        saved.append(fact)
    return saved


def _latest_active(facts: list[Fact], fact_type: str):
    active = [f for f in facts if not any(g.supersedes_fact_id == f.fact_id for g in facts)]
    items = [f for f in active if f.fact_type == fact_type and f.normalised_value is not None]
    if not items:
        return None
    items.sort(key=lambda f: f.created_at)
    return items[-1].normalised_value


def update_resolution_status(db: Database, case_id: str, facts: list[Fact]) -> str:
    """Resolve only when the *latest* status says money arrived and the latest
    bank-credit fact is positive.

    Old facts are retained (append-only), so looking at "any" historical fact
    would wrongly keep a case resolved after a later reversal.
    """
    case = db.get_case(case_id)
    if not case:
        return "open"
    status = str(_latest_active(facts, "refund_status") or "").lower()
    credit = _latest_active(facts, "bank_credit_confirmed")
    received = status in {"received", "credited", "refunded"}
    if received and credit is True and case.status != "resolved":
        db.update_case(case_id, status="resolved")
        db.append_event(case_id, "case_resolved", {"reason": "refund arrival reported by user"})
        return "resolved"
    return case.status
