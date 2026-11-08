from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from ai_lawyer.legal_rag.review_tool import main

SOURCE = {
    "source_id": "SRC_A",
    "title": "Fixture source A",
    "source_type": "act",
    "publisher": "Department of Consumer Affairs",
    "official_url": "https://example.gov.in/a.pdf",
    "published_date": "2020-07-20",
    "retrieved_at": "2026-11-08",
    "document_sha256": "a" * 64,
    "review_status": "unverified",
    "version_label": "fixture",
    "effective_from": "2020-07-20",
    "effective_to": None,
    "version_status": "current",
    "reviewed_by": None,
    "reviewed_at": None,
    "notes": "",
}

INCOMPLETE_SOURCE = {
    "source_id": "SRC_B",
    "title": "Fixture source B",
    "source_type": "regulation",
    "publisher": "",
    "official_url": "",
    "published_date": None,
    "retrieved_at": "2026-11-08",
    "document_sha256": "b" * 64,
    "review_status": "unverified",
    "version_label": "fixture",
    "effective_from": None,
    "effective_to": None,
    "version_status": "uncertain",
    "reviewed_by": None,
    "reviewed_at": None,
    "notes": "",
}

PROVISION = {
    "provision_id": "SRC_A_P1",
    "source_id": "SRC_A",
    "citation": "Fixture provision 1",
    "hierarchy_type": "section",
    "parent_provision_id": None,
    "original_text": "Verbatim fixture text one.",
    "search_text": "fixture",
    "provisos": [],
    "exceptions": [],
    "definitions_used": [],
    "cross_references": [],
    "mandatory_context": [],
    "conditions": [],
    "page_start": 1,
    "page_end": 1,
    "review_status": "unverified",
    "reviewed_by": None,
    "reviewed_at": None,
    "review_note": None,
}


def _staging(tmp_path: Path) -> Path:
    sources = [deepcopy(SOURCE), deepcopy(INCOMPLETE_SOURCE)]
    provisions = [
        deepcopy(PROVISION),
        {**deepcopy(PROVISION), "provision_id": "SRC_A_P2", "citation": "Fixture provision 2"},
        {
            **deepcopy(PROVISION),
            "provision_id": "SRC_B_P1",
            "source_id": "SRC_B",
            "citation": "Fixture provision B1",
        },
    ]
    (tmp_path / "draft_sources.json").write_text(
        json.dumps(sources, indent=2), encoding="utf-8"
    )
    (tmp_path / "draft_provisions.json").write_text(
        json.dumps(provisions, indent=2), encoding="utf-8"
    )
    return tmp_path


def _rows(tmp_path: Path) -> dict[str, dict]:
    data = json.loads((tmp_path / "draft_provisions.json").read_text(encoding="utf-8"))
    return {row["provision_id"]: row for row in data}


def _sources(tmp_path: Path) -> dict[str, dict]:
    data = json.loads((tmp_path / "draft_sources.json").read_text(encoding="utf-8"))
    return {row["source_id"]: row for row in data}


def test_approve_requires_the_exact_provision_id(tmp_path):
    staging = _staging(tmp_path)

    code = main(
        [
            "--staging-dir",
            str(staging),
            "approve",
            "SRC_A_P1",
            "--reviewer",
            "Mri",
            "--confirm",
            "SRC_A_P2",
        ]
    )

    assert code == 2
    assert _rows(tmp_path)["SRC_A_P1"]["review_status"] == "unverified"


def test_approve_without_confirmation_refuses_in_non_interactive_use(tmp_path):
    staging = _staging(tmp_path)

    code = main(
        [
            "--staging-dir",
            str(staging),
            "approve",
            "SRC_A_P1",
            "--reviewer",
            "Mri",
        ]
    )

    assert code == 2
    assert _rows(tmp_path)["SRC_A_P1"]["review_status"] == "unverified"


def test_approve_updates_exactly_one_row_and_stamps_the_reviewer(tmp_path):
    staging = _staging(tmp_path)

    code = main(
        [
            "--staging-dir",
            str(staging),
            "approve",
            "SRC_A_P1",
            "--reviewer",
            "Mri",
            "--confirm",
            "SRC_A_P1",
        ]
    )

    rows = _rows(tmp_path)
    assert code == 0
    assert rows["SRC_A_P1"]["review_status"] == "human_verified"
    assert rows["SRC_A_P1"]["reviewed_by"] == "Mri"
    assert rows["SRC_A_P1"]["reviewed_at"]
    assert rows["SRC_A_P2"]["review_status"] == "unverified"
    assert rows["SRC_A_P2"]["reviewed_by"] is None


def test_approve_without_reviewer_refuses(tmp_path):
    staging = _staging(tmp_path)

    with pytest.raises(SystemExit):
        main(
            [
                "--staging-dir",
                str(staging),
                "approve",
                "SRC_A_P1",
                "--confirm",
                "SRC_A_P1",
            ]
        )
    assert _rows(tmp_path)["SRC_A_P1"]["review_status"] == "unverified"


def test_batch_approval_is_not_possible(tmp_path):
    staging = _staging(tmp_path)

    with pytest.raises(SystemExit):
        main(
            [
                "--staging-dir",
                str(staging),
                "approve",
                "SRC_A_P1",
                "SRC_A_P2",
                "--reviewer",
                "Mri",
                "--confirm",
                "SRC_A_P1",
            ]
        )

    assert all(row["review_status"] == "unverified" for row in _rows(tmp_path).values())


def test_reject_records_the_note_and_keeps_the_row_unusable(tmp_path):
    staging = _staging(tmp_path)

    code = main(
        [
            "--staging-dir",
            str(staging),
            "reject",
            "SRC_A_P1",
            "--note",
            "text differs from the PDF",
        ]
    )

    row = _rows(tmp_path)["SRC_A_P1"]
    assert code == 0
    assert row["review_status"] == "rejected"
    assert "text differs" in row["review_note"]


def test_source_approve_reports_every_missing_field(tmp_path, capsys):
    staging = _staging(tmp_path)

    code = main(
        [
            "--staging-dir",
            str(staging),
            "source-approve",
            "SRC_B",
            "--reviewer",
            "Mri",
        ]
    )

    output = capsys.readouterr().out
    assert code == 2
    assert "publisher" in output
    assert "official_url" in output
    assert "published_date" in output
    assert "version_status" in output
    assert _sources(tmp_path)["SRC_B"]["review_status"] == "unverified"


def test_source_approve_succeeds_only_when_all_fields_are_supplied(tmp_path):
    staging = _staging(tmp_path)

    code = main(
        [
            "--staging-dir",
            str(staging),
            "source-approve",
            "SRC_B",
            "--reviewer",
            "Mri",
            "--publisher",
            "Department of Consumer Affairs",
            "--official-url",
            "https://example.gov.in/b.pdf",
            "--published-date",
            "2021-05-17",
            "--version-status",
            "current",
        ]
    )

    source = _sources(tmp_path)["SRC_B"]
    assert code == 0
    assert source["review_status"] == "human_verified"
    assert source["reviewed_by"] == "Mri"
    assert source["version_status"] == "current"


def test_show_prints_verbatim_text_hash_and_review_state(tmp_path, capsys):
    staging = _staging(tmp_path)

    code = main(["--staging-dir", str(staging), "show", "SRC_A_P1"])

    output = capsys.readouterr().out
    assert code == 0
    assert "Verbatim fixture text one." in output
    assert "a" * 64 in output
    assert "status=unverified" in output


def test_list_filters_by_source_and_status(tmp_path, capsys):
    staging = _staging(tmp_path)
    main(
        [
            "--staging-dir",
            str(staging),
            "approve",
            "SRC_A_P1",
            "--reviewer",
            "Mri",
            "--confirm",
            "SRC_A_P1",
        ]
    )
    capsys.readouterr()

    code = main(
        ["--staging-dir", str(staging), "list", "--source", "SRC_A", "--status", "human_verified"]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "SRC_A_P1" in output
    assert "SRC_A_P2" not in output


def test_worksheets_are_refreshed_after_approval(tmp_path):
    staging = _staging(tmp_path)
    (staging / "provisions_review.csv").write_text(
        "provision_id,source_id,citation,hierarchy_type,page_start,page_end,"
        "char_count,text_preview,decision,reviewer,reviewed_at,notes\n"
        "SRC_A_P1,SRC_A,Fixture provision 1,section,1,1,26,text,,,,\n",
        encoding="utf-8",
    )

    main(
        [
            "--staging-dir",
            str(staging),
            "approve",
            "SRC_A_P1",
            "--reviewer",
            "Mri",
            "--confirm",
            "SRC_A_P1",
        ]
    )

    csv_text = (staging / "provisions_review.csv").read_text(encoding="utf-8")
    assert "human_verified" in csv_text
    assert "Mri" in csv_text
