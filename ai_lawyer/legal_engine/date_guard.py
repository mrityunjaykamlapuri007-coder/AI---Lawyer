"""Date / deadline guard: numeric day claims must be backed by Python values.

Any sentence containing a day-count not supplied by a fact or computed by Python
is removed.  Any bare "deadline" sentence without a backed date is removed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from ai_lawyer.contracts.models import LegalDraft

_DAY_RE = re.compile(r"\b(\d+)\s*(?:calendar\s+|business\s+)?days?\b", re.IGNORECASE)
_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{1,2}\s+[A-Z][a-z]+\s+\d{4}|[A-Z][a-z]+\s+\d{1,2},?\s+\d{4})\b"
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass
class DateGuardResult:
    draft: LegalDraft
    blocked_claims: list[dict[str, Any]] = field(default_factory=list)


def _sentence_is_backed(
    sentence: str,
    allowed_numbers: set[int],
    allowed_dates: set[str],
    blocked: list[dict[str, Any]],
) -> bool:
    for match in _DAY_RE.finditer(sentence):
        number = int(match.group(1))
        if number not in allowed_numbers:
            blocked.append(
                {
                    "type": "unbacked_deadline",
                    "detail": f"removed unbacked day-count '{match.group(0)}'",
                }
            )
            return False
    for match in _DATE_RE.finditer(sentence):
        if match.group(0) not in allowed_dates:
            blocked.append(
                {
                    "type": "unbacked_date",
                    "detail": f"removed unbacked date '{match.group(0)}'",
                }
            )
            return False
    if re.search(r"\bdeadline\b", sentence, re.IGNORECASE) and not _DAY_RE.search(sentence):
        if not any(d in sentence for d in allowed_dates):
            blocked.append(
                {"type": "unbacked_deadline", "detail": "removed unbacked deadline sentence"}
            )
            return False
    return True


def _clean_text(
    text: str,
    allowed_numbers: set[int],
    allowed_dates: set[str],
    blocked: list[dict[str, Any]],
) -> str:
    if not text:
        return text
    pieces = _SENTENCE_SPLIT.split(text)
    kept = [p for p in pieces if _sentence_is_backed(p, allowed_numbers, allowed_dates, blocked)]
    return " ".join(kept).strip() if len(kept) != len(pieces) else text


def _fields(draft: LegalDraft) -> Iterable[tuple[str, Any, str]]:
    yield "issue_summary", lambda v: setattr(draft, "issue_summary", v), draft.issue_summary
    yield "proposed_next_step", lambda v: setattr(draft, "proposed_next_step", v), draft.proposed_next_step
    for name in (
        "user_reported_facts",
        "document_supported_facts",
        "missing_facts",
        "assumptions",
        "uncertainties",
        "possible_options",
    ):
        values = getattr(draft, name)
        for i, value in enumerate(list(values)):
            yield f"{name}[{i}]", (lambda v, arr=values, idx=i: arr.__setitem__(idx, v)), value


def validate_dates(
    draft: LegalDraft,
    allowed_numbers: set[int],
    allowed_dates: set[str],
) -> DateGuardResult:
    blocked: list[dict[str, Any]] = []
    clean = draft.model_copy(deep=True)
    for _name, setter, value in _fields(clean):
        setter(_clean_text(value, allowed_numbers, allowed_dates, blocked))
    return DateGuardResult(draft=clean, blocked_claims=blocked)
