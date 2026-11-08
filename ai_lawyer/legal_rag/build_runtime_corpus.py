"""Build the runtime corpus from human-approved staging rows only.

The staging directory (``legal_corpus/official/draft_curated``) is the review
queue.  It contains mechanically drafted text that no human has checked.  This
module copies only rows a human approved into the runtime files
``legal_corpus/sources.json`` and ``legal_corpus/provisions.json``.

Rules (fail closed):

* a provision is included only when it is ``human_verified``, has a named
  reviewer, and its source is ``human_verified`` with complete provenance and a
  non-``uncertain`` version status;
* zero qualifying provisions means nothing is written;
* the acceptance gate runs before writing; any problem means nothing is
  written;
* rejected and unapproved rows are reported with the reason they were excluded.

Usage::

    python -m ai_lawyer.legal_rag.build_runtime_corpus
    python -m ai_lawyer.legal_rag.build_runtime_corpus \\
        --staging-dir <dir> --out-dir <dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ai_lawyer.contracts.errors import CorpusValidationError
from ai_lawyer.contracts.models import Provision, Source
from ai_lawyer.legal_rag.corpus_acceptance import real_corpus_problems
from ai_lawyer.legal_rag.corpus_loader import validate_and_build

PACKAGE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_STAGING = PACKAGE_DIR / "legal_corpus" / "official" / "draft_curated"
DEFAULT_OUT = PACKAGE_DIR / "legal_corpus"

SOURCE_FIELDS = ("publisher", "official_url", "published_date", "document_sha256")


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _source_problems(source: Source) -> list[str]:
    problems = [
        f"missing {field}" for field in SOURCE_FIELDS if _blank(getattr(source, field))
    ]
    if source.version_status == "uncertain":
        problems.append("version_status is 'uncertain'")
    return problems


def _atomic_write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


def build(
    staging: Path, out_dir: Path
) -> tuple[list[Source], list[Provision], list[str], dict[str, Any]]:
    """Return approved sources, provisions, gate problems and a report."""
    raw_sources = _load(staging / "draft_sources.json")
    raw_provisions = _load(staging / "draft_provisions.json")

    sources = [Source.model_validate(item) for item in raw_sources]
    provisions = [Provision.model_validate(item) for item in raw_provisions]
    by_source = {source.source_id: source for source in sources}

    excluded: Counter[str] = Counter()
    per_source_included: Counter[str] = Counter()
    approved_sources: dict[str, Source] = {}

    for source in sources:
        if source.review_status != "human_verified":
            continue
        problems = _source_problems(source)
        if problems:
            excluded[f"source {source.source_id}: " + "; ".join(problems)] += 0
            continue
        approved_sources[source.source_id] = source

    included: list[Provision] = []
    for provision in provisions:
        if provision.review_status == "rejected":
            excluded["rejected by reviewer"] += 1
            continue
        if provision.review_status != "human_verified":
            excluded["not approved"] += 1
            continue
        if _blank(provision.reviewed_by):
            excluded["missing reviewer"] += 1
            continue
        source = by_source.get(provision.source_id)
        if source is None:
            excluded["unknown source"] += 1
            continue
        if provision.source_id not in approved_sources:
            excluded[f"source {provision.source_id} not approved"] += 1
            continue
        included.append(provision)
        per_source_included[provision.source_id] += 1

    used_source_ids = {p.source_id for p in included}
    used_sources = [approved_sources[sid] for sid in sorted(used_source_ids)]

    report = {
        "staging": str(staging),
        "out_dir": str(out_dir),
        "approved_sources_total": len(approved_sources),
        "sources_with_approved_provisions": len(used_sources),
        "provisions_total": len(provisions),
        "provisions_included": len(included),
        "per_source_included": dict(sorted(per_source_included.items())),
        "excluded": dict(sorted(excluded.items())),
        "approved_sources_without_provisions": sorted(
            set(approved_sources) - used_source_ids
        ),
    }

    if not included:
        return used_sources, included, ["no approved provisions qualify"], report

    try:
        corpus = validate_and_build(
            [s.model_dump(mode="json") for s in used_sources],
            [p.model_dump(mode="json") for p in included],
            mode="real",
            directory=None,
            warn_unusable=False,
        )
    except (ValidationError, CorpusValidationError) as exc:
        return used_sources, included, [f"corpus validation failed: {exc}"], report

    return used_sources, included, real_corpus_problems(corpus), report


def _print_report(report: dict[str, Any], problems: list[str]) -> None:
    print(f"staging : {report['staging']}")
    print(f"out dir : {report['out_dir']}")
    print(
        f"staging rows: {report['provisions_total']} provisions, "
        f"{report['approved_sources_total']} approved source(s)"
    )
    print(f"\nincluded provisions: {report['provisions_included']}")
    for source_id, count in report["per_source_included"].items():
        print(f"  {source_id}: {count}")
    if report["approved_sources_without_provisions"]:
        print("\napproved sources with no approved provisions (not written):")
        for source_id in report["approved_sources_without_provisions"]:
            print(f"  {source_id}")

    print(f"\nexcluded rows: {sum(report['excluded'].values())}")
    for reason, count in report["excluded"].items():
        if count == 0:
            print(f"  {reason}")
        else:
            print(f"  {reason}: {count}")

    if problems:
        print("\nacceptance gate: FAIL")
        for problem in problems:
            print(f"  - {problem}")
        print("\nnothing written")
    else:
        print(f"\nacceptance gate: PASS (usable total: {report['provisions_included']})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ai_lawyer.legal_rag.build_runtime_corpus",
        description="Build runtime corpus files from human-approved staging rows.",
    )
    parser.add_argument("--staging-dir", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--report",
        type=Path,
        help="optional path to write the JSON report",
    )
    args = parser.parse_args(argv)

    try:
        sources, provisions, problems, report = build(args.staging_dir, args.out_dir)
    except (FileNotFoundError, ValidationError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    _print_report(report, problems)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps({**report, "problems": problems}, indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )

    if problems:
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(
        args.out_dir / "sources.json",
        [source.model_dump(mode="json") for source in sources],
    )
    _atomic_write_json(
        args.out_dir / "provisions.json",
        [provision.model_dump(mode="json") for provision in provisions],
    )
    print(f"wrote {args.out_dir / 'sources.json'}")
    print(f"wrote {args.out_dir / 'provisions.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
