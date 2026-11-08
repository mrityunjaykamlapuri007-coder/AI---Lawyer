"""Evidence storage: generated keys, SHA-256, atomic write, no filename paths."""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path

from ai_lawyer.config.settings import Settings, get_settings
from ai_lawyer.contracts.errors import UserSafeError
from ai_lawyer.contracts.models import Evidence
from ai_lawyer.backend.services.ocr import OCRFunc, default_ocr
from ai_lawyer.backend.services.pdf_text import (
    extract_image_bytes,
    extract_pdf_bytes,
    extract_text_bytes,
)

_IMAGE_EXT = {".png", ".jpg", ".jpeg"}
_ALLOWED_EXT = {".pdf", ".txt", ".md"} | _IMAGE_EXT
_MIME = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
# File signatures: the extension alone is never trusted.
_SIGNATURES = {
    ".pdf": (b"%PDF",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
}
_UNSET = object()


def safe_filename(filename: str) -> str:
    name = Path(filename or "upload").name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    return name[:200] or "upload"


class EvidenceStore:
    def __init__(self, settings: Settings | None = None, ocr: OCRFunc | None | object = _UNSET) -> None:
        self.settings = settings or get_settings()
        self.root = self.settings.evidence_path
        self.root.mkdir(parents=True, exist_ok=True)
        # Tests inject a fake OCR; by default Tesseract is used when OCR_ENABLED.
        self.ocr = default_ocr(self.settings.ocr_enabled) if ocr is _UNSET else ocr

    def save(self, filename: str, data: bytes, case_id: str | None = None) -> Evidence:
        original = safe_filename(filename)
        ext = Path(original).suffix.lower()
        if ext not in _ALLOWED_EXT:
            raise UserSafeError(
                "unsupported_file_type",
                "Accepted files: PDF, PNG or JPG images (screenshots, photos), .txt and .md.",
                retryable=False,
                status_code=415,
            )
        if len(data) > self.settings.max_upload_bytes:
            raise UserSafeError(
                "file_too_large",
                f"The file is larger than the {self.settings.max_upload_mb} MB limit.",
                retryable=False,
                status_code=413,
            )
        if not data:
            raise UserSafeError("empty_file", "The uploaded file is empty.", status_code=400)
        if ext in _SIGNATURES and not data.startswith(_SIGNATURES[ext]):
            raise UserSafeError(
                "signature_mismatch",
                f"The file does not look like a real {ext.lstrip('.').upper()} (its signature is wrong).",
                status_code=400,
            )

        digest = hashlib.sha256(data).hexdigest()
        storage_key = f"{uuid.uuid4().hex}{ext}"
        target = self.root / storage_key
        temp = self.root / f".{storage_key}.tmp"
        with open(temp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp, target)

        if ext == ".pdf":
            pages, status, error = extract_pdf_bytes(data, self.ocr)
        elif ext in _IMAGE_EXT:
            pages, status, error = extract_image_bytes(data, self.ocr)
        else:
            pages, status, error = extract_text_bytes(data)

        return Evidence(
            case_id=case_id,
            original_filename=original,
            storage_key=storage_key,
            sha256=digest,
            mime_type=_MIME[ext],
            size_bytes=len(data),
            extraction_status=status,  # type: ignore[arg-type]
            error_code=error,
            pages=pages,
        )
