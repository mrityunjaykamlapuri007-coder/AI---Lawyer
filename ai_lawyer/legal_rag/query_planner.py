"""Deterministic query planning.

The original query is never overwritten.  Expansions come from a small,
hand-written refund vocabulary (generic terms only, never legal claims).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from ai_lawyer.contracts.models import Fact

REFUND_VOCAB: dict[str, list[str]] = {
    "refund": ["refund not received", "money back pending", "payment refund"],
    "return": ["returned goods refund", "return pickup refund"],
    "cancellation": ["cancelled order refund", "cancellation refund pending"],
    "delay": ["refund delayed", "refund pending", "money not received"],
    "denied": ["refund refused", "refund rejected", "return rejected"],
    "partial": ["partial refund", "short refund", "deduction from refund"],
    "grievance": ["grievance officer complaint", "customer care escalation", "written complaint"],
    "seller": ["seller responsibility", "merchant refund"],
    "platform": ["marketplace responsibility", "platform intermediary", "e-commerce platform complaint"],
    "payment": ["payment provider refund", "bank refund", "upi card refund"],
}

_DATE_FACT_TYPES = (
    "purchase_date",
    "cancellation_date",
    "return_requested_date",
    "return_approved_date",
    "pickup_date",
    "refund_initiated_date",
    "support_contact_date",
    "grievance_contact_date",
)


@dataclass
class QueryPlan:
    original_query: str
    self_contained_query: str
    expansions: list[str] = field(default_factory=list)
    issue_tags: list[str] = field(default_factory=list)
    reason_per_expansion: dict[str, str] = field(default_factory=dict)
    include_original: bool = True

    def variants(self, include_expansions: bool = True) -> list[str]:
        items = [self.original_query] if self.include_original else []
        items.append(self.self_contained_query)
        if include_expansions:
            items.extend(self.expansions)
        return list(dict.fromkeys(x.strip() for x in items if x and x.strip()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_query": self.original_query,
            "self_contained_query": self.self_contained_query,
            "expansions": list(self.expansions),
            "issue_tags": list(self.issue_tags),
            "reason_per_expansion": dict(self.reason_per_expansion),
        }


def _latest_value(facts: Iterable[Fact], fact_type: str):
    vals = [f for f in facts if f.fact_type == fact_type and f.normalised_value is not None]
    if not vals:
        return None
    vals.sort(key=lambda f: f.created_at)
    return vals[-1].normalised_value


def _detect_tags(message: str, facts: list[Fact]) -> list[str]:
    text = message.lower()
    status = str(_latest_value(facts, "refund_status") or "").lower()
    tags: list[str] = []

    def add(tag: str) -> None:
        if tag not in tags:
            tags.append(tag)

    if status in {"not_received", "pending", "initiated", "processed"}:
        add("delay")
    if status == "denied" or any(w in text for w in ("denied", "refused", "rejected")):
        add("denied")
    if status == "partial" or any(w in text for w in ("partial", "only", "deducted", "short")):
        add("partial")
    if _latest_value(facts, "support_contact_made") or any(
        w in text for w in ("support", "customer care", "complaint", "grievance", "emailed")
    ):
        add("grievance")
    if any(w in text for w in ("cancel", "cancelled", "canceled")):
        add("cancellation")
    if any(w in text for w in ("return", "returned", "pickup")):
        add("return")
    if any(w in text for w in ("marketplace", "platform", "seller", "intermediary")):
        add("seller")
        add("platform")
    if any(w in text for w in ("upi", "bank", "card", "payment", "wallet")):
        add("payment")
    if not tags:
        add("refund")
    return tags


def plan_query(
    message: str,
    facts: list[Fact],
    case_summary: dict[str, Any] | None = None,
    max_expansions: int = 3,
) -> QueryPlan:
    original = message or ""
    case_summary = case_summary or {}

    parts: list[str] = ["e-commerce refund dispute India"]
    merchant = _latest_value(facts, "merchant_name") or case_summary.get("merchant")
    if merchant:
        parts.append(f"merchant {merchant}")
    platform = _latest_value(facts, "platform_name")
    if platform:
        parts.append(f"platform {platform}")
    order_id = _latest_value(facts, "order_id")
    if order_id:
        parts.append(f"order {order_id}")
    status = _latest_value(facts, "refund_status")
    if status:
        parts.append(f"refund status {status}")
    amount = _latest_value(facts, "refund_amount")
    if amount:
        parts.append("refund amount stated in the case")
    for ft in _DATE_FACT_TYPES:
        value = _latest_value(facts, ft)
        if value:
            parts.append(f"{ft.replace('_', ' ')} {value}")
    if _latest_value(facts, "support_contact_made") is True:
        parts.append("support already contacted")
    if _latest_value(facts, "grievance_officer_contacted") is True:
        parts.append("grievance officer contacted")

    self_contained = "; ".join(parts)
    if len(parts) == 1 and original.strip():
        # No structured facts: keep the user's own issue wording, but never
        # promote an allegation into a fact.
        self_contained = f"{self_contained}; issue described by user as: {original.strip()}"

    tags = _detect_tags(original, facts)
    expansions: list[str] = []
    reasons: dict[str, str] = {}
    for tag in tags:
        for phrase in REFUND_VOCAB.get(tag, []):
            if phrase not in expansions and phrase != original.strip():
                expansions.append(phrase)
                reasons[phrase] = f"issue tag: {tag}"
            if len(expansions) >= max_expansions:
                break
        if len(expansions) >= max_expansions:
            break

    # Ordered dedup, stable across runs.
    expansions = list(dict.fromkeys(expansions))[:max_expansions]
    return QueryPlan(
        original_query=original,
        self_contained_query=self_contained,
        expansions=expansions,
        issue_tags=tags,
        reason_per_expansion=reasons,
    )
