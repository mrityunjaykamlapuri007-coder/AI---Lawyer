from __future__ import annotations

import json

from ai_lawyer.legal_rag.boundary_fix import apply_to_staging, propose_trim
from ai_lawyer.legal_rag.machine_verify import non_law_markers

LAW = "The National Commission shall entertain complaints exceeding two crore rupees."


def test_signature_block_is_trimmed_to_an_exact_prefix():
    text = LAW + "\nANUPAM MISHRA, Jt. Secy.\nSURENDER\nMAHADASAM\n22:00:30 +05'30'"
    trim = propose_trim(text)

    assert trim is not None
    assert trim["kept"] == LAW
    assert text.startswith(trim["kept"])
    assert "MAHADASAM" in trim["removed"]
    assert non_law_markers(trim["kept"]) == []


def test_file_number_line_starts_the_cut():
    text = LAW + "\n[ F. No. J-10/3/2018-CPU]\nAMIT MEHTA, Jt. Secy."
    assert propose_trim(text)["kept"] == LAW


def test_next_chapter_heading_is_trimmed():
    text = LAW + "\nCHAPTER III\nCENTRAL CONSUMER PROTECTION AUTHORITY"
    assert propose_trim(text)["kept"] == LAW


def test_no_trim_when_removed_block_holds_other_text():
    text = (
        LAW
        + "\nANUPAM MISHRA, Jt. Secy.\nSub-section (i) vide number G.S.R. 448(E), dated the 15th July, 2020."
    )
    assert propose_trim(text) is None


def test_schedule_is_kept_and_only_the_signature_removed():
    text = LAW + "\nSCHEDULE-I\n[Rule 18]\nName of State:\nAMIT MEHTA, Jt. Secy"
    trim = propose_trim(text)

    assert "SCHEDULE-I" in trim["kept"]
    assert trim["removed"].strip() == "AMIT MEHTA, Jt. Secy"


def test_no_trim_when_kept_text_does_not_end_a_sentence():
    text = "The Commission shall entertain complaints where\nANUPAM MISHRA, Jt. Secy."
    assert propose_trim(text) is None


def test_clean_text_is_untouched():
    assert propose_trim(LAW) is None


def test_apply_records_removed_text_and_resets_verification(tmp_path):
    original = LAW + "\nANUPAM MISHRA, Jt. Secy.\nMAHADASAM"
    rows = [
        {
            "provision_id": "P1",
            "original_text": original,
            "review_status": "machine_verified",
            "verified_by": "machine",
            "verification_evidence": {"V1_independent_extraction": "pass"},
            "verification_method_count": 2,
        }
    ]
    (tmp_path / "draft_provisions.json").write_text(json.dumps(rows), encoding="utf-8")

    changes = apply_to_staging(tmp_path, apply=True)

    row = json.loads((tmp_path / "draft_provisions.json").read_text(encoding="utf-8"))[0]
    assert changes[0]["action"] == "trim"
    assert row["original_text"] == LAW
    assert row["boundary_adjustment"]["removed_text"].startswith("ANUPAM MISHRA")
    assert row["review_status"] == "unverified"
    assert row["verified_by"] is None
    assert row["verification_evidence"] == {}
    assert "reviewed_by" not in row


def test_dry_run_writes_nothing(tmp_path):
    rows = [{"provision_id": "P1", "original_text": LAW + "\nANUPAM MISHRA, Jt. Secy."}]
    path = tmp_path / "draft_provisions.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    apply_to_staging(tmp_path, apply=False)

    assert path.read_text(encoding="utf-8") == before
