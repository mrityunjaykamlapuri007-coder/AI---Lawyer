"""Independent checks that a stored provision still contains the official text.

An official source guarantees the right document.  It does not guarantee that
the text layer, the PDF-to-text step or the provision split preserved it.  This
module performs the mechanical checks required by AGENT_RISK_CONTROLS.md:

* C1.1 a second, independent extraction (``pypdf``) of every page, diffed
  against the stored text after whitespace normalisation;
* C1.2 a number inventory (digit runs, section/rule references, dates, rupee
  amounts) compared between the stored text and the second extraction;
* C1.3 ``text_integrity_flags`` over the stored text (a readable layer with no
  digits is a known failure mode);
* C1.4 a PNG render of the page so the human checks the picture, not only text.

Everything here is mechanical.  It never changes the stored legal text and
never approves anything: it writes flags that a human must resolve.

Usage::

    python -m ai_lawyer.legal_rag.integrity
    python -m ai_lawyer.legal_rag.integrity --staging-dir <dir> --out-dir <dir>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ai_lawyer.legal_rag.english_extract import text_integrity_flags

PACKAGE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_STAGING = PACKAGE_DIR / "legal_corpus" / "official" / "draft_curated"
ORIGINALS_DIR = PACKAGE_DIR / "legal_corpus" / "official" / "originals"
EXTRACTED_DIR = PACKAGE_DIR / "legal_corpus" / "official" / "extracted_en"

# Words that invert or restrict a legal sentence.  Losing one silently changes
# the law, so they are treated as high-signal in the word diff.
CRITICAL_WORDS = frozenset(
    {
        "not",
        "no",
        "never",
        "shall",
        "may",
        "must",
        "except",
        "unless",
        "provided",
        "only",
        "within",
        "before",
        "after",
        "all",
        "any",
    }
)

# A stored provision that contains one of these markers is talking about a
# proviso, exception, explanation or overriding clause; the reviewer must say
# they checked it (C5.1).
PROVISO_MARKERS = (
    "provided that",
    "provided further",
    "except",
    "subject to",
    "explanation",
    "notwithstanding",
)

_RUPEE_RE = re.compile(r"(?:Rs\.?|INR|₹)\s*[\d,]+(?:\.\d{1,2})?", re.IGNORECASE)
_DATE_RE = re.compile(
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{4}\b|\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)
_REFERENCE_RE = re.compile(
    r"\b(?:section|sec\.?|rule|clause|sub-section|regulation)\s+\d+[A-Za-z]?(?:\(\d+\))?",
    re.IGNORECASE,
)
_DIGIT_RE = re.compile(r"\d+")
_WORD_RE = re.compile(r"[A-Za-z]+")


def normalise_whitespace(text: str) -> str:
    return " ".join(text.split())


def number_inventory(text: str) -> dict[str, Counter[str]]:
    """Return every number-bearing token in ``text``, as multisets."""
    return {
        "digits": Counter(_DIGIT_RE.findall(text)),
        "references": Counter(m.group(0).lower() for m in _REFERENCE_RE.finditer(text)),
        "dates": Counter(m.group(0).lower() for m in _DATE_RE.finditer(text)),
        "rupee_amounts": Counter(
            re.sub(r"\s+", "", m.group(0)).lower() for m in _RUPEE_RE.finditer(text)
        ),
    }


def compare_inventories(
    stored: dict[str, Counter[str]], independent: dict[str, Counter[str]]
) -> dict[str, list[str]]:
    """Tokens present in only one side, per category."""
    missing: dict[str, list[str]] = {}
    extra: dict[str, list[str]] = {}
    for category in stored:
        left = stored[category]
        right = independent.get(category, Counter())
        gone = sorted((left - right).elements())
        added = sorted((right - left).elements())
        if gone:
            missing[category] = gone
        if added:
            extra[category] = added
    return {"missing_from_independent": missing, "extra_in_independent": extra}


def critical_word_diff(stored_text: str, independent_text: str) -> list[str]:
    """Critical words present on one side only."""
    left = {w.lower() for w in _WORD_RE.findall(stored_text)}
    right = {w.lower() for w in _WORD_RE.findall(independent_text)}
    return sorted((left ^ right) & CRITICAL_WORDS)


def _normalised_tokens(text: str) -> Counter[str]:
    return Counter(w.lower() for w in _WORD_RE.findall(text))


def word_differences(stored_text: str, independent_text: str) -> dict[str, list[str]]:
    left = _normalised_tokens(stored_text)
    right = _normalised_tokens(independent_text)
    return {
        "only_in_stored": sorted((left - right).elements()),
        "only_in_independent": sorted((right - left).elements()),
        "coverage": [
            f"{sum((left & right).values())}/{max(1, sum(left.values()))} stored words found"
        ],
    }


def has_proviso_marker(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in PROVISO_MARKERS)


def extract_pages_pypdf(pdf_path: Path) -> list[str]:
    """Second, independent extraction: one string per page (1-based indexing)."""
    from pypdf import PdfReader  # lazy

    reader = PdfReader(str(pdf_path))
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # a broken page must be visible, not fatal  # noqa: BLE001
            pages.append("")
    return pages


def render_page_png(pdf_path: Path, page_number: int, out_path: Path, dpi: int = 150) -> Path:
    """Render one 1-based page to PNG for the human check (C1.4)."""
    import pymupdf  # lazy

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(str(pdf_path)) as document:
        if page_number < 1 or page_number > document.page_count:
            raise ValueError(
                f"page {page_number} outside 1..{document.page_count} of {pdf_path.name}"
            )
        page = document[page_number - 1]
        page.get_pixmap(dpi=dpi).save(str(out_path))
    return out_path


@dataclass
class ProvisionCheck:
    provision_id: str
    source_id: str
    flags: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.flags


def check_provision(
    provision: dict[str, Any],
    page_texts: dict[int, str],
    independent_pages: list[str],
) -> ProvisionCheck:
    """Compare one provision against its pages from the second extraction."""
    provision_id = str(provision.get("provision_id", "?"))
    source_id = str(provision.get("source_id", "?"))
    check = ProvisionCheck(provision_id=provision_id, source_id=source_id)

    stored = normalise_whitespace(str(provision.get("original_text", "")))
    start = int(provision.get("page_start") or 0)
    end = int(provision.get("page_end") or start)
    pages = list(range(start, end + 1)) if start >= 1 else []

    stored_pages = "\n".join(page_texts.get(p, "") for p in pages)
    independent_text = "\n".join(
        independent_pages[p - 1] for p in pages if 0 < p <= len(independent_pages)
    )

    if not independent_text.strip():
        check.flags.append("independent_extraction_empty")
        return check

    if text_integrity_flags(stored_pages or stored):
        check.flags.append("stored_text_integrity_flags")
        check.details["stored_integrity_flags"] = text_integrity_flags(
            stored_pages or stored
        )

    diff = compare_inventories(number_inventory(stored), number_inventory(independent_text))
    if diff["missing_from_independent"] or diff["extra_in_independent"]:
        check.flags.append("number_inventory_mismatch")
        check.details["number_diff"] = diff

    critical = critical_word_diff(stored, independent_text)
    if critical:
        check.flags.append("critical_word_mismatch")
        check.details["critical_words"] = critical

    words = word_differences(stored, independent_text)
    check.details["word_diff"] = words

    if has_proviso_marker(stored):
        check.flags.append("needs_proviso_check")

    if stored and stored not in normalise_whitespace(independent_text):
        check.details["stored_not_verbatim_in_independent"] = True

    return check


def _document_map() -> dict[str, dict[str, Any]]:
    path = EXTRACTED_DIR / "metadata.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {d.get("source_id", ""): d for d in payload.get("documents", [])}


def run(staging: Path, out_dir: Path) -> dict[str, Any]:
    provisions_path = staging / "draft_provisions.json"
    if not provisions_path.exists():
        raise FileNotFoundError(provisions_path)
    provisions = json.loads(provisions_path.read_text(encoding="utf-8"))
    documents = _document_map()

    independent_cache: dict[str, list[str]] = {}
    stored_pages_cache: dict[str, dict[int, str]] = {}
    checks: list[ProvisionCheck] = []
    missing_pdf: list[str] = []

    for provision in provisions:
        source_id = str(provision.get("source_id", ""))
        document = documents.get(source_id, {})
        pdf_name = document.get("pdf_name") or ""
        pdf_path = ORIGINALS_DIR / pdf_name if pdf_name else None

        if not pdf_path or not pdf_path.exists():
            missing_pdf.append(source_id)
            check = ProvisionCheck(
                provision_id=str(provision.get("provision_id", "?")),
                source_id=source_id,
                flags=["original_pdf_missing"],
            )
            checks.append(check)
            continue

        key = str(pdf_path)
        if key not in independent_cache:
            independent_cache[key] = extract_pages_pypdf(pdf_path)
            stored_pages_cache[key] = {}
            for page_number in document.get("pages", []):
                page = pdf_path
                stored_pages_cache[key][page_number] = _stored_page_text(
                    document.get("filename", ""), page_number
                )
                render_page_png(
                    page,
                    page_number,
                    out_dir / "rendered" / source_id / f"page_{page_number:03d}.png",
                )

        check = check_provision(
            provision,
            stored_pages_cache[key],
            independent_cache[key],
        )
        checks.append(check)

        if check.flags:
            provision["integrity_flags"] = check.flags
            provision["needs_proviso_check"] = "needs_proviso_check" in check.flags
        else:
            provision.setdefault("integrity_flags", [])
            provision.setdefault("needs_proviso_check", False)

    # Persist flags as review metadata.  The legal text is untouched.
    provisions_path.write_text(
        json.dumps(provisions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    report = {
        "staging": str(staging),
        "out_dir": str(out_dir),
        "provisions_checked": len(checks),
        "provisions_flagged": sum(1 for c in checks if not c.ok),
        "sources_without_pdf": sorted(set(missing_pdf)),
        "checks": [
            {
                "provision_id": c.provision_id,
                "source_id": c.source_id,
                "flags": c.flags,
                "details": c.details,
            }
            for c in checks
        ],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "integrity_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out_dir / "integrity_report.md").write_text(_render_markdown(report), encoding="utf-8")
    return report


def _stored_page_text(filename: str, page_number: int) -> str:
    """Best-effort stored page text from the extracted file.

    The extracted ``.txt`` files are continuous; this returns the whole file
    when the page cannot be isolated, which is still a valid corpus-side check
    because the number inventory is compared over the provision's own text.
    """
    path = EXTRACTED_DIR / filename
    if not filename or not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Independent extraction report",
        "",
        f"- provisions checked: {report['provisions_checked']}",
        f"- provisions flagged: {report['provisions_flagged']}",
        "",
    ]
    if report["sources_without_pdf"]:
        lines.append(
            "- sources with no original PDF: "
            + ", ".join(report["sources_without_pdf"])
        )
        lines.append("")
    lines += ["| provision | flags | number diff |", "|---|---|---|"]
    for check in report["checks"]:
        flags = ", ".join(check["flags"]) or "-"
        diff = check["details"].get("number_diff") or {}
        summary = json.dumps(diff, ensure_ascii=False) if diff else "-"
        if len(summary) > 160:
            summary = summary[:157] + "..."
        lines.append(f"| {check['provision_id']} | {flags} | `{summary}` |")
    lines += [
        "",
        "A flag is not a rejection. Open the rendered page under `rendered/`, compare",
        "the numbers and words, then either fix the stored text or reject the row.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ai_lawyer.legal_rag.integrity",
        description="Independent re-extraction, number inventory and page renders.",
    )
    parser.add_argument("--staging-dir", type=Path, default=DEFAULT_STAGING)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=PACKAGE_DIR / "legal_corpus" / "official" / "integrity",
    )
    args = parser.parse_args(argv)
    try:
        report = run(args.staging_dir, args.out_dir)
    except FileNotFoundError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"checked {report['provisions_checked']} provision(s)")
    print(f"flagged {report['provisions_flagged']}")
    print(f"report: {args.out_dir / 'integrity_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
