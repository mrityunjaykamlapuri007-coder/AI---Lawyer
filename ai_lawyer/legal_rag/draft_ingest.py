"""Mechanical draft-corpus builder for human review.

This module turns the extracted ``.txt`` files in ``legal_corpus/`` into
*draft* :class:`Source` and :class:`Provision` JSON.  It is deliberately
conservative:

* every source is written with ``review_status="unverified"``;
* ``official_url``, publisher, publication date and effective dates are left
  empty because they must be supplied by a human, not guessed;
* ``originals_text`` is copied verbatim from the ``.txt`` file (only page
  markers and surrounding whitespace are removed);
* the files real mode loads (``sources.json`` / ``provisions.json``) are never
  written.  Draft output goes to ``legal_corpus/draft/`` and stays unusable
  until a reviewer verifies it.

The generated review worksheets exist so a human can approve, edit or reject
each provision without reading raw JSON.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Literal, cast

from ai_lawyer.config.settings import PROJECT_ROOT
from ai_lawyer.contracts.models import Provision, Source
from ai_lawyer.legal_rag.corpus_loader import validate_and_build

SourceType = Literal["act", "rule", "notification", "regulation", "official_guidance"]
HierarchyType = Literal[
    "section", "rule", "subsection", "clause", "proviso", "explanation", "definition"
]

DEFAULT_CORPUS_DIR = PROJECT_ROOT / "ai_lawyer" / "legal_corpus"
DEFAULT_OUT_DIRNAME = "draft"
MIN_SECTIONS = 2

PAGE_MARKER_RE = re.compile(r"^=====\s*PAGE\s+(\d+)\s*=====$", re.IGNORECASE)
SECTION_RE = re.compile(r"^(\d{1,3})\.\s+\S")
TITLE_HINTS = ("ACT", "RULES", "REGULATIONS", "NOTIFICATION", "CODE")


@dataclass(frozen=True)
class DocumentSpec:
    """One extracted document and the metadata the reviewer must confirm."""

    filename: str
    source_id: str
    source_type: SourceType
    hierarchy_type: HierarchyType
    pdf_name: str | None = None
    title_hint: str | None = None
    metadata: dict[str, list[str]] | None = None


DEFAULT_SPECS: tuple[DocumentSpec, ...] = (
    DocumentSpec(
        "consumer_protection_act_2019.txt", "CPA_2019", "act", "section"
    ),
    DocumentSpec(
        "consumer_commission_rules_2020.txt", "CCR_2020", "rule", "rule"
    ),
    DocumentSpec("ecommerce_rules_2020.txt", "ECR_2020", "rule", "rule"),
    DocumentSpec(
        "ecommerce_amendment_2021.txt", "ECR_AMEND_2021", "notification", "clause"
    ),
    DocumentSpec(
        "jurisdiction_rules_2021.txt", "JUR_2021", "rule", "rule"
    ),
)


@dataclass(frozen=True)
class DraftSection:
    number: int | None
    text: str
    page_start: int
    page_end: int


@dataclass
class DocumentReport:
    filename: str
    source_id: str
    pages: int
    sections: int
    ascii_ratio: float
    letter_ratio: float
    latin_share: float
    ocr_risk: Literal["low", "high"]
    title_extracted: bool
    candidate_title: str | None = None
    candidate_dates: list[str] = field(default_factory=list)
    candidate_departments: list[str] = field(default_factory=list)
    candidate_gazette_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class DraftBuild:
    sources: list[Source]
    provisions: list[Provision]
    reports: list[DocumentReport]
    out_dir: Path
    retrieved_at: date
    written: list[Path] = field(default_factory=list)

    @property
    def high_ocr_risk(self) -> list[DocumentReport]:
        return [report for report in self.reports if report.ocr_risk == "high"]


# ---------------------------------------------------------------------------
# Text handling
# ---------------------------------------------------------------------------
def _normalise_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _lines_with_pages(text: str) -> list[tuple[int, str]]:
    """Return ``(page_number, line)`` pairs with page-marker lines removed."""
    page = 0
    lines: list[tuple[int, str]] = []
    for raw in _normalise_newlines(text).split("\n"):
        marker = PAGE_MARKER_RE.match(raw.strip())
        if marker:
            page = int(marker.group(1))
            continue
        lines.append((page, raw))
    return lines


def extract_title(text: str) -> str | None:
    """Find an all-caps document title line, mechanically.

    Returns ``None`` when no plausible title exists (for example heavily
    garbled OCR).  The caller must never substitute a title from memory.
    """
    for raw in _normalise_newlines(text).split("\n")[:250]:
        line = raw.strip()
        if not 12 <= len(line) <= 160:
            continue
        upper = line.upper()
        if not any(hint in upper for hint in TITLE_HINTS):
            continue
        ascii_letters = sum(1 for char in line if char.isascii() and char.isalpha())
        if ascii_letters < 8:
            continue
        if line != upper:
            continue
        if not any(char.isdigit() for char in line):
            continue
        return line
    return None


def text_quality(text: str) -> tuple[float, float, float, Literal["low", "high"]]:
    """Return ``(ascii_ratio, latin_letter_ratio, latin_letter_share, ocr_risk)``."""
    body = _normalise_newlines(text)
    if not body:
        return 0.0, 0.0, 0.0, "high"
    ascii_chars = sum(
        1 for char in body if char in "\n\t" or "\x20" <= char <= "\x7e"
    )
    latin_letters = sum(1 for char in body if "A" <= char <= "Z" or "a" <= char <= "z")
    other_letters = sum(1 for char in body if char.isalpha() and not char.isascii())
    alpha_total = latin_letters + other_letters
    ascii_ratio = ascii_chars / len(body)
    letter_ratio = latin_letters / len(body)
    latin_share = latin_letters / alpha_total if alpha_total else 0.0
    risk: Literal["low", "high"] = (
        "low" if ascii_ratio >= 0.90 and letter_ratio >= 0.55 else "high"
    )
    return ascii_ratio, letter_ratio, latin_share, risk


def script_mix_note(latin_share: float) -> str | None:
    """Flag documents that mix Latin and non-Latin scripts."""
    if 0.10 <= latin_share <= 0.90:
        return (
            f"mixed Latin/non-Latin script (Latin share {latin_share:.0%}); "
            "numbering may reset between language versions"
        )
    return None


def split_sections(text: str, min_sections: int = MIN_SECTIONS) -> list[DraftSection]:
    """Split on line-start section numbers that increase one at a time.

    The sequential rule rejects numbered lists, sub-clauses such as ``(1)`` and
    page numbers.  A gap of at most two numbers is accepted so a single
    unreadable heading does not swallow the rest of the document.  When fewer
    than ``min_sections`` headings are found, the whole document becomes one
    explicitly unsegmented draft provision.
    """
    lines = _lines_with_pages(text)
    starts: list[tuple[int, int, int, bool]] = []  # index, number, page, gap
    expected = 1
    last_number = 0
    for index, (page, line) in enumerate(lines):
        match = SECTION_RE.match(line)
        if not match:
            continue
        number = int(match.group(1))
        if number == expected:
            starts.append((index, number, page, False))
            expected = number + 1
            last_number = number
        elif last_number < number <= expected + 2:
            starts.append((index, number, page, True))
            expected = number + 1
            last_number = number

    if len(starts) < min_sections:
        return [_whole_document(lines)]

    sections: list[DraftSection] = []
    for position, (index, number, page, _gap) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        body = "\n".join(line for _, line in lines[index:end]).strip()
        if not body:
            continue
        pages = [line_page for line_page, _ in lines[index:end] if line_page > 0]
        page_start = page or (min(pages) if pages else 0)
        page_end = max(pages) if pages else page_start
        sections.append(
            DraftSection(
                number=number,
                text=body,
                page_start=page_start,
                page_end=page_end,
            )
        )
    return sections


def _whole_document(lines: list[tuple[int, str]]) -> DraftSection:
    body = "\n".join(line for _, line in lines).strip()
    pages = [page for page, _ in lines if page > 0]
    return DraftSection(
        number=None,
        text=body,
        page_start=min(pages) if pages else 0,
        page_end=max(pages) if pages else 0,
    )


# ---------------------------------------------------------------------------
# Draft construction
# ---------------------------------------------------------------------------
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_for(
    spec: DocumentSpec,
    text_path: Path,
    pdf_path: Path,
    text: str,
    title: str | None,
    retrieved_at: date,
    quality: tuple[float, float, float, Literal["low", "high"]],
) -> Source:
    text_sha = _sha256(text_path)
    pdf_sha = _sha256(pdf_path) if pdf_path.exists() else None
    ascii_ratio, letter_ratio, latin_share, risk = quality

    provenance = [f"text_sha256={text_sha}"]
    if pdf_sha:
        provenance.append(f"pdf_sha256={pdf_sha}")
    provenance.append(f"ascii_ratio={ascii_ratio:.3f}")
    provenance.append(f"letter_ratio={letter_ratio:.3f}")
    provenance.append(f"latin_letter_share={latin_share:.3f}")
    provenance.append(f"ocr_risk={risk}")

    notes = (
        f"DRAFT generated mechanically from {text_path.name} on {retrieved_at.isoformat()}; "
        + "; ".join(provenance)
        + ". Not reviewed. Usable only after a human sets review_status=human_verified."
    )
    if title is None:
        notes += " No title line was extracted; reviewer must supply the official title."

    return Source(
        source_id=spec.source_id,
        title=title or f"[DRAFT] {text_path.name} - title not extracted",
        source_type=spec.source_type,
        publisher="",
        official_url="",
        published_date=None,
        retrieved_at=retrieved_at,
        document_sha256=pdf_sha or text_sha,
        review_status="unverified",
        version_label="draft-unverified",
        effective_from=None,
        effective_to=None,
        version_status="uncertain",
        notes=notes,
    )


def _provision_for(
    spec: DocumentSpec,
    title: str | None,
    section: DraftSection,
) -> Provision:
    if section.number is None:
        provision_id = f"{spec.source_id}_DOC"
        citation = (
            f"{title}, full document (unsegmented)"
            if title
            else f"{spec.source_id} full document (unsegmented)"
        )
    else:
        provision_id = f"{spec.source_id}_P{section.number:03d}"
        base = title or spec.source_id
        citation = f"{base}, provision {section.number}"

    return Provision(
        provision_id=provision_id,
        source_id=spec.source_id,
        citation=citation,
        hierarchy_type=spec.hierarchy_type,
        parent_provision_id=None,
        original_text=section.text,
        search_text="",
        provisos=[],
        exceptions=[],
        definitions_used=[],
        cross_references=[],
        mandatory_context=[],
        conditions=[],
        page_start=section.page_start,
        page_end=section.page_end,
    )


def _existing_drafts_are_verified(out_dir: Path) -> bool:
    for name in ("draft_sources.json", "draft_provisions.json"):
        path = out_dir / name
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True
        if isinstance(payload, list) and any(
            isinstance(item, dict) and item.get("review_status") == "human_verified"
            for item in payload
        ):
            return True
    return False


def specs_from_manifest(path: str | Path) -> list[DocumentSpec]:
    """Read the part manifest written by ``english_extract``."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    specs: list[DocumentSpec] = []
    for item in payload.get("documents", []):
        specs.append(
            DocumentSpec(
                filename=str(item["filename"]),
                source_id=str(item["source_id"]),
                source_type=cast(SourceType, item["source_type"]),
                hierarchy_type=cast(HierarchyType, item["hierarchy_type"]),
                pdf_name=item.get("pdf_name"),
                title_hint=item.get("candidate_title"),
                metadata={
                    key: list(item.get(key, []))
                    for key in (
                        "candidate_dates",
                        "candidate_departments",
                        "candidate_gazette_ids",
                    )
                },
            )
        )
    if not specs:
        raise ValueError(f"no documents in manifest: {path}")
    return specs


def build_drafts(
    corpus_dir: str | Path = DEFAULT_CORPUS_DIR,
    out_dir: str | Path | None = None,
    *,
    specs: Iterable[DocumentSpec] | None = None,
    manifest_path: str | Path | None = None,
    text_dir: str | Path | None = None,
    originals_dir: str | Path | None = None,
    retrieved_at: date | None = None,
    min_sections: int = MIN_SECTIONS,
    force: bool = False,
) -> DraftBuild:
    """Build draft JSON, CSVs and a review guide.  Never touches real files."""
    corpus_path = Path(corpus_dir)
    text_root = Path(text_dir) if text_dir is not None else corpus_path
    originals_root = (
        Path(originals_dir) if originals_dir is not None else corpus_path / "originals"
    )
    destination = (
        Path(out_dir) if out_dir is not None else corpus_path / DEFAULT_OUT_DIRNAME
    )
    retrieved = retrieved_at or date.today()
    chosen_specs = (
        specs_from_manifest(manifest_path)
        if manifest_path is not None
        else list(specs or DEFAULT_SPECS)
    )

    if _existing_drafts_are_verified(destination) and not force:
        raise FileExistsError(
            f"{destination} contains drafts marked human_verified; refusing to overwrite. "
            "Use force=True only if you intend to discard that review."
        )

    sources: list[Source] = []
    provisions: list[Provision] = []
    reports: list[DocumentReport] = []

    for spec in chosen_specs:
        text_path = text_root / spec.filename
        if not text_path.exists():
            continue
        pdf_name = spec.pdf_name or f"{text_path.stem}.pdf"
        pdf_path = originals_root / pdf_name
        text = text_path.read_text(encoding="utf-8")
        extracted_title = extract_title(text)
        title = extracted_title or spec.title_hint
        quality = text_quality(text)
        sections = split_sections(text, min_sections=min_sections)
        notes: list[str] = []
        if title is None:
            notes.append("title not extracted; placeholder written")
        elif not extracted_title and spec.title_hint:
            notes.append(
                "title taken from the document's 'may be called' sentence; confirm it"
            )
        if len(sections) == 1 and sections[0].number is None:
            notes.append("document left unsegmented")
        if quality[3] == "high":
            notes.append("high OCR risk; re-extract or clean text before reviewing")
        mix_note = script_mix_note(quality[2])
        if mix_note:
            notes.append(mix_note)

        source = _source_for(
            spec, text_path, pdf_path, text, title, retrieved, quality
        )
        sources.append(source)
        for section in sections:
            provisions.append(_provision_for(spec, title, section))

        last_number = max(
            (section.number for section in sections if section.number is not None),
            default=0,
        )
        candidates = [
            int(match.group(1))
            for _, line in _lines_with_pages(text)
            if (match := SECTION_RE.match(line))
        ]
        if candidates and max(candidates) > last_number + 2:
            notes.append(
                f"possible missed headings: highest line-start number {max(candidates)} "
                f"but mechanical split stopped at {last_number}"
            )

        pages = max(
            (page for page, _ in _lines_with_pages(text) if page > 0), default=0
        )
        meta = spec.metadata or {}
        reports.append(
            DocumentReport(
                filename=spec.filename,
                source_id=spec.source_id,
                pages=pages,
                sections=len(sections),
                ascii_ratio=quality[0],
                letter_ratio=quality[1],
                latin_share=quality[2],
                ocr_risk=quality[3],
                title_extracted=extracted_title is not None,
                candidate_title=spec.title_hint,
                candidate_dates=list(meta.get("candidate_dates", [])),
                candidate_departments=list(meta.get("candidate_departments", [])),
                candidate_gazette_ids=list(meta.get("candidate_gazette_ids", [])),
                notes=notes,
            )
        )

    if not sources:
        raise FileNotFoundError(f"no known corpus files found in {corpus_path}")

    # Fail before writing anything if the drafts do not satisfy the loader schema.
    validate_and_build(
        [source.model_dump(mode="json") for source in sources],
        [provision.model_dump(mode="json") for provision in provisions],
        mode="real",
        directory=None,
        warn_unusable=False,
    )

    destination.mkdir(parents=True, exist_ok=True)
    build = DraftBuild(
        sources=sources,
        provisions=provisions,
        reports=reports,
        out_dir=destination,
        retrieved_at=retrieved,
    )
    build.written.append(_write_json(destination / "draft_sources.json", sources))
    build.written.append(
        _write_json(destination / "draft_provisions.json", provisions)
    )
    build.written.append(_write_sources_csv(destination / "sources_review.csv", sources, reports))
    build.written.append(
        _write_provisions_csv(destination / "provisions_review.csv", provisions)
    )
    build.written.append(_write_readme(destination / "DRAFT_REVIEW.md", build))
    build.written.append(_write_manifest(destination / "draft_manifest.json", build))
    return build


def _write_json(path: Path, models: list[Any]) -> Path:
    path.write_text(
        json.dumps(
            [model.model_dump(mode="json") for model in models],
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _write_sources_csv(
    path: Path, sources: list[Source], reports: list[DocumentReport]
) -> Path:
    report_by_id = {report.source_id: report for report in reports}
    fieldnames = [
        "source_id",
        "filename",
        "source_type",
        "extracted_title",
        "title_status",
        "candidate_title",
        "candidate_dates",
        "candidate_departments",
        "candidate_gazette_ids",
        "publisher",
        "official_url",
        "published_date",
        "effective_from",
        "effective_to",
        "version_status",
        "review_status",
        "document_sha256",
        "ocr_risk",
        "ascii_ratio",
        "letter_ratio",
        "latin_share",
        "decision",
        "reviewer",
        "reviewed_at",
        "notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for source in sources:
            report = report_by_id[source.source_id]
            writer.writerow(
                {
                    "source_id": source.source_id,
                    "filename": report.filename,
                    "source_type": source.source_type,
                    "extracted_title": source.title,
                    "title_status": (
                        "extracted"
                        if report.title_extracted
                        else ("candidate" if report.candidate_title else "placeholder")
                    ),
                    "candidate_title": report.candidate_title or "",
                    "candidate_dates": "; ".join(report.candidate_dates),
                    "candidate_departments": "; ".join(report.candidate_departments),
                    "candidate_gazette_ids": "; ".join(report.candidate_gazette_ids),
                    "publisher": source.publisher,
                    "official_url": source.official_url,
                    "published_date": "",
                    "effective_from": "",
                    "effective_to": "",
                    "version_status": source.version_status,
                    "review_status": source.review_status,
                    "document_sha256": source.document_sha256,
                    "ocr_risk": report.ocr_risk,
                    "ascii_ratio": f"{report.ascii_ratio:.3f}",
                    "letter_ratio": f"{report.letter_ratio:.3f}",
                    "latin_share": f"{report.latin_share:.3f}",
                    "decision": "",
                    "reviewer": "",
                    "reviewed_at": "",
                    "notes": " | ".join(report.notes),
                }
            )
    return path


def _write_provisions_csv(path: Path, provisions: list[Provision]) -> Path:
    fieldnames = [
        "provision_id",
        "source_id",
        "citation",
        "hierarchy_type",
        "page_start",
        "page_end",
        "char_count",
        "text_preview",
        "decision",
        "reviewer",
        "reviewed_at",
        "notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for provision in provisions:
            preview = " ".join(provision.original_text.split())
            writer.writerow(
                {
                    "provision_id": provision.provision_id,
                    "source_id": provision.source_id,
                    "citation": provision.citation,
                    "hierarchy_type": provision.hierarchy_type,
                    "page_start": provision.page_start,
                    "page_end": provision.page_end,
                    "char_count": len(provision.original_text),
                    "text_preview": preview[:200],
                    "decision": "",
                    "reviewer": "",
                    "reviewed_at": "",
                    "notes": "",
                }
            )
    return path


def _write_readme(path: Path, build: DraftBuild) -> Path:
    lines = [
        "# Draft corpus review guide",
        "",
        "These files are **drafts generated mechanically from extracted text**.",
        "Nothing here is legal advice and nothing here may be cited until a human",
        "reviews it. Every source is written with `review_status: unverified`, so",
        "the engine treats every provision as unusable.",
        "",
        "## Files",
        "",
        "- `draft_sources.json` / `draft_provisions.json` - schema-valid drafts.",
        "- `sources_review.csv` - source metadata worksheet (URLs and dates are blank).",
        "- `provisions_review.csv` - one row per provision, with a text preview.",
        "- `draft_manifest.json` - counts and per-document OCR quality.",
        "",
        "## Review steps",
        "",
        "1. Check the empty `publisher`, `official_url`, `published_date`,",
        "   `effective_from` and `effective_to` fields against an official copy.",
        "2. Fix the extracted title if `title_status` is `placeholder`; if it is",
        "   `candidate`, confirm the title quoted from the document's own",
        "   'may be called' sentence.",
        "3. The `candidate_dates`, `candidate_departments` and",
        "   `candidate_gazette_ids` columns are quotations from the document, not",
        "   decisions. Confirm or replace them before setting any Source field.",
        "4. Read each provision in `provisions_review.csv`. Mark `approve`, `edit`",
        "   or `reject`; split or merge sections in the JSON if the mechanical",
        "   segmentation is wrong.",
        "5. Re-extract any document whose `ocr_risk` is `high`. Garbled text must",
        "   not be approved as-is.",
        "6. Only after review, copy the approved entries to `legal_corpus/sources.json`",
        "   and `legal_corpus/provisions.json` and set `review_status` to",
        "   `human_verified` for sources you personally checked. Set",
        "   `human_review_status` to `reviewed` on any condition you verified.",
        "7. Rebuild the index with `CORPUS_MODE=real` and rerun the evaluation.",
        "",
        "## Documents in this draft",
        "",
        "| source_id | file | sections | pages | OCR risk | notes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for report in build.reports:
        notes = "; ".join(report.notes) or "-"
        lines.append(
            f"| {report.source_id} | {report.filename} | {report.sections} | "
            f"{report.pages} | {report.ocr_risk} | {notes} |"
        )
    lines += [
        "",
        f"Generated: {build.retrieved_at.isoformat()}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_manifest(path: Path, build: DraftBuild) -> Path:
    payload = {
        "generated_at": build.retrieved_at.isoformat(),
        "draft_only": True,
        "citation_ready": False,
        "review_status": "unverified",
        "sources_count": len(build.sources),
        "provisions_count": len(build.provisions),
        "documents": [
            {
                "filename": report.filename,
                "source_id": report.source_id,
                "pages": report.pages,
                "sections": report.sections,
                "ascii_ratio": round(report.ascii_ratio, 4),
                "letter_ratio": round(report.letter_ratio, 4),
                "latin_share": round(report.latin_share, 4),
                "ocr_risk": report.ocr_risk,
                "title_extracted": report.title_extracted,
                "candidate_title": report.candidate_title,
                "candidate_dates": report.candidate_dates,
                "candidate_departments": report.candidate_departments,
                "candidate_gazette_ids": report.candidate_gazette_ids,
                "notes": report.notes,
            }
            for report in build.reports
        ],
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    """CLI: python -m ai_lawyer.legal_rag.draft_ingest"""
    parser = argparse.ArgumentParser(
        description="Build review-only draft corpus files from extracted .txt sources"
    )
    parser.add_argument("--corpus-dir", default=str(DEFAULT_CORPUS_DIR))
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--text-dir",
        default=None,
        help="Directory containing extracted .txt files (default: corpus dir)",
    )
    parser.add_argument(
        "--originals-dir",
        default=None,
        help="Directory containing source PDFs (default: <corpus-dir>/originals)",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="Part manifest written by legal_rag.english_extract",
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="Retrieval date written to sources (YYYY-MM-DD, default: today)",
    )
    parser.add_argument("--min-sections", type=int, default=MIN_SECTIONS)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite drafts even if they contain human_verified entries",
    )
    args = parser.parse_args()

    retrieved = date.fromisoformat(args.as_of) if args.as_of else date.today()
    build = build_drafts(
        corpus_dir=args.corpus_dir,
        out_dir=args.out,
        manifest_path=args.manifest,
        text_dir=args.text_dir,
        originals_dir=args.originals_dir,
        retrieved_at=retrieved,
        min_sections=args.min_sections,
        force=args.force,
    )

    print(
        f"draft sources={len(build.sources)} provisions={len(build.provisions)} "
        f"review_status=unverified citation_ready=false"
    )
    for report in build.reports:
        print(
            f"  {report.source_id}: pages={report.pages} sections={report.sections} "
            f"ascii={report.ascii_ratio:.1%} letters={report.letter_ratio:.1%} "
            f"latin_share={report.latin_share:.1%} ocr_risk={report.ocr_risk}"
        )
        for note in report.notes:
            print(f"    - {note}")
    if build.high_ocr_risk:
        print(
            f"WARNING: {len(build.high_ocr_risk)} of {len(build.reports)} documents "
            "have high OCR risk. Re-extract before human review."
        )
    print("wrote:")
    for path in build.written:
        print(f"  {path}")


if __name__ == "__main__":
    main()
