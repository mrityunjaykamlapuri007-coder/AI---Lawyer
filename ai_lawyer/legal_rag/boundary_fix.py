"""Ingestion boundary fix: end a provision before a trailing non-law block.

The draft ingest sometimes carried text past the end of the last rule: the
file number, the signatory line, the digital-signature stamp, or the heading of
the next chapter.  V5 rejects such provisions.  This step corrects the segment
boundary; it does not edit law.

Rules:

* the kept text is an exact prefix of the stored text (nothing rewritten);
* the cut is at the first line that is a non-law marker, and only when the kept
  text ends in sentence punctuation and contains no non-law marker;
* the removed text is stored verbatim in ``boundary_adjustment`` with the
  original text's SHA-256;
* the provision is reset to ``unverified`` and must pass machine verification
  (V1-V6) again from scratch.

Usage::

    python -m ai_lawyer.legal_rag.boundary_fix            # list proposals
    python -m ai_lawyer.legal_rag.boundary_fix --apply    # write to staging
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_lawyer.legal_rag.machine_verify import (
    _HEADING_WORDS,
    _NON_LAW_PATTERNS,
    DEFAULT_STAGING,
    non_law_markers,
)

METHOD = "boundary-fix-1.0"
_END_PUNCTUATION = (".", ";", ":", "”", '"', ".”", ";”")


_STAMP_NAME = re.compile(r"[A-Z]{2,}(?: [A-Z]{2,})*")
_STAMP_TIME = re.compile(r"(?:\d{1,2}:\d{2}:\d{2}\s*)?[+-]\d{2}'\d{2}'")
_CHAPTER = re.compile(r"CHAPTER [IVXLC]+")


def _line_is_marker(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _CHAPTER.fullmatch(stripped):
        return True
    return any(pattern.search(stripped) for _, pattern in _NON_LAW_PATTERNS)


def _removable(lines: list[str]) -> bool:
    """Every removed line must itself be non-law, or nothing is removed."""
    previous_chapter = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _line_is_marker(stripped):
            previous_chapter = bool(_CHAPTER.fullmatch(stripped))
            continue
        if _STAMP_TIME.fullmatch(stripped):
            continue
        # A digital-signature name, or the title printed under a CHAPTER line.
        if _STAMP_NAME.fullmatch(stripped) and not stripped.startswith(
            tuple(w for w in _HEADING_WORDS if w != "CHAPTER")
        ):
            previous_chapter = False
            continue
        return False
    return True


def propose_trim(text: str) -> dict[str, Any] | None:
    """Return the trim for ``text``, or ``None`` if no safe trim exists."""
    if not non_law_markers(text):
        return None
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if index == 0 or not _line_is_marker(line):
            continue
        kept = "".join(lines[:index]).rstrip()
        removed = "".join(lines[index:])
        if not _removable(lines[index:]):
            return None
        if not kept.endswith(_END_PUNCTUATION):
            return None
        if non_law_markers(kept):
            return None
        assert text.startswith(kept)
        return {"kept": kept, "removed": removed, "markers": non_law_markers(text)}
    return None


def apply_to_staging(staging: Path, *, apply: bool) -> list[dict[str, Any]]:
    path = staging / "draft_provisions.json"
    provisions = json.loads(path.read_text(encoding="utf-8"))
    changes: list[dict[str, Any]] = []
    for row in provisions:
        text = str(row.get("original_text", ""))
        trim = propose_trim(text)
        if trim is None:
            if non_law_markers(text):
                changes.append({"provision_id": row["provision_id"], "action": "no_safe_trim"})
            continue
        changes.append(
            {
                "provision_id": row["provision_id"],
                "action": "trim",
                "removed": trim["removed"],
                "markers": trim["markers"],
            }
        )
        if apply:
            row["boundary_adjustment"] = {
                "method": METHOD,
                "removed_text": trim["removed"],
                "markers": trim["markers"],
                "original_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "applied_at": datetime.now(timezone.utc).isoformat(),
            }
            row["original_text"] = trim["kept"]
            # Must re-earn verification on the new boundary.
            row["review_status"] = "unverified"
            row["verified_by"] = None
            row["verified_at"] = None
            row["verification_evidence"] = {}
            row["verification_method_count"] = 0
            row["review_note"] = "boundary adjusted at ingestion; must re-pass machine verification"
    if apply and any(c["action"] == "trim" for c in changes):
        path.write_text(json.dumps(provisions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ai_lawyer.legal_rag.boundary_fix")
    parser.add_argument("--staging-dir", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    changes = apply_to_staging(args.staging_dir, apply=args.apply)
    for change in changes:
        if change["action"] == "trim":
            removed = re.sub(r"\s+", " ", change["removed"]).strip()
            print(f"{change['provision_id']}: trim {change['markers']} removed={removed!r}")
        else:
            print(f"{change['provision_id']}: NO SAFE TRIM (stays rejected)")
    trims = sum(1 for c in changes if c["action"] == "trim")
    print(f"{'applied' if args.apply else 'proposed'}: {trims} trim(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
