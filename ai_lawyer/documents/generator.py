"""Draft generation for support_request and formal_grievance.

Facts come from the fact store only.  Missing mandatory fields become
``[TO BE FILLED BY USER]``.  Legal grounds list only accepted provisions, with
citations rendered from the corpus.  Nothing is ever sent.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ai_lawyer.contracts.errors import UserSafeError
from ai_lawyer.contracts.models import Candidate, DocumentDraft, Fact
from ai_lawyer.documents.validator import validate_draft_content
from ai_lawyer.legal_engine.applicability import active_facts
from ai_lawyer.legal_rag.corpus_loader import Corpus

TEMPLATE_DIR = Path(__file__).with_name("templates")
PLACEHOLDER = "[TO BE FILLED BY USER]"
SUPPORTED = {"support_request", "formal_grievance"}


def _latest(facts: list[Fact], fact_type: str):
    items = [f for f in active_facts(facts) if f.fact_type == fact_type and f.normalised_value is not None]
    return items[-1].normalised_value if items else None


def _money(minor: int | None) -> str:
    # Anything that is not integer minor units becomes a placeholder, never a crash.
    if minor is None or isinstance(minor, bool) or not isinstance(minor, int):
        return PLACEHOLDER
    return f"INR {minor / 100:,.2f}"


def _date_values(facts: list[Fact]) -> str:
    labels = {
        "purchase_date": "purchase",
        "cancellation_date": "cancellation",
        "return_requested_date": "return requested",
        "return_approved_date": "return approved",
        "pickup_date": "pickup",
        "refund_initiated_date": "refund initiated",
        "support_contact_date": "support contacted",
        "grievance_contact_date": "grievance contacted",
    }
    items = []
    for fact in active_facts(facts):
        if fact.fact_type in labels:
            items.append(f"{labels[fact.fact_type]}: {fact.raw_value}")
    return "; ".join(items) if items else PLACEHOLDER


def _summary(facts: list[Fact]) -> str:
    active = active_facts(facts)
    if not active:
        return PLACEHOLDER
    lines = []
    for fact in active:
        if fact.fact_type in {"order_id", "transaction_id", "merchant_name", "platform_name"}:
            continue
        value = fact.normalised_value if fact.normalised_value is not None else fact.raw_value
        source = "document" if fact.source_type == "evidence" else "you"
        page = f", page {fact.page_number}" if fact.page_number else ""
        lines.append(f"- {fact.fact_type.replace('_', ' ')}: {value} (reported by {source}{page})")
    return "\n".join(lines) if lines else PLACEHOLDER


def generate_document(
    *,
    draft_type: str,
    case_id: str,
    facts: list[Fact],
    accepted: list[Candidate],
    corpus: Corpus,
) -> DocumentDraft:
    if draft_type not in SUPPORTED:
        raise UserSafeError(
            "document_type_not_supported",
            "That document type is not supported by the current corpus or build.",
            status_code=400,
        )

    merchant = _latest(facts, "merchant_name") or PLACEHOLDER
    platform = _latest(facts, "platform_name")
    order_id = _latest(facts, "order_id") or PLACEHOLDER
    amount = _money(_latest(facts, "refund_amount"))
    status = _latest(facts, "refund_status") or PLACEHOLDER
    support = _latest(facts, "support_contact_made")
    support_text = "yes" if support is True else "no" if support is False else PLACEHOLDER

    legal_grounds = []
    for cand in accepted:
        if not cand.accepted:
            continue
        provision = corpus.get(cand.provision_id)
        if not provision:
            continue
        legal_grounds.append(
            {
                "citation": provision.citation,
                "excerpt": provision.original_text[:600],
            }
        )

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(f"{draft_type}.md.j2")
    content = template.render(
        merchant=merchant,
        platform_line=f"Platform: {platform}" if platform else "",
        order_id=order_id,
        amount=amount,
        status=status,
        refund_status=status,
        support_contact=support_text,
        dates=_date_values(facts),
        summary=_summary(facts),
        user_name=PLACEHOLDER,
        address=PLACEHOLDER,
        legal_grounds=legal_grounds,
    )

    issues = validate_draft_content(
        content, facts=facts, accepted=accepted, corpus=corpus, draft_type=draft_type
    )
    if issues:
        raise UserSafeError(
            "draft_validation_failed",
            "The draft was blocked because it contained a value that is not in the fact store.",
            status_code=400,
            details={"issues": issues},
        )

    missing = [PLACEHOLDER] if PLACEHOLDER in content else []
    return DocumentDraft(
        case_id=case_id,
        draft_type=draft_type,  # type: ignore[arg-type]
        content=content,
        status="needs_review",
        missing_fields=missing,
    )
