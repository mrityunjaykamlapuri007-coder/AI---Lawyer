"""UUID / time / stable-id helpers.

Provision ids are deterministic and never derived from chunk positions.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone


def new_id(prefix: str = "") -> str:
    value = str(uuid.uuid4())
    return f"{prefix}{value}" if prefix else value


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_")
    return cleaned.upper()


def make_provision_id(
    source_id: str,
    section: str | int,
    subsection: str | int | None = None,
    clause: str | int | None = None,
) -> str:
    """Canonical, chunk-independent provision id.

    Examples: ``CPA2019_S2``, ``CPA2019_S2_1``, ``RULES2020_R3_2_A``.
    """
    parts = [_slug(source_id), f"S{_slug(str(section))}"]
    if subsection is not None:
        parts.append(_slug(str(subsection)))
    if clause is not None:
        parts.append(_slug(str(clause)))
    return "_".join(parts)


def parse_iso_date(value: str | date | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None
