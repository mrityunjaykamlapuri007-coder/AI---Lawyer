from __future__ import annotations

import json
import shutil
from pathlib import Path

from ai_lawyer.legal_rag import build_runtime_corpus as builder
from ai_lawyer.legal_rag.corpus_loader import load_corpus
from ai_lawyer.legal_rag.review_tool import main as review_main

STAGING = (
    Path(__file__).resolve().parents[2]
    / "legal_corpus"
    / "official"
    / "draft_curated"
)


def _copy_staging(tmp_path: Path) -> Path:
    destination = tmp_path / "staging"
    shutil.copytree(STAGING, destination)
    return destination


def _ecr_ids(staging: Path, count: int) -> list[str]:
    rows = json.loads((staging / "draft_provisions.json").read_text(encoding="utf-8"))
    return [row["provision_id"] for row in rows if row["source_id"] == "ECR_2020"][:count]


def _approve_source(staging: Path, source_id: str = "ECR_2020") -> None:
    code = review_main(
        [
            "--staging-dir",
            str(staging),
            "source-approve",
            source_id,
            "--reviewer",
            "Test Reviewer",
            "--publisher",
            "Test Publisher",
            "--official-url",
            "https://example.invalid/document.pdf",
            "--published-date",
            "2020-07-23",
            "--version-status",
            "current",
        ]
    )
    assert code == 0


def _approve(
    staging: Path, provision_ids: list[str], *, approve_source: bool = True
) -> None:
    if approve_source:
        _approve_source(staging, "ECR_2020")
    for provision_id in provision_ids:
        code = review_main(
            [
                "--staging-dir",
                str(staging),
                "approve",
                provision_id,
                "--reviewer",
                "Test Reviewer",
                "--confirm",
                provision_id,
            ]
        )
        assert code == 0


def test_zero_approved_provisions_refuses_and_writes_nothing(tmp_path):
    staging = _copy_staging(tmp_path)
    out = tmp_path / "out"

    code = builder.main(["--staging-dir", str(staging), "--out-dir", str(out)])

    assert code == 2
    assert not (out / "sources.json").exists()
    assert not (out / "provisions.json").exists()


def test_two_approved_rows_build_a_real_corpus_that_loads(tmp_path):
    staging = _copy_staging(tmp_path)
    ids = _ecr_ids(staging, 2)
    _approve(staging, ids)
    out = tmp_path / "out"

    code = builder.main(["--staging-dir", str(staging), "--out-dir", str(out)])

    assert code == 0
    sources = json.loads((out / "sources.json").read_text(encoding="utf-8"))
    provisions = json.loads((out / "provisions.json").read_text(encoding="utf-8"))
    assert [s["source_id"] for s in sources] == ["ECR_2020"]
    assert {p["provision_id"] for p in provisions} == set(ids)
    assert all(p["review_status"] == "human_verified" for p in provisions)

    corpus = load_corpus("real", corpus_dir=out)
    assert corpus.usable_count == 2
    assert corpus.unusable_count == 0


def test_approved_provision_without_source_approval_is_excluded(tmp_path):
    staging = _copy_staging(tmp_path)
    rows = json.loads((staging / "draft_provisions.json").read_text(encoding="utf-8"))
    ecr = [r["provision_id"] for r in rows if r["source_id"] == "ECR_2020"][0]
    amendment = [
        r["provision_id"] for r in rows if r["source_id"] == "ECR_2021_AMENDMENT"
    ][0]

    _approve_source(staging, "ECR_2020")
    for provision_id in (ecr, amendment):
        assert (
            review_main(
                [
                    "--staging-dir",
                    str(staging),
                    "approve",
                    provision_id,
                    "--reviewer",
                    "Test Reviewer",
                    "--confirm",
                    provision_id,
                ]
            )
            == 0
        )
    out = tmp_path / "out"

    code = builder.main(["--staging-dir", str(staging), "--out-dir", str(out)])

    assert code == 0
    provisions = json.loads((out / "provisions.json").read_text(encoding="utf-8"))
    assert [p["provision_id"] for p in provisions] == [ecr]


def test_unreviewed_condition_blocks_the_build(tmp_path, capsys):
    staging = _copy_staging(tmp_path)
    ids = _ecr_ids(staging, 2)
    _approve(staging, ids)
    code = review_main(
        [
            "--staging-dir",
            str(staging),
            "condition-add",
            ids[0],
            "--condition-id",
            "TEST_C1",
            "--description",
            "test condition",
            "--fact-type",
            "refund_status",
            "--operator",
            "in",
            "--value",
            "pending,not_received",
        ]
    )
    assert code == 0
    out = tmp_path / "out"

    code = builder.main(["--staging-dir", str(staging), "--out-dir", str(out)])

    output = capsys.readouterr().out
    assert code == 2
    assert "not human-reviewed" in output
    assert not (out / "provisions.json").exists()


def test_reviewed_condition_allows_the_build(tmp_path):
    staging = _copy_staging(tmp_path)
    ids = _ecr_ids(staging, 2)
    _approve(staging, ids)
    for args in (
        [
            "condition-add",
            ids[0],
            "--condition-id",
            "TEST_C1",
            "--description",
            "test condition",
            "--fact-type",
            "refund_status",
            "--operator",
            "in",
            "--value",
            "pending,not_received",
        ],
        ["condition-review", ids[0], "TEST_C1"],
    ):
        assert review_main(["--staging-dir", str(staging), *args]) == 0
    out = tmp_path / "out"

    code = builder.main(["--staging-dir", str(staging), "--out-dir", str(out)])

    assert code == 0
    provisions = json.loads((out / "provisions.json").read_text(encoding="utf-8"))
    condition = next(
        p for p in provisions if p["provision_id"] == ids[0]
    )["conditions"][0]
    assert condition["human_review_status"] == "reviewed"
    assert condition["expected_value"] == ["pending", "not_received"]
