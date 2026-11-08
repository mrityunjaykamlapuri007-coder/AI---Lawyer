"""Image and scanned-PDF evidence via OCR (fake OCR: no Tesseract call in unit tests)."""
from __future__ import annotations

from datetime import date

import pytest

from ai_lawyer.backend.services.evidence_store import EvidenceStore
from ai_lawyer.backend.services.ocr import OCRUnavailable, ocr_quality
from ai_lawyer.backend.services.orchestrator import Upload
from ai_lawyer.contracts.errors import UserSafeError

RECEIPT = (
    "ShopEasy Demo Refund Notice\n"
    "Order: SM-7007\n"
    "Refund of INR 1,299 initiated on 12 October 2026 to the original payment method.\n"
)


def _png() -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=300, height=120)
    page.insert_text((10, 40), "screenshot", fontsize=14)
    return page.get_pixmap(dpi=72).tobytes("png")


def _jpeg() -> bytes:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=200, height=100)
    page.insert_text((10, 40), "photo", fontsize=14)
    return page.get_pixmap(dpi=72).tobytes("jpg")


def _scanned_pdf() -> bytes:
    """A PDF whose only page is an image: no text layer, like a phone scan."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=300, height=200)
    page.insert_image(page.rect, stream=_png())
    return doc.tobytes()


def _store(settings, text: str | None = RECEIPT, raises: bool = False):
    calls: list[bytes] = []

    def fake_ocr(png: bytes) -> str:
        calls.append(png)
        if raises:
            raise OCRUnavailable("no tesseract")
        return text or ""

    return EvidenceStore(settings, ocr=fake_ocr), calls


def test_png_screenshot_is_read_by_ocr(settings):
    store, calls = _store(settings)
    evidence = store.save("refund.png", _png())

    assert evidence.extraction_status == "completed"
    assert evidence.mime_type == "image/png"
    assert evidence.pages[0].method == "ocr"
    assert "SM-7007" in evidence.text
    assert calls and calls[0].startswith(b"\x89PNG")


def test_jpeg_photo_is_read_by_ocr(settings):
    store, _ = _store(settings)
    evidence = store.save("receipt.JPG", _jpeg())
    assert evidence.extraction_status == "completed"
    assert evidence.mime_type == "image/jpeg"


@pytest.mark.parametrize(
    "name,data",
    [("fake.png", b"%PDF-1.4 not an image"), ("fake.jpg", b"\x89PNG\r\n\x1a\nxx"), ("fake.jpeg", b"hello")],
)
def test_image_signature_spoof_is_rejected(settings, name, data):
    store, calls = _store(settings)
    with pytest.raises(UserSafeError) as exc:
        store.save(name, data)
    assert exc.value.error_code == "signature_mismatch"
    assert calls == []


def test_unreadable_image_fails_clearly(settings):
    store, _ = _store(settings, text="")
    evidence = store.save("blank.png", _png())
    assert (evidence.extraction_status, evidence.error_code) == ("failed", "ocr_no_text")
    assert evidence.text == ""


def test_garbled_ocr_is_not_used(settings):
    store, _ = _store(settings, text="~~|| ;; ^^ ~~ || ;; ^^ ~~ ||")
    evidence = store.save("blurry.png", _png())
    assert (evidence.extraction_status, evidence.error_code) == ("failed", "ocr_low_quality")


def test_missing_tesseract_fails_only_that_file(settings):
    store, _ = _store(settings, raises=True)
    evidence = store.save("refund.png", _png())
    assert (evidence.extraction_status, evidence.error_code) == ("failed", "ocr_unavailable")


def test_ocr_disabled_means_images_fail_with_a_reason(settings):
    store = EvidenceStore(settings, ocr=None)
    evidence = store.save("refund.png", _png())
    assert evidence.error_code == "ocr_unavailable"


def test_corrupt_image_fails_without_ocr_call(settings):
    store, calls = _store(settings)
    evidence = store.save("broken.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    assert (evidence.extraction_status, evidence.error_code) == ("failed", "image_corrupt")
    assert calls == []


def test_scanned_pdf_page_falls_back_to_ocr(settings):
    store, calls = _store(settings)
    evidence = store.save("scan.pdf", _scanned_pdf())
    assert evidence.extraction_status == "completed"
    assert evidence.pages[0].method == "ocr"
    assert len(calls) == 1


def test_scanned_pdf_without_ocr_keeps_old_behaviour(settings):
    evidence = EvidenceStore(settings, ocr=None).save("scan.pdf", _scanned_pdf())
    assert (evidence.extraction_status, evidence.error_code) == ("failed", "no_extractable_text")


def test_ocr_quality_rules():
    assert ocr_quality("Refund of INR 1,299 initiated")[0] == "completed"
    assert ocr_quality("  ")[1] == "ocr_no_text"


def test_pipeline_turns_a_screenshot_into_document_supported_facts(orchestrator, conversation, settings):
    store, _ = _store(settings)
    orchestrator.evidence_store = store

    response = orchestrator.handle_message(
        conversation_id=conversation.conversation_id,
        user_id=settings.demo_user_id,
        message="Here is a screenshot of the refund message for my cancelled order. The money has not arrived.",
        uploads=[Upload(filename="refund.png", data=_png())],
        as_of_date=date(2026, 11, 8),
    )

    processing = response.evidence_processing[0]
    assert processing.status == "completed" and processing.methods == ["ocr"]
    supported = [f for f in response.extracted_facts if f.status == "document_supported"]
    assert supported, response.extracted_facts
    assert all(f.page_number == 1 for f in supported)
    # The substring guard still applies: every document fact appears in the OCR text.
    assert all(f.raw_value.lower() in RECEIPT.lower() for f in supported)
