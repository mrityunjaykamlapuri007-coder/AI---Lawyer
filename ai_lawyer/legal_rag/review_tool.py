"""Human review CLI for the staged legal corpus.

Only a human can approve a provision.  This tool makes that review fast and
safe; it never invents text, dates, citations or conditions.  It writes to the
staging directory (``official/draft_curated``) and never to the runtime corpus.
The runtime files are built separately by
``python -m ai_lawyer.legal_rag.build_runtime_corpus`` from approved rows only.

Commands
--------
``list``
    Show provision ids and review state, optionally for one source.
``show <provision_id>``
    Print the stored verbatim text, page, document hash, and the path to the
    original PDF so it can be opened beside the text.
``approve <provision_id> --reviewer NAME``
    Approve exactly one provision.  Requires the reviewer to type the
    provision id again.  There is no batch mode and no ``--all``.
``reject <provision_id> --note TEXT``
    Record a rejection reason.  The provision stays unusable.
``source-approve <source_id> --reviewer NAME``
    Approve a source, but only when its provenance fields are complete and its
    version status is not ``uncertain``.  Missing fields are printed exactly.

Exit codes: 0 success, 2 refusal (nothing written).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ai_lawyer.contracts.models import Provision, Source

PACKAGE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_STAGING = PACKAGE_DIR / "legal_corpus" / "official" / "draft_curated"
ORIGINALS_DIR = PACKAGE_DIR / "legal_corpus" / "official" / "originals"
EXTRACTED_DIR = PACKAGE_DIR / "legal_corpus" / "official" / "extracted_en"

SOURCES_FILE = "draft_sources.json"
PROVISIONS_FILE = "draft_provisions.json"

# Required before a source can be approved.  ``reviewed_by`` is the reviewer
# supplied to this command; the rest must already be true in the staging data.
SOURCE_APPROVAL_FIELDS = (
    "publisher",
    "official_url",
    "published_date",
    "document_sha256",
)


class Refusal(Exception):
    """A review action that must not be applied."""


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
def load_sources(staging: Path) -> list[dict[str, Any]]:
    path = staging / SOURCES_FILE
    if not path.exists():
        raise Refusal(f"missing staging file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_provisions(staging: Path) -> list[dict[str, Any]]:
    path = staging / PROVISIONS_FILE
    if not path.exists():
        raise Refusal(f"missing staging file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


def save(staging: Path, sources: list[dict], provisions: list[dict]) -> None:
    # Validate against the runtime schema before writing: the staging files
    # must stay loadable by the corpus loader.
    for item in sources:
        Source.model_validate(item)
    for item in provisions:
        Provision.model_validate(item)
    _atomic_write_json(staging / SOURCES_FILE, sources)
    _atomic_write_json(staging / PROVISIONS_FILE, provisions)
    refresh_worksheets(staging, sources, provisions)


def refresh_worksheets(
    staging: Path, sources: list[dict], provisions: list[dict]
) -> None:
    """Keep the CSV worksheets in step with the JSON that the tool edits."""
    provisions_csv = staging / "provisions_review.csv"
    if provisions_csv.exists():
        rows = json.loads(json.dumps(provisions))
        with provisions_csv.open("w", encoding="utf-8", newline="") as handle:
            fields = [
                "provision_id",
                "source_id",
                "citation",
                "hierarchy_type",
                "page_start",
                "page_end",
                "char_count",
                "text_preview",
                "review_status",
                "decision",
                "reviewer",
                "reviewed_at",
                "notes",
            ]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                preview = " ".join(str(row.get("original_text", "")).split())
                writer.writerow(
                    {
                        "provision_id": row["provision_id"],
                        "source_id": row["source_id"],
                        "citation": row.get("citation", ""),
                        "hierarchy_type": row.get("hierarchy_type", ""),
                        "page_start": row.get("page_start", ""),
                        "page_end": row.get("page_end", ""),
                        "char_count": len(str(row.get("original_text", ""))),
                        "text_preview": preview[:200],
                        "review_status": row.get("review_status", "unverified"),
                        "decision": "",
                        "reviewer": row.get("reviewed_by") or "",
                        "reviewed_at": row.get("reviewed_at") or "",
                        "notes": row.get("review_note") or "",
                    }
                )

    sources_csv = staging / "sources_review.csv"
    if sources_csv.exists():
        by_id = {row["source_id"]: row for row in sources}
        with sources_csv.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            existing = list(reader)
        for row in existing:
            fresh = by_id.get(row["source_id"])
            if not fresh:
                continue
            for column in (
                "publisher",
                "official_url",
                "published_date",
                "version_status",
                "review_status",
            ):
                if column in fields:
                    row[column] = fresh.get(column) or ""
            if "reviewer" in fields:
                row["reviewer"] = fresh.get("reviewed_by") or ""
            if "reviewed_at" in fields:
                row["reviewed_at"] = fresh.get("reviewed_at") or ""
        with sources_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(existing)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def _document_map() -> dict[str, dict[str, Any]]:
    path = EXTRACTED_DIR / "metadata.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    mapping: dict[str, dict[str, Any]] = {}
    for document in payload.get("documents", []):
        mapping.setdefault(document.get("source_id", ""), document)
    return mapping


def _find_provision(provisions: list[dict], provision_id: str) -> dict:
    for row in provisions:
        if row.get("provision_id") == provision_id:
            return row
    raise Refusal(f"unknown provision_id: {provision_id}")


def _find_source(sources: list[dict], source_id: str) -> dict:
    for row in sources:
        if row.get("source_id") == source_id:
            return row
    raise Refusal(f"unknown source_id: {source_id}")


def _short_title(row: dict) -> str:
    text = row.get("citation") or row.get("original_text") or ""
    return " ".join(str(text).split())[:78]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_date(value: str) -> str:
    # Store as ISO date; the schema expects a date, not free text.
    return date.fromisoformat(value).isoformat()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_list(args: argparse.Namespace) -> int:
    provisions = load_provisions(args.staging)
    if args.source:
        provisions = [p for p in provisions if p.get("source_id") == args.source]
        if not provisions:
            raise Refusal(f"no provisions for source_id: {args.source}")
    if args.status != "all":
        provisions = [p for p in provisions if p.get("review_status", "unverified") == args.status]

    if not provisions:
        print("no rows match the filter")
        return 0

    current_source = None
    for row in provisions:
        if row.get("source_id") != current_source:
            current_source = row.get("source_id")
            print(f"\n[{current_source}]")
        status = row.get("review_status", "unverified")
        reviewer = row.get("reviewed_by") or "-"
        print(f"  {row['provision_id']:<48} {status:<14} by={reviewer:<18} {_short_title(row)}")
    print(f"\n{len(provisions)} row(s)")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    sources = load_sources(args.staging)
    provisions = load_provisions(args.staging)
    row = _find_provision(provisions, args.provision_id)
    source = _find_source(sources, row["source_id"])
    document = _document_map().get(row["source_id"], {})

    pdf_name = document.get("pdf_name") or ""
    pdf_path = ORIGINALS_DIR / pdf_name if pdf_name else None
    sha = source.get("document_sha256") or document.get("pdf_sha256") or "(none)"

    print(f"provision_id : {row['provision_id']}")
    print(f"source_id    : {row['source_id']}")
    print(f"source title : {source.get('title', '')}")
    print(f"citation     : {row.get('citation', '')}")
    print(f"hierarchy    : {row.get('hierarchy_type', '')}")
    print(f"pages        : {row.get('page_start')} - {row.get('page_end')}")
    print(f"text file    : {document.get('filename') or '(unknown)'}")
    print(f"original PDF : {pdf_path if pdf_path else '(unknown)'}")
    print(f"sha256       : {sha}")
    print(
        "review       : status={status} by={by} at={at} note={note}".format(
            status=row.get("review_status", "unverified"),
            by=row.get("reviewed_by") or "-",
            at=row.get("reviewed_at") or "-",
            note=row.get("review_note") or "-",
        )
    )
    if source.get("review_status") != "human_verified":
        print("               (source is NOT approved; this provision cannot be cited yet)")
    print("\n--- verbatim text ---")
    print(row.get("original_text", ""))
    if row.get("conditions"):
        print("\n--- stored conditions ---")
        for condition in row["conditions"]:
            print(
                "  {id}: {desc} | {fact} {op} {value} | {state}".format(
                    id=condition.get("condition_id"),
                    desc=condition.get("description"),
                    fact=condition.get("fact_type"),
                    op=condition.get("operator"),
                    value=condition.get("expected_value"),
                    state=condition.get("human_review_status"),
                )
            )
    return 0


def _confirm_provision_id(provision_id: str, supplied: str | None) -> None:
    expected = provision_id
    if supplied is None:
        if not sys.stdin.isatty():
            raise Refusal(
                "confirmation required: pass --confirm with the provision id, "
                "or run interactively and type it"
            )
        supplied = input(f'Type the provision id "{provision_id}" to confirm: ')
    if supplied.strip() != expected:
        raise Refusal(
            f'confirmation does not match "{expected}"; nothing was changed'
        )


def cmd_approve(args: argparse.Namespace) -> int:
    reviewer = (args.reviewer or "").strip()
    if not reviewer:
        raise Refusal("--reviewer is required; approvals must name a human")

    sources = load_sources(args.staging)
    provisions = load_provisions(args.staging)
    row = _find_provision(provisions, args.provision_id)
    _confirm_provision_id(args.provision_id, args.confirm)

    row["review_status"] = "human_verified"
    row["reviewed_by"] = reviewer
    row["reviewed_at"] = _now().isoformat()
    row["review_note"] = None
    save(args.staging, sources, provisions)

    print(f"approved {args.provision_id} by {reviewer}")
    source = _find_source(sources, row["source_id"])
    if source.get("review_status") != "human_verified":
        print(
            f"WARNING: source {row['source_id']} is not approved yet. This provision "
            "will not enter the runtime corpus until `source-approve` succeeds."
        )
    return 0


def cmd_reject(args: argparse.Namespace) -> int:
    note = (args.note or "").strip()
    if not note:
        raise Refusal("--note is required for a rejection; record the reason")

    sources = load_sources(args.staging)
    provisions = load_provisions(args.staging)
    row = _find_provision(provisions, args.provision_id)

    row["review_status"] = "rejected"
    row["review_note"] = note
    if args.reviewer:
        row["reviewed_by"] = args.reviewer.strip()
    row["reviewed_at"] = _now().isoformat()
    save(args.staging, sources, provisions)

    print(f"rejected {args.provision_id}: {note}")
    print("the provision remains unusable and must not enter the runtime corpus")
    return 0


def cmd_source_approve(args: argparse.Namespace) -> int:
    reviewer = (args.reviewer or "").strip()
    if not reviewer:
        raise Refusal("--reviewer is required; approvals must name a human")

    sources = load_sources(args.staging)
    provisions = load_provisions(args.staging)
    row = _find_source(sources, args.source_id)

    # Apply only values the human supplied.  Never fill metadata from memory.
    candidate = dict(row)
    if args.publisher is not None:
        candidate["publisher"] = args.publisher.strip()
    if args.official_url is not None:
        candidate["official_url"] = args.official_url.strip()
    if args.published_date is not None:
        candidate["published_date"] = _parse_date(args.published_date)
    if args.version_status is not None:
        candidate["version_status"] = args.version_status
    if args.effective_from is not None:
        candidate["effective_from"] = _parse_date(args.effective_from)
    if args.effective_to is not None:
        candidate["effective_to"] = _parse_date(args.effective_to)

    missing: list[str] = []
    for field in SOURCE_APPROVAL_FIELDS:
        value = candidate.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    if candidate.get("version_status") == "uncertain":
        missing.append("version_status (is 'uncertain'; set current/superseded/future)")
    if missing:
        print(f"cannot approve source {args.source_id}; missing or incomplete:")
        for field in missing:
            print(f"  - {field}")
        print(
            "supply the real values with --publisher/--official-url/--published-date "
            "and --version-status; nothing was written"
        )
        return 2

    candidate["review_status"] = "human_verified"
    candidate["reviewed_by"] = reviewer
    candidate["reviewed_at"] = _now().date().isoformat()
    row.update(candidate)
    save(args.staging, sources, provisions)
    print(f"approved source {args.source_id} by {reviewer}")
    print(
        f"note: {sum(1 for p in provisions if p.get('source_id') == args.source_id)} "
        "provision(s) still need individual approval"
    )
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ai_lawyer.legal_rag.review_tool",
        description="Human review of the staged legal corpus (staging only).",
    )
    parser.add_argument(
        "--staging-dir",
        dest="staging",
        type=Path,
        default=DEFAULT_STAGING,
        help="staging directory (default: official/draft_curated)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list provisions and review state")
    p_list.add_argument("--source", help="filter to one source_id")
    p_list.add_argument(
        "--status",
        choices=["all", "unverified", "human_verified", "rejected"],
        default="all",
    )
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="show one provision verbatim with provenance")
    p_show.add_argument("provision_id")
    p_show.set_defaults(func=cmd_show)

    p_approve = sub.add_parser("approve", help="approve exactly one provision")
    p_approve.add_argument("provision_id")
    p_approve.add_argument("--reviewer", required=True)
    p_approve.add_argument(
        "--confirm",
        help="the same provision id; required in non-interactive use",
    )
    p_approve.set_defaults(func=cmd_approve)

    p_reject = sub.add_parser("reject", help="reject one provision with a reason")
    p_reject.add_argument("provision_id")
    p_reject.add_argument("--note", required=True)
    p_reject.add_argument("--reviewer")
    p_reject.set_defaults(func=cmd_reject)

    p_source = sub.add_parser(
        "source-approve", help="approve a source when its provenance is complete"
    )
    p_source.add_argument("source_id")
    p_source.add_argument("--reviewer", required=True)
    p_source.add_argument("--publisher")
    p_source.add_argument("--official-url")
    p_source.add_argument("--published-date", help="ISO date, e.g. 2020-07-20")
    p_source.add_argument(
        "--version-status",
        choices=["current", "superseded", "future"],
    )
    p_source.add_argument("--effective-from", help="ISO date")
    p_source.add_argument("--effective-to", help="ISO date")
    p_source.set_defaults(func=cmd_source_approve)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Refusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except ValidationError as exc:
        print(f"REFUSED: staging row would be invalid: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
