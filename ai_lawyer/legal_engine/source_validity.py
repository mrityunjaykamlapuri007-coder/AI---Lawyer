"""Source-version validity (three-valued date logic, v3 Section 7.2)."""
from __future__ import annotations

from datetime import date

from ai_lawyer.contracts.models import Source, SourceValidity


def evaluate_source_validity(
    source: Source, as_of_date: date | None
) -> tuple[SourceValidity, str]:
    if as_of_date is None:
        return "uncertain", "as_of_date is unknown"
    if source.version_status == "uncertain":
        return "uncertain", "source version status is uncertain"
    if source.effective_from is None and source.effective_to is None:
        return "uncertain", "source has no effective dates"
    if source.effective_from is not None and source.effective_from > as_of_date:
        return (
            "not_yet_effective",
            f"effective from {source.effective_from.isoformat()}, after {as_of_date.isoformat()}",
        )
    if source.effective_to is not None and source.effective_to < as_of_date:
        return (
            "superseded",
            f"effective to {source.effective_to.isoformat()}, before {as_of_date.isoformat()}",
        )
    if source.version_status == "superseded":
        return "superseded", "source is marked superseded"
    if source.version_status == "future":
        return "not_yet_effective", "source is marked future"
    return "current_for_date", f"source was in force on {as_of_date.isoformat()}"
