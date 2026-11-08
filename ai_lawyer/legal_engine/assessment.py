"""Assessment rules R0-R7 (v3 Section 9).

Python owns the outcome.  Rules never depend on amount alone or on delay length
alone, and a delay is never called a violation.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from ai_lawyer.contracts.ids import parse_iso_date
from ai_lawyer.contracts.models import Assessment, Candidate, Fact, Outcome
from ai_lawyer.legal_engine.acceptance import has_consumer_commission_route
from ai_lawyer.legal_engine.applicability import active_facts
from ai_lawyer.legal_rag.corpus_loader import Corpus

_DATE_TYPES = (
    "purchase_date",
    "cancellation_date",
    "return_requested_date",
    "return_approved_date",
    "pickup_date",
    "refund_initiated_date",
)
_PENDING_STATUSES = {
    "not_received",
    "pending",
    "initiated",
    "processed",
    "partial",
    "denied",
    "failed",
    "reversed",
    "disputed",
}
_RECEIVED_STATUSES = {"received", "credited", "refunded", "completed"}


def _facts_of(facts: list[Fact], fact_type: str) -> list[Fact]:
    return [f for f in active_facts(facts) if f.fact_type == fact_type and f.normalised_value is not None]


def _latest(facts: list[Fact], fact_type: str) -> Any:
    items = _facts_of(facts, fact_type)
    if not items:
        return None
    items.sort(key=lambda f: f.created_at)
    return items[-1].normalised_value


def _bool_value(facts: list[Fact], fact_type: str) -> bool | None:
    value = _latest(facts, fact_type)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    return None


def _exact_dates(facts: list[Fact]) -> dict[str, date]:
    out: dict[str, date] = {}
    for ft in _DATE_TYPES:
        value = _latest(facts, ft)
        parsed = parse_iso_date(value)
        if parsed:
            out[ft] = parsed
    return out


def _missing_questions(facts: list[Fact], conflicts: list[Fact]) -> list[str]:
    questions: list[str] = []
    if conflicts:
        pairs = []
        for fact in conflicts[:2]:
            pairs.append(f"{fact.fact_type.replace('_', ' ')} = {fact.raw_value}")
        questions.append(
            "I have different dates or values that do not agree (" + "; ".join(pairs) + "). Which one is correct?"
        )
    status = _latest(facts, "refund_status")
    if status is None:
        questions.append("What is the current refund status shown by the merchant, platform or your bank?")
    if not _exact_dates(facts):
        questions.append("When did you cancel or return the order? Please give the exact date.")
    if _bool_value(facts, "support_contact_made") is None:
        questions.append("Have you contacted the seller or platform support in writing, and on what date?")
    elif _bool_value(facts, "support_contact_made") and _bool_value(facts, "grievance_officer_contacted") is None:
        questions.append("Have you contacted the platform's grievance officer, and on what date?")
    if _bool_value(facts, "bank_credit_confirmed") is None and str(status).lower() in {"initiated", "processed"}:
        questions.append("Has your bank or payment app confirmed whether the credit was received?")
    return questions


def _lawyer_flags(user_text: str, facts: list[Fact]) -> tuple[bool, str | None, str]:
    text = (user_text or "").lower()
    reasons: list[str] = []
    urgency = "unknown"
    if any(w in text for w in ("represent me", "lawyer", "advocate", "legal representation")):
        reasons.append("the user asks about legal representation")
    if any(w in text for w in ("court", "limitation period", "limitation deadline", "hearing")):
        reasons.append("the user mentions a court or a limitation deadline")
        urgency = "high"
    if any(w in text for w in ("fraud", "cheat", "cheated", "criminal", "police", "threat", "extortion")):
        reasons.append("the user alleges fraud or criminal conduct")
        urgency = "high"
    parties = sum(
        1
        for term in ("seller", "marketplace", "platform", "bank", "payment")
        if term in text
    )
    if parties >= 2 and any(w in text for w in ("who is responsible", "who must", "says the", "not clear", "unclear")):
        reasons.append("responsibility between seller, marketplace, payment provider or bank is unclear")
    if not reasons and any(w in text for w in ("sue", "case against")):
        reasons.append("the user is considering formal proceedings")
    return (bool(reasons), "; ".join(reasons) if reasons else None, urgency)


def _next_steps(outcome: Outcome, promised_days: int | None, trigger_label: str | None) -> list[str]:
    if outcome == Outcome.no_legal_action_currently_required:
        step = "Keep a written record and monitor the refund."
        if promised_days is not None:
            step += (
                f" Follow up after the merchant's own timeline of {promised_days} days "
                f"(calendar days, counting from {trigger_label or 'the trigger date'}, trigger date excluded)."
            )
        return [step, "Save the order, payment and refund messages."]
    if outcome == Outcome.informal_resolution_recommended:
        return [
            "Send a written support request to the seller or platform and keep proof of sending.",
            "State the order id, dates, amount and what outcome you want.",
            "Wait for a response before escalating.",
        ]
    if outcome == Outcome.formal_grievance_recommended:
        return [
            "Send a formal written grievance to the platform's grievance officer.",
            "Attach the order, payment, return and support messages.",
            "Keep proof of delivery and ask for a written response.",
        ]
    if outcome == Outcome.formal_legal_proceedings_may_be_justified:
        return [
            "Formal proceedings may be justified, but this is not a guarantee of any outcome.",
            "Gather the order, payment, return, support and grievance records.",
            "Consider getting advice from a qualified lawyer before filing anything.",
        ]
    if outcome == Outcome.needs_more_information:
        return ["Answer the follow-up question so the refund timeline can be assessed."]
    return ["This issue is outside the scope of this assistant. Please speak to a qualified lawyer."]


def assess_case(
    *,
    in_scope: bool,
    accepted_candidates: list[Candidate],
    corpus: Corpus,
    facts: list[Fact],
    as_of_date: date,
    user_text: str,
    llm_proposed_outcome: str | None = None,
) -> Assessment:
    trace: list[str] = []
    active = active_facts(facts)
    accepted = [c for c in accepted_candidates if c.accepted]
    conflicts = [f for f in active if f.ambiguity_flag]
    missing = _missing_questions(active, conflicts)
    lawyer_needed, lawyer_reason, urgency = _lawyer_flags(user_text, active)

    def build(outcome: Outcome, reasons: list[str], rule: str) -> Assessment:
        trace.append(f"{rule}: {reasons[0] if reasons else outcome.value}")
        # Only ask follow-up questions when the next step genuinely depends on
        # them.  If Python has already selected a clear outcome (for example a
        # refund still inside the merchant's promised timeline), extra
        # questions would contradict the answer and are withheld.
        questions = missing if outcome == Outcome.needs_more_information else []
        return Assessment(
            outcome=outcome,
            reasons=reasons,
            facts_used=[f.fact_id for f in active],
            provision_ids_used=[c.provision_id for c in accepted],
            missing_information=questions,
            uncertainties=[c.rejection_reason or "" for c in accepted_candidates if c.rejection_reason][:5],
            urgency=urgency,  # type: ignore[arg-type]
            next_steps=_next_steps(
                outcome,
                int(_latest(active, "merchant_promised_timeline_days") or 0) or None,
                next(iter(_exact_dates(active)), None),
            ),
            lawyer_needed=lawyer_needed,
            lawyer_reason=lawyer_reason,
            rule_trace=trace,
            llm_proposed_outcome=llm_proposed_outcome,
        )

    if not in_scope:
        return build(
            Outcome.out_of_scope,
            ["The issue is outside unresolved e-commerce refund disputes in India."],
            "R0",
        )

    if not accepted:
        reasons = [
            "The supported knowledge base did not establish an applicable provision after bounded retries."
        ]
        assessment = build(Outcome.needs_more_information, reasons, "R1")
        assessment.uncertainties.append("No accepted legal provision; no legal conclusion is offered.")
        return assessment

    if conflicts:
        return build(
            Outcome.needs_more_information,
            ["The case contains conflicting dates or values that must be resolved first."],
            "R2-conflict",
        )

    status = _latest(active, "refund_status")
    exact = _exact_dates(active)
    if status is None or not exact:
        return build(
            Outcome.needs_more_information,
            [
                "An essential fact is missing: "
                + ("the refund status" if status is None else "an exact cancellation/return date")
                + "."
            ],
            "R2",
        )

    status_text = str(status).lower()
    pending = status_text in _PENDING_STATUSES
    unresolved = pending or _bool_value(active, "bank_credit_confirmed") is False
    support = _bool_value(active, "support_contact_made")
    grievance = _bool_value(active, "grievance_officer_contacted")

    # R4 is checked before R3: a refund that is still inside the merchant's own
    # promised (user-reported) timeline does not yet need even an informal
    # escalation.  A denial or a partial refund is not a "delay within a
    # timeline", so R4 only applies to pending-style statuses.
    promised = _latest(active, "merchant_promised_timeline_days")
    if promised is not None and pending and status_text not in {"denied", "partial"}:
        try:
            promised_days = int(promised)
        except (TypeError, ValueError):
            promised_days = None
        if promised_days is not None and exact:
            trigger_type = next(iter(exact))
            elapsed = (as_of_date - exact[trigger_type]).days
            if 0 <= elapsed <= promised_days:
                return build(
                    Outcome.no_legal_action_currently_required,
                    [
                        f"Elapsed {elapsed} calendar days from the {trigger_type.replace('_', ' ')} "
                        f"({exact[trigger_type].isoformat()}), which is within the merchant's own "
                        f"{promised_days}-day timeline (trigger date excluded). A delay alone is not a violation."
                    ],
                    "R4",
                )

    if pending and support is not True:
        return build(
            Outcome.informal_resolution_recommended,
            ["The refund is pending and there is no record that support has been contacted yet."],
            "R3",
        )

    if support is True and unresolved and grievance is not True:
        return build(
            Outcome.formal_grievance_recommended,
            ["Support was contacted, the issue remains unresolved, and the grievance officer has not been contacted."],
            "R5",
        )

    if grievance is True and unresolved and has_consumer_commission_route(accepted, corpus):
        return build(
            Outcome.formal_legal_proceedings_may_be_justified,
            [
                "The grievance route was attempted and remains unresolved, and the corpus contains an accepted "
                "provision about the formal Consumer Commission route. Formal proceedings may be justified, not guaranteed."
            ],
            "R6",
        )

    return build(
        Outcome.needs_more_information,
        ["The available facts do not yet support a clear next step."],
        "R7",
    )
