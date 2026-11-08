"""Machine verification of agent-drafted applicability conditions.

A condition is accepted (``machine_review_status: machine_verified``) only if:

1. its ``source_quote`` is an exact (whitespace-normalised) substring of the
   provision text, and the provision itself is machine- or human-verified;
2. its fact type is one the fact extractor can produce, and any expected value
   is in that fact type's vocabulary;
3. it passes the 3-case test table: an applicable, a not-applicable and an
   unknown fact set, whose expected results are derived from the operator rule
   (not from an LLM).  ``manual`` conditions must give UNKNOWN in all three.

A condition that fails is written as ``unreviewed`` with the reason, so it can
never evaluate to TRUE or FALSE.  Nothing here is human review.

Usage::

    python -m ai_lawyer.legal_rag.machine_conditions            # report only
    python -m ai_lawyer.legal_rag.machine_conditions --apply    # write to staging
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_lawyer.contracts.models import ALLOWED_FACT_TYPES, Condition, Fact
from ai_lawyer.legal_rag.machine_verify import DEFAULT_STAGING, OUT_DIR

PACKAGE_DIR = Path(__file__).resolve().parents[1]
CONDITIONS_FILE = PACKAGE_DIR / "legal_corpus" / "official" / "conditions" / "agent_conditions.json"
METHOD = "machine-conditions-1.0"

BOOLEAN_FACTS = frozenset({"support_contact_made", "grievance_officer_contacted", "bank_credit_confirmed"})
DATE_FACTS = frozenset(t for t in ALLOWED_FACT_TYPES if t.endswith("_date"))


def refund_status_vocabulary() -> list[str]:
    from ai_lawyer.backend.services.fact_extractor import _STATUS_PATTERNS  # lazy

    return [name for name, _ in _STATUS_PATTERNS]


def _vocabulary(fact_type: str) -> list[Any] | None:
    if fact_type == "refund_status":
        return refund_status_vocabulary()
    if fact_type in BOOLEAN_FACTS:
        return [True, False]
    return None  # open values (names, ids, dates, amounts)


def _sample_present(fact_type: str) -> Any:
    if fact_type in BOOLEAN_FACTS:
        return True
    if fact_type in DATE_FACTS:
        return "2026-10-01"
    if fact_type in {"refund_amount", "merchant_promised_timeline_days"}:
        return 100
    return "test value"


def _fact(fact_type: str, value: Any) -> Fact:
    return Fact(
        case_id="condition-test",
        fact_type=fact_type,
        raw_value=str(value),
        normalised_value=value,
        source_type="user_message",
        source_id="condition-test",
        status="user_reported",
    )


def _norm(text: str) -> str:
    return " ".join(text.split())


def condition_test_table(condition: Condition) -> tuple[bool, list[dict[str, Any]]]:
    """Run the 3-case table.  Expected values come from the operator rule."""
    from ai_lawyer.legal_engine.applicability import evaluate_condition

    probe = condition.model_copy(update={"machine_review_status": "machine_verified"})
    cases: list[tuple[str, list[Fact], bool | None]] = []
    ftype = condition.fact_type
    if condition.operator == "manual":
        cases = [
            ("applicable", [_fact(ftype, _sample_present(ftype))], None),
            ("not_applicable", [_fact(ftype, False)], None),
            ("unknown", [], None),
        ]
    elif condition.operator == "exists":
        cases = [
            ("applicable", [_fact(ftype, _sample_present(ftype))], True),
            ("not_applicable", [_fact(ftype, False)], False),
            ("unknown", [], None),
        ]
    elif condition.operator in {"in", "equals"}:
        expected = (
            list(condition.expected_value)
            if condition.operator == "in"
            else [condition.expected_value]
        )
        outside = [v for v in (_vocabulary(ftype) or []) if v not in expected]
        if not outside:
            return False, [{"case": "setup", "error": "no vocabulary value outside the expected set"}]
        cases = [
            ("applicable", [_fact(ftype, expected[0])], True),
            ("not_applicable", [_fact(ftype, outside[0])], False),
            ("unknown", [], None),
        ]
    else:
        return False, [{"case": "setup", "error": f"operator {condition.operator} has no test table"}]

    rows: list[dict[str, Any]] = []
    passed = True
    for name, facts, want in cases:
        got = evaluate_condition(probe, facts).value
        ok = got is want
        passed &= ok
        rows.append({"case": name, "expected": want, "got": got, "pass": ok})
    return passed, rows


def validate(condition: Condition, provision: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if provision.get("review_status") not in {"machine_verified", "human_verified"}:
        problems.append("provision is not verified")
    quote = _norm(condition.source_quote)
    if not quote:
        problems.append("no source quote")
    elif quote not in _norm(str(provision.get("original_text", ""))):
        problems.append("source quote is not in the provision text")
    if condition.fact_type not in ALLOWED_FACT_TYPES:
        problems.append(f"fact type {condition.fact_type!r} is not extractable")
    vocabulary = _vocabulary(condition.fact_type)
    if condition.operator in {"in", "equals"} and vocabulary is not None:
        values = condition.expected_value if condition.operator == "in" else [condition.expected_value]
        unknown = [v for v in values or [] if v not in vocabulary]
        if unknown:
            problems.append(f"expected values {unknown} are not in the {condition.fact_type} vocabulary")
    if condition.fact_type in BOOLEAN_FACTS and condition.operator not in {"exists", "manual"}:
        problems.append("boolean facts use 'exists' (explicit false gives FALSE)")
    return problems


def run(staging: Path, *, apply: bool, conditions_file: Path = CONDITIONS_FILE) -> dict[str, Any]:
    drafted = json.loads(conditions_file.read_text(encoding="utf-8"))["conditions"]
    path = staging / "draft_provisions.json"
    provisions = json.loads(path.read_text(encoding="utf-8"))
    by_id = {p["provision_id"]: p for p in provisions}
    report: dict[str, Any] = {
        "method": METHOD,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "conditions_file": conditions_file.name,
        "provisions": {},
    }
    for provision_id, items in drafted.items():
        provision = by_id.get(provision_id)
        entries = []
        written: list[dict[str, Any]] = []
        for item in items:
            condition = Condition.model_validate(
                {**item, "drafted_by": "agent", "human_review_status": "unreviewed"}
            )
            problems = validate(condition, provision) if provision else ["unknown provision"]
            table_ok, table = (False, []) if problems else condition_test_table(condition)
            accepted = not problems and table_ok
            entries.append(
                {
                    "condition_id": condition.condition_id,
                    "accepted": accepted,
                    "problems": problems,
                    "condition_test_table": table,
                }
            )
            written.append(
                condition.model_copy(
                    update={"machine_review_status": "machine_verified" if accepted else "unreviewed"}
                ).model_dump(mode="json")
            )
        report["provisions"][provision_id] = entries
        if apply and provision is not None:
            provision["conditions"] = written
    if apply:
        path.write_text(json.dumps(provisions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "conditions_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ai_lawyer.legal_rag.machine_conditions")
    parser.add_argument("--staging-dir", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    report = run(args.staging_dir, apply=args.apply)
    total = accepted = 0
    for provision_id, entries in report["provisions"].items():
        for entry in entries:
            total += 1
            accepted += entry["accepted"]
            status = "ACCEPT" if entry["accepted"] else "REJECT " + "; ".join(entry["problems"] or ["test table failed"])
            print(f"{entry['condition_id']}: {status}")
    print(f"{'applied' if args.apply else 'checked'}: {accepted}/{total} conditions machine_verified")
    return 0 if accepted == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
