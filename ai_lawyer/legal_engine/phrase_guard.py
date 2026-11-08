"""Forbidden-phrase guard.

Assertions of violation, guilt, certainty or guaranteed outcomes are rewritten
to conditional wording.  Every rewrite is logged and surfaced as a blocked claim.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ai_lawyer.contracts.models import LegalDraft

# (pattern, replacement, label).  Order matters.
_PATTERNS: list[tuple[str, str, str]] = [
    (r"\byou will definitely win\b", "the outcome is not guaranteed", "guaranteed_outcome"),
    (r"\byou will win\b", "the outcome is not guaranteed", "guaranteed_outcome"),
    (r"\bI guarantee\b", "I cannot guarantee", "guarantee"),
    (r"\bwe guarantee\b", "we cannot guarantee", "guarantee"),
    (r"(?<!not )\bguaranteed\b", "not guaranteed", "guarantee"),
    (r"\bbroke the law\b", "may not have met the applicable requirement", "violation_claim"),
    (r"\bviolated the law\b", "may not be consistent with the applicable requirement", "violation_claim"),
    (r"\bviolated\b", "may not be consistent with the applicable requirement", "violation_claim"),
    (r"\billegal\b", "potentially inconsistent with the law", "violation_claim"),
    (r"\bthe seller is guilty\b", "the seller's responsibility is not established", "guilt_claim"),
    (r"\bthe marketplace is guilty\b", "the marketplace's responsibility is not established", "guilt_claim"),
    (r"\bguilty\b", "responsibility is not established", "guilt_claim"),
    (r"\bthe seller is lying\b", "the parties' accounts differ", "guilt_claim"),
    (r"\byou should sue\b", "you may wish to get legal advice about formal options", "advice_claim"),
    (r"\bdefinitely\b", "possibly", "certainty"),
]


@dataclass
class PhraseGuardResult:
    draft: LegalDraft
    rewrites: list[dict[str, Any]] = field(default_factory=list)


def scan_text(text: str) -> tuple[str, list[dict[str, Any]]]:
    rewrites: list[dict[str, Any]] = []
    out = text or ""
    for pattern, replacement, label in _PATTERNS:
        new, count = re.subn(pattern, replacement, out, flags=re.IGNORECASE)
        if count:
            rewrites.append({"type": "phrase_rewritten", "label": label, "count": count})
            out = new
    return out, rewrites


def sanitize_text(text: str) -> str:
    return scan_text(text)[0]


def _all_fields(draft: LegalDraft):
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
    for i, item in enumerate(draft.application_analysis):
        yield (
            f"application_analysis[{i}].conditional_statement",
            (lambda v, it=item: setattr(it, "conditional_statement", v)),
            item.conditional_statement,
        )


def sanitize_draft(draft: LegalDraft) -> PhraseGuardResult:
    rewrites: list[dict[str, Any]] = []
    clean = draft.model_copy(deep=True)
    for _name, setter, value in _all_fields(clean):
        new, found = scan_text(value)
        if found:
            setter(new)
            rewrites.extend(found)
    return PhraseGuardResult(draft=clean, rewrites=rewrites)
