"""Extract the English-language portion of the bilingual gazette PDFs.

The supplied PDFs contain Hindi and English versions of the same notification.
The Hindi text layer uses a font whose ``ToUnicode`` map is broken, so naive
extraction produces substituted characters.  The English text layer is clean.

This module keeps English-majority pages, drops lines that are not mostly
Latin script, splits multiple notifications inside one PDF, and copies text
verbatim.  It does not repair, paraphrase or translate anything.  Output is for
human review, not for citation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

import pymupdf

from ai_lawyer.config.settings import PROJECT_ROOT

DEFAULT_CORPUS_DIR = PROJECT_ROOT / "ai_lawyer" / "legal_corpus"
DEFAULT_OUT_DIRNAME = "extracted_en"

# filename stem -> (base source id, source type, hierarchy type)
DOCUMENT_TYPES: dict[str, tuple[str, str, str]] = {
    "consumer_protection_act_2019": ("CPA_2019", "act", "section"),
    "consumer_commission_rules_2020": ("CCR_2020", "rule", "rule"),
    "ecommerce_rules_2020": ("ECR_2020", "rule", "rule"),
    "ecommerce_amendment_2021": ("ECR_AMEND_2021", "notification", "clause"),
    "jurisdiction_rules_2021": ("JUR_2021", "rule", "rule"),
}

PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,3}\s*$")
SECTION_NUMBER_RE = re.compile(r"^\s*(\d{1,3})\.\s*$")
ROMAN_RE = re.compile(r"^\s*[IVXLC]+\s*$")
TITLE_RE = re.compile(r"may be called the (.+?)\.", re.IGNORECASE)
TITLE_HINTS = ("ACT", "RULES", "REGULATIONS", "NOTIFICATION", "CODE")
BOILERPLATE_RE = re.compile(
    r"^\s*(?:"
    r"the gazette of india"
    r"|.*\bthe gazette of india\b.*"
    r"|\[?part ii\b"
    r"|sec\.\s*\d+\]"
    r"|published by authority"
    r"|regd\.\s*no\."
    r"|xxxgid\w*"
    r"|no\.\s*\d+\]"
    r"|cg-dl-e-[\w-]+"
    r"|new delhi,"
    r"|\d{4}\s+gi/\d{4}"
    r"|extraordinary\s*$"
    r"|uploaded by\b"
    r"|and published by\b"
    r"|digitally signed by\b"
    r"|date:\s*\d{4}\.\d{2}\.\d{2}"
    r"|number\s+g\.s\.r\."
    r"|\[f\.\s*no\."
    r")",
    re.IGNORECASE,
)
MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December"
)
DATE_RE = re.compile(
    rf"(?:\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTHS}),?\s+\d{{4}}\b"
    rf"|\b(?:{MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b)",
    re.IGNORECASE,
)
GAZETTE_ID_RE = re.compile(r"\b\d{4}\s+GI/\d{4}\b")
DEPARTMENT_RE = re.compile(r"^\s*MINISTRY OF [A-Z][A-Z ,.&()-]+$")


@dataclass
class ExtractedPart:
    filename: str
    source_id: str
    source_type: str
    hierarchy_type: str
    text: str
    pages: list[int]
    candidate_title: str | None
    pdf_name: str
    pdf_sha256: str
    metadata: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class EnglishExtract:
    filename: str
    parts: list[ExtractedPart]
    pages_kept: list[int]
    pages_total: int
    latin_share: float
    dropped_lines: int

    @property
    def text(self) -> str:
        return "\n\n".join(part.text for part in self.parts)


def _counts(text: str) -> tuple[int, int]:
    latin = sum(1 for char in text if char.isascii() and char.isalpha())
    other = sum(
        1
        for char in text
        if not char.isascii()
        and (char.isalpha() or 0x0900 <= ord(char) <= 0x097F)
    )
    return latin, other


def _line_is_english(line: str, *, page_ratio: float) -> bool:
    stripped = line.strip()
    if not stripped or PAGE_NUMBER_RE.match(stripped):
        return False
    if ROMAN_RE.match(stripped) or BOILERPLATE_RE.match(stripped):
        return False
    latin, devanagari = _counts(stripped)
    if latin + devanagari == 0:
        # Keep section numbers only from pages with real English content;
        # punctuation on a Hindi-only page is noise from the other version.
        return page_ratio >= 0.90 or (
            page_ratio >= 0.30 and bool(SECTION_NUMBER_RE.match(stripped))
        )
    return latin >= 2 and latin / (latin + devanagari) >= 0.85


def _merge_section_numbers(lines: list[str]) -> list[str]:
    """Attach a standalone ``N.`` line to the heading that follows it."""
    merged: list[str] = []
    index = 0
    while index < len(lines):
        match = SECTION_NUMBER_RE.match(lines[index])
        if (
            match
            and index + 1 < len(lines)
            and lines[index + 1].strip()
            and not SECTION_NUMBER_RE.match(lines[index + 1])
        ):
            merged.append(f"{match.group(1)}. {lines[index + 1].strip()}")
            index += 2
            continue
        merged.append(lines[index])
        index += 1
    return merged


def _candidate_title(text: str) -> str | None:
    match = TITLE_RE.search(" ".join(text.split()))
    if match:
        title = match.group(1).strip(" .;:")
        if 8 <= len(title) <= 200:
            return title
    # Fall back to an all-caps heading, as used by the Act.
    for raw in text.splitlines()[:250]:
        line = raw.strip()
        if not 12 <= len(line) <= 160 or line != line.upper():
            continue
        if not any(hint in line.upper() for hint in TITLE_HINTS):
            continue
        if sum(1 for char in line if char.isascii() and char.isalpha()) < 8:
            continue
        if any(char.isdigit() for char in line):
            return line
    return None


def _metadata(text: str) -> dict[str, list[str]]:
    dates = sorted(set(match.group(0).strip() for match in DATE_RE.finditer(text)))
    gazette_ids = sorted(set(GAZETTE_ID_RE.findall(text)))
    departments = sorted(
        {
            line.strip()
            for line in text.splitlines()
            if DEPARTMENT_RE.match(line.strip())
        }
    )
    return {
        "candidate_dates": dates,
        "candidate_gazette_ids": gazette_ids,
        "candidate_departments": departments,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _split_parts(
    page_lines: list[tuple[int, list[str]]], stem: str
) -> list[tuple[list[tuple[int, list[str]]], str]]:
    """Split filtered pages into notifications, keeping page markers."""
    flat = [(page, line) for page, lines in page_lines for line in lines]
    boundaries = [
        index
        for index, (_, line) in enumerate(flat)
        if line.strip().upper() == "NOTIFICATION"
    ]
    if not boundaries:
        return [(page_lines, "_1")]

    starts = boundaries
    parts: list[tuple[list[tuple[int, list[str]]], str]] = []
    first = 0
    for part_number, start in enumerate(starts, start=1):
        end = starts[part_number] if part_number < len(starts) else len(flat)
        chunk = flat[first:end]
        first = end
        grouped: list[tuple[int, list[str]]] = []
        for page, line in chunk:
            if grouped and grouped[-1][0] == page:
                grouped[-1][1].append(line)
            else:
                grouped.append((page, [line]))
        suffix = "_1" if len(starts) == 1 else f"_{part_number}"
        parts.append((grouped, suffix))
    return parts


def _part_text(pages: list[tuple[int, list[str]]]) -> str:
    blocks = [
        f"===== PAGE {page} =====\n" + "\n".join(_merge_section_numbers(lines))
        for page, lines in pages
        if lines
    ]
    return "\n\n".join(blocks).strip() + "\n"


def extract_english(pdf_path: str | Path) -> EnglishExtract:
    """Return the English portions of one PDF, one part per notification."""
    path = Path(pdf_path)
    document = pymupdf.open(path)
    stem = path.stem
    base_id, source_type, hierarchy_type = DOCUMENT_TYPES.get(
        stem, (stem.upper(), "notification", "clause")
    )
    pdf_hash = _sha256(path)

    page_lines: list[tuple[int, list[str]]] = []
    kept_pages: list[int] = []
    dropped = 0
    for number, page in enumerate(document, start=1):
        raw = page.get_text()
        latin_page, dev_page = _counts(raw)
        page_total = latin_page + dev_page
        page_ratio = latin_page / page_total if page_total else 0.0
        lines: list[str] = []
        for line in raw.splitlines():
            if _line_is_english(line, page_ratio=page_ratio):
                lines.append(line.rstrip())
            elif line.strip():
                dropped += 1
        if lines:
            kept_pages.append(number)
            page_lines.append((number, lines))

    raw_all = "\n".join(page.get_text() for page in document)
    whole_metadata = _metadata(raw_all)
    parts: list[ExtractedPart] = []
    split = _split_parts(page_lines, stem)
    multi = len(split) > 1
    for index, (pages, suffix) in enumerate(split, start=1):
        text = _part_text(pages)
        if not text.strip():
            continue
        source_id = base_id if index == 1 else f"{base_id}{suffix}"
        part_meta = _metadata(text)
        if len(split) == 1:
            part_meta["candidate_dates"] = sorted(
                set(part_meta["candidate_dates"])
                | set(whole_metadata["candidate_dates"])
            )
        part_meta["candidate_gazette_ids"] = sorted(
            set(part_meta["candidate_gazette_ids"])
            | set(whole_metadata["candidate_gazette_ids"])
        )
        part_meta["candidate_departments"] = sorted(
            set(part_meta["candidate_departments"])
            | set(whole_metadata["candidate_departments"])
        )
        parts.append(
            ExtractedPart(
                filename=f"{stem}{suffix}.txt",
                source_id=source_id,
                source_type=source_type,
                hierarchy_type=hierarchy_type,
                text=text,
                pages=[page for page, _ in pages],
                candidate_title=_candidate_title(text),
                pdf_name=path.name,
                pdf_sha256=pdf_hash,
                metadata=part_meta,
            )
        )

    latin_total, dev_total = _counts("\n\n".join(part.text for part in parts))
    total = latin_total + dev_total
    return EnglishExtract(
        filename=path.name,
        parts=parts,
        pages_kept=kept_pages,
        pages_total=len(document),
        latin_share=latin_total / total if total else 0.0,
        dropped_lines=dropped,
    )


def extract_all(
    corpus_dir: str | Path = DEFAULT_CORPUS_DIR,
    out_dir: str | Path | None = None,
    *,
    pdf_names: Iterable[str] | None = None,
) -> list[EnglishExtract]:
    corpus_path = Path(corpus_dir)
    originals = corpus_path / "originals"
    destination = (
        Path(out_dir) if out_dir is not None else corpus_path / DEFAULT_OUT_DIRNAME
    )
    destination.mkdir(parents=True, exist_ok=True)

    pdfs = (
        [originals / name for name in pdf_names]
        if pdf_names is not None
        else sorted(originals.glob("*.pdf"))
    )
    extracts: list[EnglishExtract] = []
    for pdf in pdfs:
        if not pdf.exists():
            continue
        extract = extract_english(pdf)
        for part in extract.parts:
            (destination / part.filename).write_text(part.text, encoding="utf-8")
        extracts.append(extract)

    metadata_path = destination / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "generated_at": date.today().isoformat(),
                "review_status": "unverified",
                "source": (
                    "English lines extracted from bilingual gazette PDFs; "
                    "review only, not citation-ready"
                ),
                "documents": [
                    {
                        "filename": part.filename,
                        "pdf_name": part.pdf_name,
                        "pdf_sha256": part.pdf_sha256,
                        "source_id": part.source_id,
                        "source_type": part.source_type,
                        "hierarchy_type": part.hierarchy_type,
                        "pages": part.pages,
                        "candidate_title": part.candidate_title,
                        **part.metadata,
                    }
                    for extract in extracts
                    for part in extract.parts
                ],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return extracts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract the English-language lines from bilingual gazette PDFs"
    )
    parser.add_argument("--corpus-dir", default=str(DEFAULT_CORPUS_DIR))
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    extracts = extract_all(args.corpus_dir, args.out)
    for extract in extracts:
        print(
            f"{extract.filename}: pages_kept={len(extract.pages_kept)}/"
            f"{extract.pages_total} parts={len(extract.parts)} "
            f"latin_share={extract.latin_share:.1%} dropped_lines={extract.dropped_lines}"
        )
        for part in extract.parts:
            print(
                f"  {part.filename} source_id={part.source_id} "
                f"pages={part.pages[0]}-{part.pages[-1]} chars={len(part.text)} "
                f"title={part.candidate_title!r}"
            )
    print(f"wrote {sum(len(e.parts) for e in extracts)} part files")


if __name__ == "__main__":
    main()
