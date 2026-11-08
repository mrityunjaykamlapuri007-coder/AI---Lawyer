"""OCR for image evidence and scanned PDF pages (Tesseract, local CPU).

Images (screenshots or photos of refund messages, invoices, emails) and PDF
pages without a text layer are rendered to PNG and read by Tesseract.  The OCR
text is treated exactly like any other document text: facts are kept only if
their raw value is a substring of it, and they are marked document_supported
with the page and ``method="ocr"`` so the user is asked to check them.

No remote OCR: evidence never leaves the machine.  If Tesseract is missing the
file fails with ``ocr_unavailable``; other uploads continue.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

OCRFunc = Callable[[bytes], str]
MIN_CHARS = 15
MIN_ALNUM_RATIO = 0.5


class OCRUnavailable(RuntimeError):
    pass


def tesseract_ocr(png: bytes) -> str:
    """Read one PNG image with the local Tesseract binary."""
    from ai_lawyer.legal_rag.machine_verify import OcrUnavailable, tesseract_cmd

    try:
        command = tesseract_cmd()
    except OcrUnavailable as exc:
        raise OCRUnavailable(str(exc)) from exc
    with tempfile.TemporaryDirectory() as tmp:
        image = Path(tmp) / "page.png"
        image.write_bytes(png)
        result = subprocess.run(
            [command, str(image), "-", "-l", "eng", "--psm", "4"],
            capture_output=True,
            timeout=120,
        )
    if result.returncode != 0:
        raise OCRUnavailable("tesseract failed on the image")
    return result.stdout.decode("utf-8", errors="replace")


def default_ocr(enabled: bool) -> OCRFunc | None:
    return tesseract_ocr if enabled else None


def ocr_quality(text: str) -> tuple[str, str | None]:
    """(quality_status, error_code) for OCR output: empty or garbled text fails."""
    stripped = re.sub(r"\s+", "", text or "")
    if len(stripped) < MIN_CHARS:
        return "failed", "ocr_no_text"
    alnum = sum(ch.isalnum() for ch in stripped)
    if alnum / len(stripped) < MIN_ALNUM_RATIO:
        return "failed", "ocr_low_quality"
    return "completed", None
