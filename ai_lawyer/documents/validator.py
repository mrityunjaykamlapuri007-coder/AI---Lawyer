"""Deterministic validation for generated drafts.

A draft may only contain values that are present in the fact store, a rendered
citation from an accepted corpus provision, or the explicit
``[TO BE FILLED BY USER]`` placeholder.  Anything else blocks the draft: it is
better to show the user nothing than to invent a date, amount or order id.
"""
from __future__ import annotations

import re
from typing import Any

from ai_lawyer.backend.services.fact_extractor import find_dates, parse_amount_minor
from ai_lawyer.contracts.models import Candidate, Fact
from ai_lawyer.legal_engine.applicability import active_facts
from ai_lawyer.legal_rag.corpus_loader import Corpus

PLACEHOLDER = "[TO BE FILLED BY USER]"
_ORDER_RE = re.compile(r"\b[A-Z]{2,10}-\d{2,}\b")
_AMOUNT_RE = re.compile(r"(?:INR|Rs\.?|₹)\s*([\d,]+(?:\.\d{1,2})?)", re.IGNORECASE)
_MERCHANT_LINE_RE = re.compile(r"^-\s*(?:Merchant(?: / platform)?|Merchant / platform):\s*(.+)$", re.MULTILINE)
_CITATION_LINE_RE = re.compile(r"^-\s*([^:]{3,200}):\s*\"", re.MULTILINE)


def _fact_values(facts: list[Fact], fact_types: set[str]) -> set[str]:
    values: set[str] = set()
    for fact in active_facts(facts):
        if fact.fact_type not in fact_types:
            continue
        values.add(fact.raw_value.strip())
        if fact.normalised_value is not None:
            values.add(str(fact.normalised_value).strip())
    return {v for v in values if v}


def _accepted_text(corpus: Corpus, accepted: list[Candidate]) -> str:
    parts: list[str] = []
    for cand in accepted:
        if not cand.accepted:
            continue
        provision = corpus.get(cand.provision_id)
        if provision:
            parts.append(provision.original_text)
            parts.append(provision.citation)
    return "\n".join(parts).lower()


def validate_draft_content(
    content: str,
    *,
    facts: list[Fact],
    accepted: list[Candidate],
    corpus: Corpus,
    draft_type: str,
) -> list[str]:
    """Return a list of human-readable blocking issues (empty means valid)."""
    issues: list[str] = []
    if not content.strip():
        return ["draft is empty"]
    if "DRAFT" not in content.splitlines()[0].upper():
        issues.append("draft is missing the DRAFT header")
    if "not sent" not in content.lower() and "not been sent" not in content.lower():
        issues.append("draft is missing the 'not sent or filed' notice")

    corpus_text = _accepted_text(corpus, accepted)

    order_values = _fact_values(facts, {"order_id", "transaction_id"})
    for match in _ORDER_RE.finditer(content):
        value = match.group(0)
        if value not in order_values and value.lower() not in corpus_text:
            issues.append(f"order/transaction id not in fact store: {value}")

    date_values = _fact_values(facts, {
        "purchase_date", "cancellation_date", "return_requested_date",
        "return_approved_date", "pickup_date", "refund_initiated_date",
        "support_contact_date", "grievance_contact_date",
    })
    normalised_dates = {
        str(f.normalised_value) for f in active_facts(facts)
        if f.fact_type.endswith("_date") and f.normalised_value is not None
    }
    for hit in find_dates(content):
        if hit.raw in date_values or hit.value.isoformat() in normalised_dates:
            continue
        if hit.raw.lower() in corpus_text:
            continue
        issues.append(f"date not in fact store: {hit.raw}")

    amount_values = {
        int(f.normalised_value) for f in active_facts(facts)
        if f.fact_type == "refund_amount" and isinstance(f.normalised_value, int)
    }
    for match in _AMOUNT_RE.finditer(content):
        minor = parse_amount_minor(match.group(1))
        if minor is None or minor not in amount_values:
            issues.append(f"amount not in fact store: {match.group(0)}")

    party_values = {
        str(f.normalised_value or f.raw_value).strip().lower()
        for f in active_facts(facts)
        if f.fact_type in {"merchant_name", "platform_name"}
    }
    for match in _MERCHANT_LINE_RE.finditer(content):
        value = match.group(1).strip().rstrip(".")
        if not value or value == PLACEHOLDER:
            continue
        if value.lower() not in party_values and not any(value.lower() in p or p in value.lower() for p in party_values):
            issues.append(f"merchant/platform not in fact store: {value}")

    accepted_citations = {
        (corpus.get(c.provision_id).citation if corpus.get(c.provision_id) else "")
        for c in accepted
        if c.accepted
    }
    accepted_citations = {c for c in accepted_citations if c}
    for match in _CITATION_LINE_RE.finditer(content):
        citation = match.group(1).strip()
        if citation not in accepted_citations:
            issues.append(f"legal citation is not an accepted provision: {citation}")

    return issues
