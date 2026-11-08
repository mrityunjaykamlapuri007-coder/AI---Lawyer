from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ai_lawyer.legal_rag.corpus_acceptance import real_corpus_problems
from ai_lawyer.legal_rag.corpus_loader import load_corpus
from ai_lawyer.legal_rag.machine_verify import CHECKS, non_law_markers, verify_provision
from ai_lawyer.legal_rag.official_copy import (
    RefusedUrl,
    check_official_copy,
    official_copy_problems,
    record,
)

PACKAGE = Path(__file__).resolve().parents[2]

GAZETTE_URL = "https://egazette.gov.in/WriteReadData/2099/000001.pdf"
OFFICIAL_COPY = {
    "url": GAZETTE_URL,
    "host": "egazette.gov.in",
    "final_url": GAZETTE_URL,
    "http_status": 200,
    "local_sha256": "a" * 64,
    "sha256": "a" * 64,
    "result": "byte_identical",
}

SOURCE = {
    "source_id": "MACHINE_ACT",
    "title": "Machine fixture source",
    "source_type": "act",
    "publisher": "Test Publisher",
    "official_url": "https://example.invalid/act.pdf",
    "published_date": "2020-07-23",
    "retrieved_at": "2026-11-08",
    "document_sha256": "a" * 64,
    "review_status": "machine_verified",
    "version_label": "fixture",
    "effective_from": "2020-07-23",
    "effective_to": None,
    "version_status": "current",
    "amendment_chain": [{"instrument": "Test Amendment 2021", "status": "checked"}],
    "amendment_chain_checked": True,
    "known_gaps": [],
    "metadata_quotes": {"published_date": "23rd July, 2020"},
    "metadata_quote_pages": {"published_date": 1},
    "effective_date_status": "stated",
    "verified_by": "machine",
    "verified_at": "2026-11-08T10:00:00Z",
    "verification_evidence": {"pipeline_version": "test", "provisions_checked": 1},
    "pipeline_version": "test",
    "official_copy": OFFICIAL_COPY,
    "reviewed_by": None,
    "reviewed_at": None,
    "notes": "",
}

EVIDENCE = {check: "pass" for check in CHECKS}

PROVISION = {
    "provision_id": "MACHINE_ACT_S1",
    "source_id": "MACHINE_ACT",
    "citation": "Section 1 of the machine fixture",
    "hierarchy_type": "section",
    "parent_provision_id": None,
    "original_text": "A seller must refund a cancelled order within the stated period.",
    "search_text": "refund",
    "provisos": [],
    "exceptions": [],
    "definitions_used": [],
    "cross_references": [],
    "mandatory_context": [],
    "conditions": [],
    "page_start": 1,
    "page_end": 1,
    "review_status": "machine_verified",
    "reviewed_by": None,
    "reviewed_at": None,
    "review_note": None,
    "verified_by": "machine",
    "verified_at": "2026-11-08T10:00:00Z",
    "verification_method_count": 2,
    "verification_evidence": EVIDENCE,
    "pipeline_version": "test",
    "integrity_flags": [],
    "needs_proviso_check": False,
}


def _write(tmp_path: Path, sources, provisions) -> None:
    (tmp_path / "sources.json").write_text(json.dumps(sources), encoding="utf-8")
    (tmp_path / "provisions.json").write_text(json.dumps(provisions), encoding="utf-8")


def test_machine_verified_corpus_is_accepted_and_citable(tmp_path):
    _write(tmp_path, [deepcopy(SOURCE)], [deepcopy(PROVISION)])

    corpus = load_corpus("real", corpus_dir=tmp_path)

    assert corpus.usable_count == 1
    assert corpus.is_usable("MACHINE_ACT_S1")
    assert real_corpus_problems(corpus) == []


def test_machine_source_without_checked_amendments_is_rejected(tmp_path):
    source = {
        **deepcopy(SOURCE),
        "amendment_chain_checked": False,
        "amendment_chain": [{"instrument": "Test Amendment 2021", "status": "unchecked"}],
    }
    _write(tmp_path, [source], [deepcopy(PROVISION)])

    with pytest.raises(Exception) as exc:
        load_corpus("real", corpus_dir=tmp_path)

    assert any("amendment" in e for e in exc.value.errors)


def test_machine_provision_with_one_extraction_method_is_rejected(tmp_path):
    provision = {**deepcopy(PROVISION), "verification_method_count": 1}
    _write(tmp_path, [deepcopy(SOURCE)], [provision])

    with pytest.raises(Exception) as exc:
        load_corpus("real", corpus_dir=tmp_path)

    assert any("two independent extraction methods" in e for e in exc.value.errors)


def test_machine_provision_with_failed_check_is_rejected(tmp_path):
    evidence = {**EVIDENCE, "V2_number_inventory": "fail"}
    provision = {**deepcopy(PROVISION), "verification_evidence": evidence}
    _write(tmp_path, [deepcopy(SOURCE)], [provision])

    with pytest.raises(Exception) as exc:
        load_corpus("real", corpus_dir=tmp_path)

    assert any("V2_number_inventory did not pass" in e for e in exc.value.errors)


def test_machine_condition_without_quote_is_rejected(tmp_path):
    provision = deepcopy(PROVISION)
    provision["conditions"] = [
        {
            "condition_id": "C1",
            "description": "refund still pending",
            "fact_type": "refund_status",
            "operator": "equals",
            "expected_value": "pending",
            "human_review_status": "unreviewed",
            "source_quote": "",
            "drafted_by": "agent",
            "machine_review_status": "machine_verified",
        }
    ]
    _write(tmp_path, [deepcopy(SOURCE)], [provision])

    with pytest.raises(Exception) as exc:
        load_corpus("real", corpus_dir=tmp_path)

    assert any("neither human-reviewed nor machine-verified with a source quote" in e for e in exc.value.errors)


def test_machine_condition_with_quote_passes(tmp_path):
    provision = deepcopy(PROVISION)
    provision["conditions"] = [
        {
            "condition_id": "C1",
            "description": "refund still pending",
            "fact_type": "refund_status",
            "operator": "equals",
            "expected_value": "pending",
            "human_review_status": "unreviewed",
            "source_quote": "refund a cancelled order",
            "drafted_by": "agent",
            "machine_review_status": "machine_verified",
        }
    ]
    _write(tmp_path, [deepcopy(SOURCE)], [provision])

    corpus = load_corpus("real", corpus_dir=tmp_path)

    assert real_corpus_problems(corpus) == []


def test_no_code_path_outside_the_review_tool_writes_human_fields():
    """C7.1: only the review tool may write human verification fields."""
    offenders: list[str] = []
    pattern = (
        'review_status"\\] = "human_verified"',
        "reviewed_by\"\\] = ",
        "reviewed_at\"\\] = ",
    )
    import re

    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(PACKAGE).as_posix()
        if relative.startswith("tests/") or relative.endswith("review_tool.py"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for expression in pattern:
            if re.search(expression, text):
                offenders.append(f"{relative}: {expression}")

    assert offenders == []


def test_dropped_digit_is_rejected(tmp_path):
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    provision = {
        "provision_id": "P1",
        "page_start": 1,
        "page_end": 1,
        "original_text": "The fee is 5000 rupees for the complaint.",
    }

    result = verify_provision(
        provision,
        {},
        pdf,
        ocr_pages={1: "The fee is 500 rupees for the complaint."},
        stored_pages={1: "The fee is 5000 rupees for the complaint."},
        document={},
    )

    assert result["evidence"]["V2_number_inventory"] == "fail"
    assert "5000" in result["evidence"]["V2_detail"]["missing_from_ocr"]["digits"]


def test_missing_not_is_rejected(tmp_path):
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    provision = {
        "provision_id": "P2",
        "page_start": 1,
        "page_end": 1,
        "original_text": "A refund is not required after cancellation.",
    }

    result = verify_provision(
        provision,
        {},
        pdf,
        ocr_pages={1: "A refund is required after cancellation."},
        stored_pages={1: "A refund is not required after cancellation."},
        document={},
    )

    assert result["evidence"]["V1_independent_extraction"] == "fail"
    assert result["evidence"]["V5_boundary"] == "fail"


def test_trailing_proviso_is_rejected(tmp_path):
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    provision = {
        "provision_id": "P3",
        "page_start": 1,
        "page_end": 1,
        "original_text": "A seller must refund a cancelled order.",
    }

    result = verify_provision(
        provision,
        {},
        pdf,
        ocr_pages={
            1: "A seller must refund a cancelled order. Provided that the request "
            "was made within the stated period."
        },
        stored_pages={1: "A seller must refund a cancelled order."},
        document={},
    )

    assert result["evidence"]["V1_independent_extraction"] == "pass"
    assert result["evidence"]["V5_boundary"] == "fail"
    assert "V5_trailing_proviso" in result["flags"]


def _verify_clean_ocr(tmp_path, stored: str, ocr: str):
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    return verify_provision(
        {"provision_id": "P9", "page_start": 1, "page_end": 1, "original_text": stored},
        {},
        pdf,
        ocr_pages={1: ocr},
        stored_pages={1: ocr},
        document={},
    )


def test_signature_block_in_stored_text_is_rejected(tmp_path):
    text = (
        "The National Commission shall entertain complaints exceeding two crore rupees.\n"
        "ANUPAM MISHRA, Jt. Secy.\nSURENDER\nMAHADASAM"
    )
    result = _verify_clean_ocr(tmp_path, text, text)

    assert result["evidence"]["V1_independent_extraction"] == "pass"
    assert result["evidence"]["V5_boundary"] == "fail"
    assert "V5_non_law_text" in result["flags"]
    markers = result["evidence"]["V5_detail"]["non_law_markers"]
    assert {"signatory_designation", "signatory_name_line", "trailing_uppercase_name_line"} <= set(markers)


def test_file_number_and_gazette_footer_are_non_law():
    assert "file_number" in non_law_markers("violation of these rules.\n[ F. No. J-10/3/2018-CPU]")
    assert "gazette_footer" in non_law_markers(
        "rules.\nUploaded by Dte. of Printing at Government of India Press"
    )


def test_next_chapter_heading_is_non_law():
    text = "within the district.\nCHAPTER III\nCENTRAL CONSUMER PROTECTION AUTHORITY"
    assert non_law_markers(text) == ["trailing_next_heading"]


def test_clean_provision_has_no_non_law_markers(tmp_path):
    text = (
        "(2) They shall come into force on the date of their publication in the "
        "Official Gazette."
    )
    assert non_law_markers(text) == []
    assert _verify_clean_ocr(tmp_path, text, text)["evidence"]["V5_boundary"] == "pass"


# --- official Gazette copy -------------------------------------------------
def _pdf(tmp_path: Path, body: bytes = b"%PDF-1.4 gazette body") -> Path:
    path = tmp_path / "local.pdf"
    path.write_bytes(body)
    return path


def test_official_copy_byte_identical(tmp_path):
    local = _pdf(tmp_path)
    evidence = check_official_copy(
        local, GAZETTE_URL, fetch=lambda url: (url, 200, local.read_bytes())
    )

    assert evidence["result"] == "byte_identical"
    assert evidence["sha256"] == evidence["local_sha256"]
    assert official_copy_problems("S", evidence, evidence["local_sha256"]) == []


def test_official_copy_mismatch_is_a_problem(tmp_path):
    local = _pdf(tmp_path)
    evidence = check_official_copy(
        local, GAZETTE_URL, fetch=lambda url: (url, 200, b"%PDF-1.4 a different file")
    )

    assert evidence["result"] == "mismatch"
    assert official_copy_problems("S", evidence, evidence["local_sha256"])


def test_non_gazette_host_is_refused_before_any_request(tmp_path):
    calls: list[str] = []

    def fetch(url):
        calls.append(url)
        return url, 200, b"%PDF"

    for url in (
        "https://consumeraffairs.gov.in/public/upload/files/x.pdf",
        "https://egazette.gov.in.evil.example/x.pdf",
        "http://egazette.gov.in/WriteReadData/2020/220661.pdf",
    ):
        with pytest.raises(RefusedUrl):
            check_official_copy(_pdf(tmp_path), url, fetch=fetch)
    assert calls == []


def test_redirect_off_gazette_host_is_not_accepted(tmp_path):
    local = _pdf(tmp_path)
    evidence = check_official_copy(
        local,
        GAZETTE_URL,
        fetch=lambda url: ("https://mirror.example/x.pdf", 200, local.read_bytes()),
    )

    assert evidence["result"] == "redirected_off_official_host"
    assert official_copy_problems("S", evidence, evidence["local_sha256"])


def test_fetch_failure_and_html_page_are_not_accepted(tmp_path):
    local = _pdf(tmp_path)

    def boom(url):
        raise ConnectionError("down")

    assert check_official_copy(local, GAZETTE_URL, fetch=boom)["result"] == "fetch_failed"
    assert (
        check_official_copy(local, GAZETTE_URL, fetch=lambda u: (u, 404, b""))["result"]
        == "fetch_failed"
    )
    assert (
        check_official_copy(local, GAZETTE_URL, fetch=lambda u: (u, 200, b"<html>"))["result"]
        == "not_a_pdf"
    )


def test_official_copy_must_match_document_sha256():
    assert official_copy_problems("S", OFFICIAL_COPY, "b" * 64)
    assert official_copy_problems("S", {}, "a" * 64) == [
        "source S has no official Gazette copy check"
    ]


def test_machine_source_without_official_copy_is_rejected_by_gate(tmp_path):
    source = {**deepcopy(SOURCE), "official_copy": {}}
    _write(tmp_path, [source], [deepcopy(PROVISION)])

    with pytest.raises(Exception) as exc:
        load_corpus("real", corpus_dir=tmp_path)

    assert any("no official Gazette copy check" in e for e in exc.value.errors)


def test_machine_source_with_mismatched_official_copy_is_rejected_by_gate(tmp_path):
    copy = {**OFFICIAL_COPY, "sha256": "c" * 64, "result": "mismatch"}
    _write(tmp_path, [{**deepcopy(SOURCE), "official_copy": copy}], [deepcopy(PROVISION)])

    with pytest.raises(Exception) as exc:
        load_corpus("real", corpus_dir=tmp_path)

    assert any("not 'byte_identical'" in e for e in exc.value.errors)


def test_record_writes_evidence_to_staging_and_report(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "draft_sources.json").write_text(
        json.dumps([{"source_id": "S1"}]), encoding="utf-8"
    )
    local = _pdf(tmp_path)

    evidence = record(
        "S1",
        GAZETTE_URL,
        staging,
        fetch=lambda url: (url, 200, local.read_bytes()),
        local_pdf=local,
        out_dir=tmp_path / "verification",
    )

    stored = json.loads((staging / "draft_sources.json").read_text(encoding="utf-8"))
    assert stored[0]["official_copy"]["result"] == "byte_identical"
    assert evidence["result"] == "byte_identical"
    assert (tmp_path / "verification" / "S1" / "official_copy.json").exists()


def test_machine_verified_at_is_never_a_person(tmp_path):
    provision = {**deepcopy(PROVISION), "verified_by": "machine"}
    assert provision["reviewed_by"] is None
    assert provision["verified_by"] == "machine"
    assert datetime.fromisoformat(
        provision["verified_at"].replace("Z", "+00:00")
    ).tzinfo == timezone.utc
