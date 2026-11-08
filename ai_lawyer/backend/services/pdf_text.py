"""Per-page text extraction: text PDFs, scanned PDF pages (OCR) and images (OCR)."""
from __future__ import annotations

import logging

from ai_lawyer.backend.services.ocr import OCRFunc, OCRUnavailable, ocr_quality
from ai_lawyer.contracts.models import PageExtraction

logger = logging.getLogger(__name__)

OCR_DPI = 300


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


def _ocr_page(png: bytes, page_number: int, ocr: OCRFunc) -> tuple[PageExtraction, str | None]:
    text = ocr(png)
    quality, error = ocr_quality(text)
    return (
        PageExtraction(
            page_number=page_number,
            text=text if quality == "completed" else "",
            method="ocr",
            quality_status=quality,  # type: ignore[arg-type]
        ),
        error,
    )


def _status(pages: list[PageExtraction], first_error: str | None) -> tuple[str, str | None]:
    completed = [p for p in pages if p.quality_status == "completed"]
    if not completed:
        return "failed", first_error or "no_extractable_text"
    if len(completed) != len(pages):
        return "partial", first_error or "some_pages_have_no_text"
    return "completed", None


def extract_image_bytes(data: bytes, ocr: OCRFunc | None) -> tuple[list[PageExtraction], str, str | None]:
    """A screenshot or photo: normalise to PNG, then OCR it."""
    if ocr is None:
        return [], "failed", "ocr_unavailable"
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - dependency is pinned
        return [], "failed", "image_library_missing"
    try:
        pixmap = pymupdf.Pixmap(data)
        if pixmap.alpha:
            pixmap = pymupdf.Pixmap(pixmap, 0)  # drop transparency for OCR
        png = pixmap.tobytes("png")
    except Exception:  # noqa: BLE001
        return [], "failed", "image_corrupt"
    try:
        page, error = _ocr_page(png, 1, ocr)
    except OCRUnavailable:
        return [], "failed", "ocr_unavailable"
    status, error = _status([page], error)
    return [page], status, error


def extract_pdf_bytes(
    data: bytes, ocr: OCRFunc | None = None
) -> tuple[list[PageExtraction], str, str | None]:
    """Text layer first; a page with no text is OCR'd when OCR is available."""
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
        first_error: str | None = None
        for index, page in enumerate(doc, start=1):
            try:
                text = page.get_text("text") or ""
            except Exception:  # noqa: BLE001
                text = ""
            if text.strip():
                pages.append(PageExtraction(page_number=index, text=text,
                                            method="text_extraction", quality_status="completed"))
                continue
            if ocr is not None:
                try:
                    extraction, error = _ocr_page(page.get_pixmap(dpi=OCR_DPI).tobytes("png"), index, ocr)
                    pages.append(extraction)
                    first_error = first_error or error
                    continue
                except OCRUnavailable:
                    first_error = first_error or "ocr_unavailable"
            pages.append(PageExtraction(page_number=index, text="",
                                        method="text_extraction", quality_status="needs_user_retry"))
        if not pages:
            return [], "failed", "pdf_no_pages"
        status, error = _status(pages, first_error)
        return pages, status, error
    finally:
        doc.close()
