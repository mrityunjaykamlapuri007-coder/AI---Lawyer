"""Split a staged rule into its numbered sub-rules.

An amendment that substitutes one sub-rule makes V6 reject the whole rule,
which also hides the sub-rules the amendment never touched.  Splitting lets
each sub-rule be verified on its own.

Rules:

* each child's text is an exact contiguous slice of the parent's stored text;
  the slices are recorded and together cover the parent text completely;
* sub-rule numbers must run 1, 2, 3, ... with no gap, or nothing is split;
* children start ``unverified`` and must pass machine verification (V1-V6);
* the parent row is kept unchanged (it stays rejected by V6) so nothing is lost.

Usage::

    python -m ai_lawyer.legal_rag.subrule_split --provision ECR_2020_P004
    python -m ai_lawyer.legal_rag.subrule_split --provision ECR_2020_P004 --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_lawyer.legal_rag.machine_verify import DEFAULT_STAGING

METHOD = "subrule-split-1.0"
_SUBRULE_START = re.compile(r"(?m)^[ \t]*\((\d{1,2})\)")
# A heading line ending in a dash (any dash or a replacement glyph), then "(1)".
_INLINE_FIRST = re.compile(r"(?m)^\d+\.[^\n]*?[\-–—�:]\s*(\(1\))")


def split_points(text: str) -> list[tuple[int, int]]:
    """Return [(sub_rule_number, start_offset)], or [] if numbering is not 1..n."""
    points = [(int(m.group(1)), m.start(1) - 1) for m in _SUBRULE_START.finditer(text)]
    if points and points[0][0] == 2:
        # "6. Duties of sellers. – (1) No seller ..." puts (1) on the heading
        # line, right after the heading's dash.
        inline = _INLINE_FIRST.search(text[: points[0][1]])
        if inline:
            points.insert(0, (1, inline.start(1)))
    if len(points) < 2 or [n for n, _ in points] != list(range(1, len(points) + 1)):
        return []
    return points


def split_text(text: str) -> list[dict[str, Any]]:
    points = split_points(text)
    if not points:
        return []
    pieces: list[dict[str, Any]] = []
    for index, (number, start) in enumerate(points):
        # The rule heading before "(1)" belongs to sub-rule (1).
        begin = 0 if index == 0 else start
        end = points[index + 1][1] if index + 1 < len(points) else len(text)
        pieces.append({"sub_rule": number, "start": begin, "end": end, "text": text[begin:end].strip()})
    assert "".join(text[p["start"]:p["end"]] for p in pieces) == text
    return pieces


def make_children(parent: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(parent["original_text"])
    pieces = split_text(text)
    parent_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    heading = text[: split_points(text)[0][1]].strip() if pieces else ""
    children: list[dict[str, Any]] = []
    for piece in pieces:
        child = deepcopy(parent)
        child["provision_id"] = f"{parent['provision_id']}_SR{piece['sub_rule']:02d}"
        child["citation"] = f"{parent['citation']}, sub-rule ({piece['sub_rule']})"
        child["hierarchy_type"] = "subsection"
        # The parent stays rejected and never reaches the runtime corpus, so
        # linking to it would leave a dangling id; the split is recorded instead.
        child["parent_provision_id"] = None
        child["original_text"] = piece["text"]
        child["search_text"] = f"{heading} {child['citation']}".strip()
        child["review_status"] = "unverified"
        child["verified_by"] = None
        child["verified_at"] = None
        child["verification_evidence"] = {}
        child["verification_method_count"] = 0
        child["review_note"] = None
        child["boundary_adjustment"] = {
            "method": METHOD,
            "split_from": parent["provision_id"],
            "parent_sha256": parent_sha,
            "slice": [piece["start"], piece["end"]],
            "applied_at": datetime.now(timezone.utc).isoformat(),
        }
        children.append(child)
    return children


def apply_split(staging: Path, provision_id: str, *, apply: bool) -> list[dict[str, Any]]:
    path = staging / "draft_provisions.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    index = next((i for i, r in enumerate(rows) if r.get("provision_id") == provision_id), None)
    if index is None:
        raise KeyError(f"unknown provision_id: {provision_id}")
    children = make_children(rows[index])
    if not children:
        return []
    existing = {r["provision_id"] for r in rows}
    clash = [c["provision_id"] for c in children if c["provision_id"] in existing]
    if clash:
        raise ValueError(f"already split: {', '.join(clash)}")
    if apply:
        rows[index + 1 : index + 1] = children
        path.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return children


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ai_lawyer.legal_rag.subrule_split")
    parser.add_argument("--provision", required=True)
    parser.add_argument("--staging-dir", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        children = apply_split(args.staging_dir, args.provision, apply=args.apply)
    except (KeyError, ValueError) as exc:
        print(f"REFUSED: {exc}")
        return 2
    if not children:
        print("REFUSED: sub-rule numbering is not a clean 1..n sequence; nothing split")
        return 2
    for child in children:
        first = re.sub(r"\s+", " ", child["original_text"])[:80]
        print(f"{child['provision_id']}: {len(child['original_text'])} chars | {first}")
    print(f"{'applied' if args.apply else 'proposed'}: {len(children)} sub-rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
