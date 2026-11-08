"""Per-page text extraction for text-based PDFs.  OCR is DESIGN_ONLY in Tier 1."""
from __future__ import annotations

import logging

from ai_lawyer.contracts.models import PageExtraction

logger = logging.getLogger(__name__)


def extract_text_bytes(data: bytes) -> tuple[list[PageExtraction], str, str | None]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return [], "failed", "text_undecodable"
    if not text.strip():
        return [], "failed", "empty_text"
    return (
        [PageExtraction(page_number=1, text=text, method="pasted_text", quality_status="completed")],
        "completed",
        None,
    )


def extract_pdf_bytes(data: bytes) -> tuple[list[PageExtraction], str, str | None]:
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - dependency is pinned
        return [], "failed", "pdf_library_missing"

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:  # noqa: BLE001
        return [], "failed", "pdf_corrupt"

    try:
        if getattr(doc, "needs_pass", False):
            return [], "failed", "pdf_encrypted"
        pages: list[PageExtraction] = []
        for index, page in enumerate(doc, start=1):
            try:
                text = page.get_text("text") or ""
            except Exception:  # noqa: BLE001
                text = ""
            if text.strip():
                pages.append(
                    PageExtraction(
                        page_number=index,
                        text=text,
                        method="text_extraction",
                        quality_status="completed",
                    )
                )
            else:
                pages.append(
                    PageExtraction(
                        page_number=index,
                        text="",
                        method="text_extraction",
                        quality_status="needs_user_retry",
                    )
                )
        if not pages:
            return [], "failed", "pdf_no_pages"
        completed = [p for p in pages if p.quality_status == "completed"]
        if not completed:
            return pages, "failed", "no_extractable_text"
        if len(completed) != len(pages):
            return pages, "partial", "some_pages_have_no_text"
        return pages, "completed", None
    finally:
        doc.close()
