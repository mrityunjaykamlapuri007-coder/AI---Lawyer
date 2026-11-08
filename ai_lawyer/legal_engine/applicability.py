"""Three-valued deterministic condition evaluation (v3 Section 7.1).

TRUE / FALSE / UNKNOWN.  Absence of a fact is never proof of absence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from ai_lawyer.contracts.ids import parse_iso_date
from ai_lawyer.contracts.models import Condition, Fact, Provision


@dataclass
class TriResult:
    value: bool | None  # True / False / None (= UNKNOWN)
    reason: str

    @property
    def label(self) -> str:
        return "applicable" if self.value is True else "not_applicable" if self.value is False else "unknown"


def active_facts(facts: list[Fact]) -> list[Fact]:
    superseded = {f.supersedes_fact_id for f in facts if f.supersedes_fact_id}
    return [f for f in facts if f.fact_id not in superseded]


def _is_explicit_negation(value: Any) -> bool:
    if value is False:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"false", "no", "none", "not contacted", "not_contacted"}
    return False


def _norm(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.strip().lower().split())
    if isinstance(value, bool):
        return value
    return value


def condition_is_trusted(condition: Condition) -> bool:
    """Human-reviewed, or machine-verified with its source quote at trust level machine."""
    if condition.human_review_status == "reviewed":
        return True
    if condition.machine_review_status != "machine_verified" or not condition.source_quote.strip():
        return False
    from ai_lawyer.legal_rag.corpus_loader import trust_level  # lazy

    return trust_level() == "machine"


def evaluate_condition(condition: Condition, facts: list[Fact]) -> TriResult:
    if not condition_is_trusted(condition):
        return TriResult(
            None,
            f"condition {condition.condition_id} is neither human-reviewed nor "
            "machine-verified at the configured trust level",
        )
    if condition.operator == "manual":
        return TriResult(None, f"condition {condition.condition_id} is manual and always UNKNOWN")

    relevant = [
        f for f in active_facts(facts) if f.fact_type == condition.fact_type and f.normalised_value is not None
    ]

    if condition.operator == "exists":
        if not relevant:
            return TriResult(None, f"no fact of type {condition.fact_type}")
        positives = [f for f in relevant if not _is_explicit_negation(f.normalised_value)]
        if positives:
            return TriResult(True, f"fact {positives[-1].fact_id} records {condition.fact_type}")
        return TriResult(False, f"the only facts explicitly negate {condition.fact_type}")

    if not relevant:
        return TriResult(None, f"no fact of type {condition.fact_type}")

    values = [_norm(f.normalised_value) for f in relevant]

    if condition.operator == "equals":
        expected = _norm(condition.expected_value)
        matches = [v for v in values if v == expected]
        if matches and len(set(map(str, values))) == 1:
            return TriResult(True, f"{condition.fact_type} equals {expected!r}")
        if matches:
            return TriResult(None, f"conflicting values for {condition.fact_type}: {values}")
        return TriResult(False, f"{condition.fact_type} is {values[0]!r}, not {expected!r}")

    if condition.operator == "in":
        expected_list = [_norm(v) for v in (condition.expected_value or [])]
        matches = [v for v in values if v in expected_list]
        if matches and len(set(map(str, values))) == 1:
            return TriResult(True, f"{condition.fact_type} is in {expected_list}")
        if matches:
            return TriResult(None, f"conflicting values for {condition.fact_type}: {values}")
        return TriResult(False, f"{condition.fact_type} is {values[0]!r}, not in {expected_list}")

    if condition.operator in {"date_before", "date_after"}:
        left = parse_iso_date(values[0])
        right = parse_iso_date(condition.expected_value)
        if left is None or right is None:
            return TriResult(None, "one or both dates are not exact")
        if condition.operator == "date_before":
            return TriResult(left < right, f"{left.isoformat()} < {right.isoformat()}")
        return TriResult(left > right, f"{left.isoformat()} > {right.isoformat()}")

    return TriResult(None, f"unsupported operator {condition.operator}")


def evaluate_provision(provision: Provision, facts: list[Fact]) -> TriResult:
    if not provision.conditions:
        return TriResult(None, "no reviewed conditions in the corpus for this provision")
    results = [evaluate_condition(c, facts) for c in provision.conditions]
    if any(r.value is False for r in results):
        first = next(r for r in results if r.value is False)
        return TriResult(False, first.reason)
    if all(r.value is True for r in results):
        return TriResult(True, "; ".join(r.reason for r in results))
    unknown = [r.reason for r in results if r.value is None]
    return TriResult(None, "; ".join(unknown) or "some conditions are unknown")
