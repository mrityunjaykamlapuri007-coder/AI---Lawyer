"""Machine verification of staged provisions (no human in the loop).

Every provision must pass ALL of these before it becomes citable:

V1 two independent extractions: the PDF text layer and OCR of the rendered
   page.  Every word of the stored text must be found in the OCR text, in order.
V2 number inventory: every digit run, date, rupee amount and section/rule
   reference in the stored text must appear in the OCR text.
V3 document integrity: the PDF hash matches the recorded hash and
   ``text_integrity_flags`` is clean.
V4 metadata evidence: each date / gazette number has a verbatim quote and page
   from the OCR text.  A value with no quote is ``not_stated``, never inferred.
V5 boundary: the stored text is a contiguous span of the OCR text, the next
   words do not open a proviso/exception/explanation that was cut off, and the
   span holds no non-law text (signatory line, file number, gazette footer,
   digital-signature stamp).  Such text is rejected, never trimmed by code.
V6 amendment effect: the rule is not substituted by a recorded amendment.

A source is machine_verified only if its PDF is byte-identical to the Gazette
of India copy (``legal_rag.official_copy``); run that command first.

Any failure marks the provision ``rejected`` with the reason.  Nothing is ever
labelled ``human_verified`` here, and no person's name is written.

Usage::

    python -m ai_lawyer.legal_rag.machine_verify --source ECR_2020
    python -m ai_lawyer.legal_rag.machine_verify --source ECR_2020 --dry-run

OCR is Tesseract (found via ``TESSERACT_CMD``, ``PATH`` or the default Windows
install path).  If it is not installed the command refuses: a single
extraction method is not accepted.  RapidOCR was used up to pipeline 1.2 and
was replaced because it silently dropped whole lines (for example a definition
line in the Jurisdiction Rules), which failed provisions for OCR reasons.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ai_lawyer.contracts.models import Provision, Source
from ai_lawyer.legal_rag.english_extract import text_integrity_flags
from ai_lawyer.legal_rag.integrity import (
    has_proviso_marker,
    number_inventory,
    normalise_whitespace,
)
from ai_lawyer.legal_rag.official_copy import official_copy_problems

PACKAGE_DIR = Path(__file__).resolve().parents[1]
LEGAL_CORPUS = PACKAGE_DIR / "legal_corpus"
DEFAULT_STAGING = LEGAL_CORPUS / "official" / "draft_curated"
ORIGINALS_DIR = LEGAL_CORPUS / "official" / "originals"
OUT_DIR = LEGAL_CORPUS / "official" / "verification"
OCR_CACHE = LEGAL_CORPUS / "official" / "ocr"

# 200 dpi glued words together ("monthfromthedateof") and dropped short
# enumeration labels such as "(c)".  300 dpi reads them correctly.  The dpi is
# part of the cache filename so a cache from another setting is never reused.
OCR_DPI = 300

PIPELINE_VERSION = "machine-verify-1.3"
OCR_ENGINE = "tesseract"
CHECKS = (
    "V1_independent_extraction",
    "V2_number_inventory",
    "V3_document_integrity",
    "V4_metadata_evidence",
    "V5_boundary",
    "V6_amendment_effect",
)

_WORD_RE = re.compile(r"[a-z0-9]+")
_LIGATURES = {"\ufb01": "fi", "\ufb02": "fl", "\ufb00": "ff", "\ufb03": "ffi", "\ufb04": "ffl"}


class OcrUnavailable(RuntimeError):
    pass


# Text that a gazette prints around a notification but that is not law.
_NON_LAW_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("file_number", re.compile(r"\bF\.\s*No\.\s*\S")),
    ("signatory_designation", re.compile(r"\bSecy\.?(?=[\s,]|$)")),
    ("signatory_name_line", re.compile(r"^[A-Z][A-Z.]+(?: [A-Z][A-Z.]+)+,\s+\S", re.MULTILINE)),
    (
        "gazette_footer",
        re.compile(
            r"Uploaded by Dte\.|Controller of Publications|Government of India Press"
            r"|Digitally signed by|Signature Not Verified",
            re.IGNORECASE,
        ),
    ),
)
_HEADING_WORDS = ("CHAPTER", "PART", "SCHEDULE", "FORM", "APPENDIX", "ANNEXURE")


def non_law_markers(text: str) -> list[str]:
    """Name every kind of non-law text found in a stored provision."""
    found = [name for name, pattern in _NON_LAW_PATTERNS if pattern.search(text)]
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    # The heading of the next chapter ("CHAPTER II / CONSUMER PROTECTION
    # COUNCILS") belongs to the following provision, not this one.
    if any(line.startswith(_HEADING_WORDS) for line in lines[-2:]):
        found.append("trailing_next_heading")
    # A digital-signature stamp renders as bare upper-case name lines after
    # the last sentence ("SURENDER / MAHADASAM").  Legal text ends in
    # punctuation, so an upper-case word line at the very end is not law.
    elif lines and re.fullmatch(r"[A-Z]{3,}(?: [A-Z]{2,})*", lines[-1]):
        found.append("trailing_uppercase_name_line")
    return found


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def normalise_for_compare(text: str) -> str:
    for source, target in _LIGATURES.items():
        text = text.replace(source, target)
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    return text


def tokens(text: str) -> list[str]:
    return _WORD_RE.findall(normalise_for_compare(text).lower())


def _in_order_subsequence(needle: list[str], haystack: list[str]) -> tuple[int, int | None, int | None]:
    """Return (matched, first_index, last_index) for an in-order match."""
    matched = 0
    first: int | None = None
    last: int | None = None
    position = 0
    for token in needle:
        while position < len(haystack) and haystack[position] != token:
            position += 1
        if position >= len(haystack):
            return matched, first, last
        if first is None:
            first = position
        last = position
        matched += 1
        position += 1
    return matched, first, last


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------
_WINDOWS_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


def tesseract_cmd() -> str:
    import os
    import shutil

    explicit = os.environ.get("TESSERACT_CMD")
    if explicit and Path(explicit).exists():
        return explicit
    found = shutil.which("tesseract")
    if found:
        return found
    if _WINDOWS_TESSERACT.exists():
        return str(_WINDOWS_TESSERACT)
    raise OcrUnavailable(
        "Tesseract is not installed; V1 needs a second, independent extraction "
        "method and will not run without OCR"
    )


def ocr_engine_version() -> str:
    import subprocess

    result = subprocess.run(
        [tesseract_cmd(), "--version"], capture_output=True, text=True, timeout=60
    )
    first = (result.stdout or result.stderr).splitlines()
    return first[0].strip() if first else "tesseract (unknown version)"


def _default_ocr(image_path: Path) -> str:
    import subprocess

    result = subprocess.run(
        [tesseract_cmd(), str(image_path), "-", "-l", "eng", "--psm", "4"],
        capture_output=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise OcrUnavailable(
            f"tesseract failed on {image_path.name}: "
            + result.stderr.decode("utf-8", errors="replace")[:200]
        )
    return result.stdout.decode("utf-8", errors="replace")


def _cache_path(pdf_name: str, page_number: int, dpi: int = OCR_DPI) -> Path:
    # The engine is part of the name so output from another engine is never reused.
    stem = pdf_name.replace(".pdf", "")
    return OCR_CACHE / stem / f"page_{OCR_ENGINE}_{dpi:03d}_{page_number:03d}.txt"


def ocr_page(
    pdf_path: Path,
    page_number: int,
    *,
    ocr: Callable[[Path], str] | None = None,
    cache: bool = True,
    dpi: int = OCR_DPI,
) -> str:
    cached = _cache_path(pdf_path.name, page_number, dpi)
    if cache and cached.exists() and cached.read_text(encoding="utf-8").strip():
        return cached.read_text(encoding="utf-8")

    import pymupdf  # lazy

    with pymupdf.open(str(pdf_path)) as document:
        if page_number < 1 or page_number > document.page_count:
            raise ValueError(f"page {page_number} outside the document")
        stem = pdf_path.name.replace(".pdf", "")
        png = OCR_CACHE / stem / f"page_{dpi:03d}_{page_number:03d}.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        document[page_number - 1].get_pixmap(dpi=dpi).save(str(png))

    text = (ocr or _default_ocr)(png)
    if cache:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(text, encoding="utf-8")
    return text


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def _number_gaps(stored: str, independent: str) -> dict[str, list[str]]:
    left = number_inventory(stored)
    right = number_inventory(independent)
    gaps: dict[str, list[str]] = {}
    for category, counter in left.items():
        missing = sorted((counter - right[category]).elements())
        if missing:
            gaps[category] = missing
    return gaps


def _date_variants(iso: str) -> list[str]:
    value = date.fromisoformat(iso)
    day, month, year = value.day, value.strftime("%B"), value.year
    return [
        f"{day} {month} {year}",
        f"{day} {month}, {year}",
        f"{day}{_ordinal(day)} {month} {year}",
        f"{day}{_ordinal(day)} {month}, {year}",
        f"{day:02d}/{month[:3]}/{year}",
        f"{month} {day}, {year}",
        f"{month} {day} {year}",
        iso,
    ]


def _ordinal(day: int) -> str:
    if 10 <= day % 100 <= 20:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


def _find_quote(field: str, value: str, ocr_pages: dict[int, str]) -> tuple[str, int] | None:
    if field in {"published_date", "effective_from"}:
        candidates = _date_variants(value)
    elif field == "gazette_id":
        candidates = [value, value.replace("/", " / "), value.replace(" ", "")]
    else:
        candidates = [value]
    for page_number, page_text in sorted(ocr_pages.items()):
        haystack = normalise_whitespace(page_text)
        haystack_lower = haystack.lower()
        compact = re.sub(r"\s+", "", haystack_lower)
        for candidate in candidates:
            position = haystack_lower.find(candidate.lower())
            if position >= 0:
                return haystack[position : position + len(candidate)], page_number
            compact_candidate = re.sub(r"\s+", "", candidate.lower())
            compact_position = compact.find(compact_candidate)
            if compact_position >= 0:
                # Return the canonical spelling, not the de-spaced OCR form.
                return candidate, page_number
    return None


def _rule_number(citation: str) -> int | None:
    match = re.search(r"\bprovision\s+(\d+)\b", citation or "", re.IGNORECASE)
    return int(match.group(1)) if match else None


def _sub_rule_number(citation: str) -> int | None:
    match = re.search(r"\bsub-rule\s*\((\d+)\)\s*$", citation or "", re.IGNORECASE)
    return int(match.group(1)) if match else None


def _affected_sub_rules(text: str) -> dict[str, list[int]]:
    """'in rule 4, for sub-rule (1)' -> {'4': [1]}.  Absent means whole rule."""
    found: dict[str, set[int]] = {}
    for rule, sub in re.findall(
        r"\bin rule\s+(\d+)\s*,\s*for sub-rule\s*\((\d+)\)", text, re.IGNORECASE
    ):
        found.setdefault(rule, set()).add(int(sub))
    return {rule: sorted(subs) for rule, subs in found.items()}


def substitution_hits(
    entry: dict[str, Any], rule_number: int | None, sub_rule: int | None
) -> bool:
    """True when this amendment substitutes text this provision contains."""
    if entry.get("status") != "checked" or entry.get("effect") != "substitution":
        return False
    if rule_number is None or rule_number not in entry.get("affected_rules", []):
        return False
    subs = (entry.get("affected_sub_rules") or {}).get(str(rule_number))
    if not subs:
        return True  # the amendment's scope inside the rule is unknown: whole rule
    if sub_rule is None:
        return True  # this provision holds the whole rule, including the substituted part
    return sub_rule in subs


def _document_metadata(source_id: str) -> dict[str, Any]:
    path = LEGAL_CORPUS / "official" / "extracted_en" / "metadata.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    for document in payload.get("documents", []):
        if document.get("source_id") == source_id:
            return document
    return {}


def _manifest_entry(source_id: str, pdf_name: str = "") -> dict[str, Any]:
    """The supplied download manifest for this source (C2.2 cross-check)."""
    path = LEGAL_CORPUS / "official" / "manifest.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    for document in payload.get("documents", []):
        if document.get("document_id") == source_id:
            return document
    for document in payload.get("documents", []):
        if pdf_name and document.get("file") == pdf_name:
            return document
    return {}


def _all_manifest_entries() -> list[dict[str, Any]]:
    path = LEGAL_CORPUS / "official" / "manifest.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("documents", [])


def _candidate_metadata(source: dict[str, Any], manifest: dict[str, Any]) -> dict[str, str]:
    """Values to look for in the document.  Source first, manifest second."""
    return {
        "published_date": source.get("published_date")
        or manifest.get("instrument_date")
        or "",
        "effective_from": source.get("effective_from")
        or manifest.get("effective_from")
        or "",
        "gazette_id": (source.get("metadata_quotes") or {}).get("gazette_id")
        or manifest.get("gazette_id_as_printed")
        or "",
    }


def _instrument_key(text: str) -> str:
    """Reduce an instrument description to its stable number, e.g. 'gsr 328e'."""
    lowered = normalise_for_compare(text or "").lower()
    match = re.search(r"g\.?\s*s\.?\s*r\.?\s*(\d+)\s*\(\s*e\s*\)", lowered)
    if match:
        return f"gsr-{match.group(1)}e"
    match = re.search(r"\b(\d{1,5})\s*/\s*(\d{4})\b", lowered)
    if match:
        return f"no-{match.group(1)}-{match.group(2)}"
    return ""


def _label_correction_pairs(text: str) -> list[tuple[str, str]]:
    """Return 'for X, read Y' pairs from a corrigendum, if any."""
    pattern = re.compile(
        r"for\s*[\u201c\"']([^\u201d\"']{1,6})[\u201d\"']\s*,?\s*read\s*"
        r"[\u201c\"']([^\u201d\"']{1,6})[\u201d\"']",
        re.IGNORECASE,
    )
    return pattern.findall(text)


def _amendment_effect(entry: dict[str, Any]) -> dict[str, Any]:
    """Read the supplied amending instrument and record what it changes.

    The effect is derived only from the supplied extracted text.  An amendment
    whose text was not extracted is ``unchecked``; it is never assumed to be
    harmless.
    """
    document_id = entry.get("document_id", "")
    extracted = entry.get("extracted_file") or ""
    path = LEGAL_CORPUS / "official" / extracted if extracted else None
    if not path or not path.exists():
        return {
            "status": "unchecked",
            "note": "amending instrument text was not extracted",
            "document_id": document_id,
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    rules = sorted({int(m) for m in re.findall(r"\bin rule\s+(\d+)", text, re.IGNORECASE)})
    pairs = _label_correction_pairs(text)
    labels_only = bool(pairs) and all(
        len(left.strip("() ")) == 1 and len(right.strip("() ")) == 1
        for left, right in pairs
    )
    effect: dict[str, Any] = {
        "status": "checked",
        "document_id": document_id,
        "affected_rules": rules,
        "affected_sub_rules": _affected_sub_rules(text),
        "effective_from": entry.get("effective_from") or entry.get("instrument_date"),
        "version_status": entry.get("version_status"),
    }
    if entry.get("version_status") == "future":
        effect["effect"] = "future"
        effect["note"] = "not in force on the verification date"
    elif labels_only:
        effect["effect"] = "label_correction"
        effect["note"] = "enumeration labels only; no substantive text substituted"
    elif rules:
        effect["effect"] = "substitution"
        effect["note"] = "substitutes text in the listed rules; consolidated text not rebuilt"
    else:
        effect["status"] = "unchecked"
        effect["effect"] = "unknown"
        effect["note"] = "could not identify the amended rule from the text"
    return effect


def amendment_status(
    chain: list[str], manifest_entries: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve each amendment against the supplied documents and read its text.

    ``checked`` means the instrument is present, its text was read, and the
    effect was classified.  It never means the amended text was applied to a
    principal provision; provisions whose rule is substituted are excluded
    separately.
    """
    by_key = {
        _instrument_key(entry.get("instrument_number", "")): entry
        for entry in manifest_entries
        if _instrument_key(entry.get("instrument_number", ""))
    }
    entries: list[dict[str, Any]] = []
    gaps: list[str] = []
    for instrument in chain:
        key = _instrument_key(instrument)
        entry = by_key.get(key)
        if entry is None:
            entries.append(
                {
                    "instrument": instrument,
                    "status": "unchecked",
                    "note": "not present in the supplied document set",
                }
            )
            gaps.append(f"amendment not ingested: {instrument}")
            continue
        effect = _amendment_effect(entry)
        effect["instrument"] = instrument
        entries.append(effect)
        if effect["status"] != "checked":
            gaps.append(f"amendment effect unknown: {instrument}")
    return entries, gaps


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_provision(
    provision: dict[str, Any],
    source: dict[str, Any],
    pdf_path: Path,
    *,
    ocr_pages: dict[int, str],
    stored_pages: dict[int, str],
    document: dict[str, Any],
    ocr: Callable[[Path], str] | None = None,
) -> dict[str, Any]:
    pid = str(provision.get("provision_id"))
    start = int(provision.get("page_start") or 1)
    end = int(provision.get("page_end") or start)
    pages = list(range(start, end + 1))

    stored = normalise_whitespace(str(provision.get("original_text", "")))
    independent = "\n".join(ocr_pages[p] for p in pages if p in ocr_pages)
    evidence: dict[str, Any] = {"pipeline_version": PIPELINE_VERSION, "pages": pages}
    flags: list[str] = []

    # V1 - independent extraction, word by word.
    stored_tokens = tokens(stored)
    independent_tokens = tokens(independent)
    matched, first, last = _in_order_subsequence(stored_tokens, independent_tokens)
    missing_words = [t for t in stored_tokens]
    if matched == len(stored_tokens) and stored_tokens:
        evidence["V1_independent_extraction"] = "pass"
        evidence["V1_detail"] = {"stored_tokens": len(stored_tokens), "matched": matched}
    else:
        evidence["V1_independent_extraction"] = "fail"
        present = set(independent_tokens)
        missing_words = [t for t in dict.fromkeys(stored_tokens) if t not in present]
        evidence["V1_detail"] = {
            "stored_tokens": len(stored_tokens),
            "matched_in_order": matched,
            "sample_missing": missing_words[:40],
        }
        flags.append("V1_word_mismatch")

    # V2 - number inventory, zero tolerance.
    gaps = _number_gaps(stored, independent)
    if gaps:
        evidence["V2_number_inventory"] = "fail"
        evidence["V2_detail"] = {"missing_from_ocr": gaps}
        flags.append("V2_number_mismatch")
    else:
        evidence["V2_number_inventory"] = "pass"

    # V3 - document integrity.
    recorded = document.get("pdf_sha256") or source.get("document_sha256")
    actual = _sha256(pdf_path)
    page_text = "\n".join(stored_pages.get(p, "") for p in pages) or stored
    integrity = text_integrity_flags(page_text)
    if recorded and actual != recorded:
        evidence["V3_document_integrity"] = "fail"
        evidence["V3_detail"] = {"reason": "pdf_sha256_mismatch", "recorded": recorded, "actual": actual}
        flags.append("V3_hash_mismatch")
    elif integrity:
        evidence["V3_document_integrity"] = "fail"
        evidence["V3_detail"] = {"reason": "text_integrity_flags", "flags": integrity}
        flags.append("V3_text_integrity")
    else:
        evidence["V3_document_integrity"] = "pass"

    # V5 - boundary: contiguous span and no cut-off proviso.
    if first is not None and last is not None and matched == len(stored_tokens):
        trailing = independent_tokens[last + 1 : last + 6]
        joined = " ".join(trailing)
        if any(
            joined.startswith(marker)
            for marker in ("provided that", "provided further", "except", "subject to", "explanation")
        ):
            evidence["V5_boundary"] = "fail"
            evidence["V5_detail"] = {"reason": "trailing_proviso_cut_off", "trailing": trailing}
            flags.append("V5_trailing_proviso")
        else:
            evidence["V5_boundary"] = "pass"
    else:
        evidence["V5_boundary"] = "fail"
        evidence["V5_detail"] = {"reason": "stored_text_not_a_contiguous_span_of_ocr"}
        flags.append("V5_not_contiguous")

    non_law = non_law_markers(str(provision.get("original_text", "")))
    if non_law:
        evidence["V5_boundary"] = "fail"
        evidence["V5_detail"] = {
            **evidence.get("V5_detail", {}),
            "reason_non_law": "stored text contains non-law text",
            "non_law_markers": non_law,
        }
        flags.append("V5_non_law_text")

    if has_proviso_marker(stored):
        evidence["V5_detail"] = {
            **evidence.get("V5_detail", {}),
            "contains_proviso_marker": True,
        }

    return {"provision_id": pid, "evidence": evidence, "flags": flags}


def verify_source(
    source_id: str,
    staging: Path,
    *,
    dry_run: bool = False,
    ocr: Callable[[Path], str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    sources_path = staging / "draft_sources.json"
    provisions_path = staging / "draft_provisions.json"
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    provisions = json.loads(provisions_path.read_text(encoding="utf-8"))

    source = next((s for s in sources if s.get("source_id") == source_id), None)
    if source is None:
        raise KeyError(f"unknown source_id: {source_id}")
    rows = [p for p in provisions if p.get("source_id") == source_id]
    if limit is not None:
        rows = rows[:limit]

    document = _document_metadata(source_id)
    pdf_name = document.get("pdf_name") or document.get("file") or ""
    pdf_path = ORIGINALS_DIR / pdf_name if pdf_name else None
    if not pdf_path or not pdf_path.exists():
        raise FileNotFoundError(f"original PDF for {source_id} not found ({pdf_name!r})")

    pages: list[int] = []
    for row in rows:
        pages.extend(range(int(row.get("page_start") or 1), int(row.get("page_end") or 1) + 1))
    # The gazette number and issue date are printed on the cover page, which no
    # provision body spans.  OCR it too, or V4 can never quote them.
    import pymupdf  # lazy

    with pymupdf.open(str(pdf_path)) as opened:
        page_count = opened.page_count
    pages.extend(range(1, min(2, page_count) + 1))
    pages = sorted(set(pages))

    ocr_pages = {p: ocr_page(pdf_path, p, ocr=ocr) for p in pages}
    stored_pages = {p: _stored_page_text(document.get("filename", "")) for p in pages}

    report = {
        "source_id": source_id,
        "pdf": pdf_name,
        "pdf_sha256": _sha256(pdf_path),
        "pipeline_version": PIPELINE_VERSION,
        "ocr_engine": ocr_engine_version() if ocr is None else "injected (test)",
        "ocr_dpi": OCR_DPI,
        "provisions": [],
    }

    # V4 - metadata evidence, computed once per source.  Values come from the
    # staging record or the supplied manifest; the document must confirm them.
    manifest = _manifest_entry(source_id, document.get("pdf_name", ""))
    metadata = _candidate_metadata(source, manifest)
    quote_results: dict[str, Any] = {}
    for field, value in metadata.items():
        if not value:
            quote_results[field] = {"status": "missing"}
            continue
        found = _find_quote(field, str(value), ocr_pages)
        if found:
            quote, page_number = found
            quote_results[field] = {"status": "quoted", "quote": quote, "page": page_number}
        else:
            quote_results[field] = {"status": "not_stated", "value_checked": str(value)}
    report["metadata_evidence"] = quote_results

    chain, gaps = amendment_status(manifest.get("amendment_chain", []), _all_manifest_entries())
    report["amendment_chain"] = chain
    report["known_gaps"] = gaps
    chain_clean = all(entry["status"] == "checked" for entry in chain)

    v4_ok = (
        quote_results.get("published_date", {}).get("status") == "quoted"
        and quote_results.get("effective_from", {}).get("status") == "quoted"
        and quote_results.get("gazette_id", {}).get("status") in {"quoted", "missing"}
        and chain_clean
    )

    for row in rows:
        result = verify_provision(
            row,
            source,
            pdf_path,
            ocr_pages=ocr_pages,
            stored_pages=stored_pages,
            document=document,
            ocr=ocr,
        )
        evidence = result["evidence"]
        # V4 applies to every provision of the source.
        evidence["V4_metadata_evidence"] = "pass" if v4_ok else "fail"
        evidence["V4_detail"] = {
            "metadata": quote_results,
            "amendment_chain_clean": chain_clean,
            "known_gaps": gaps,
        }
        if not v4_ok:
            result["flags"].append("V4_metadata_unquoted")

        rule_number = _rule_number(str(row.get("citation", "")))
        sub_rule = _sub_rule_number(str(row.get("citation", "")))
        substituted_by = [
            entry for entry in chain if substitution_hits(entry, rule_number, sub_rule)
        ]
        if substituted_by:
            evidence["V6_amendment_effect"] = "fail"
            evidence["V6_detail"] = {
                "reason": "this rule is substituted by an amending instrument; the "
                "consolidated text was not rebuilt",
                "instruments": [entry["instrument"] for entry in substituted_by],
            }
            result["flags"].append("V6_amendment_text_changed")
        else:
            evidence["V6_amendment_effect"] = "pass"
            evidence["V6_detail"] = {
                "rule_number": rule_number,
                "sub_rule": sub_rule,
                "checked_instruments": [entry["instrument"] for entry in chain],
            }

        passed = all(evidence[check] == "pass" for check in CHECKS)
        report["provisions"].append(
            {
                "provision_id": result["provision_id"],
                "passed": passed,
                "flags": result["flags"],
                "evidence": evidence,
            }
        )

        if not dry_run:
            row["verification_evidence"] = {
                **{key: evidence[key] for key in CHECKS},
                "ocr_engine": report["ocr_engine"],
            }
            row["verification_method_count"] = 2
            row["pipeline_version"] = PIPELINE_VERSION
            row["verified_at"] = datetime.now(timezone.utc).isoformat()
            if passed:
                row["review_status"] = "machine_verified"
                row["verified_by"] = "machine"
                row["review_note"] = None
            else:
                row["review_status"] = "rejected"
                row["verified_by"] = "machine"
                row["review_note"] = "machine verification failed: " + ", ".join(
                    result["flags"]
                )

    # A source is machine_verified when its document identity and metadata are
    # proven and at least one provision passed every check.  Each provision is
    # still verified on its own; an OCR failure in one provision must not make
    # an unrelated verified provision uncitable.
    official_problems = official_copy_problems(
        source_id, source.get("official_copy"), report["pdf_sha256"]
    )
    report["official_copy"] = {
        "result": (source.get("official_copy") or {}).get("result", "not_checked"),
        "url": (source.get("official_copy") or {}).get("url"),
        "problems": official_problems,
    }
    source_passed = (
        v4_ok
        and chain_clean
        and not official_problems
        and any(p["passed"] for p in report["provisions"])
    )
    report["source_passed"] = source_passed

    if not dry_run:
        now = datetime.now(timezone.utc).isoformat()
        source["verification_evidence"] = {
            "metadata": report["metadata_evidence"],
            "amendment_chain": chain,
            "known_gaps": gaps,
            "pipeline_version": PIPELINE_VERSION,
            "pdf_sha256": report["pdf_sha256"],
            "provisions_passed": sum(1 for p in report["provisions"] if p["passed"]),
            "provisions_checked": len(report["provisions"]),
        }
        source["pipeline_version"] = PIPELINE_VERSION
        source["verified_at"] = now
        source["amendment_chain"] = chain
        source["known_gaps"] = gaps
        source["amendment_chain_checked"] = chain_clean
        if not source.get("official_url") and manifest.get("official_url"):
            source["official_url"] = manifest["official_url"]
        if not source.get("document_sha256") and manifest.get("sha256"):
            source["document_sha256"] = manifest["sha256"]
        if not source.get("publisher") and manifest.get("publisher"):
            source["publisher"] = manifest["publisher"]
        if report["source_passed"]:
            source["review_status"] = "machine_verified"
            source["verified_by"] = "machine"
            if manifest.get("version_status"):
                source["version_status"] = manifest["version_status"]
            source["version_label"] = f"machine-verified-{PIPELINE_VERSION}"
            source["notes"] = (
                (source.get("notes") or "").rstrip()
                + " Machine-verified by the automated pipeline; NOT reviewed by a "
                "lawyer or a human."
            ).strip()
            quotes = {
                field: item["quote"]
                for field, item in report["metadata_evidence"].items()
                if item.get("status") == "quoted"
            }
            pages_map = {
                field: item["page"]
                for field, item in report["metadata_evidence"].items()
                if item.get("status") == "quoted"
            }
            source["metadata_quotes"] = {**source.get("metadata_quotes", {}), **quotes}
            source["metadata_quote_pages"] = {
                **source.get("metadata_quote_pages", {}),
                **pages_map,
            }
            if "published_date" in quotes:
                source["published_date"] = metadata["published_date"]
            if "effective_from" in quotes:
                source["effective_from"] = metadata["effective_from"]
            source["effective_date_status"] = (
                "stated" if "effective_from" in quotes else "not_stated"
            )
        else:
            source["review_status"] = "unverified"
            source["verified_by"] = None

        sources_path.write_text(
            json.dumps(sources, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        provisions_path.write_text(
            json.dumps(provisions, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    out = OUT_DIR / source_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for item in report["provisions"]:
        (out / f"{item['provision_id']}.json").write_text(
            json.dumps(item, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return report


def _stored_page_text(filename: str) -> str:
    path = LEGAL_CORPUS / "official" / "extracted_en" / filename
    if not filename or not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ai_lawyer.legal_rag.machine_verify",
        description="Machine-verify a source's provisions (V1-V5).",
    )
    parser.add_argument("--source", required=True, help="source_id to verify")
    parser.add_argument("--staging-dir", type=Path, default=DEFAULT_STAGING)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = verify_source(
            args.source, args.staging_dir, dry_run=args.dry_run, limit=args.limit
        )
    except OcrUnavailable as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (KeyError, FileNotFoundError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    passed = sum(1 for p in report["provisions"] if p["passed"])
    total = len(report["provisions"])
    print(f"source      : {report['source_id']}")
    print(f"pdf         : {report['pdf']}")
    print(f"provisions  : {total}, passed: {passed}, rejected: {total - passed}")
    print(f"source pass : {report['source_passed']}")
    print(f"official copy: {report['official_copy']['result']}")
    for problem in report["official_copy"]["problems"]:
        print(f"  - {problem}")
    for field, item in report["metadata_evidence"].items():
        print(f"  {field}: {item.get('status')} {item.get('quote', '')!r}")
    for item in report["provisions"]:
        failed = [c for c in CHECKS if item["evidence"][c] != "pass"]
        print(
            f"  {item['provision_id']}: {'PASS' if item['passed'] else 'REJECT'}"
            + (f" ({', '.join(failed)})" if failed else "")
        )
    print(f"report: {OUT_DIR / report['source_id'] / 'report.json'}")
    return 0 if report["source_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
