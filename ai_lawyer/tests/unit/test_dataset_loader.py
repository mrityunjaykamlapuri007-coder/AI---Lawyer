from __future__ import annotations

from ai_lawyer.config.settings import PROJECT_ROOT
from ai_lawyer.evaluation.dataset_loader import load_dataset, validate_rows

DATASET_DIR = PROJECT_ROOT / "ai_lawyer" / "evaluation" / "dataset"


def _row(test_id="R1", scenario="S1", split="development", pid="TEST_ACT_A1"):
    return {
        "test_id": test_id,
        "split": split,
        "scenario_id": scenario,
        "user_query": "refund pending",
        "expected_provision_ids": [pid],
        "essential_provision_ids": [pid],
        "relevance_by_provision": {pid: 3},
        "applicability_by_provision": {pid: "applicable"},
        "required_context_ids": [],
        "labeling_status": "FIXTURE",
    }


def test_fixture_dataset_loads_and_is_labelled(corpus):
    dataset = load_dataset(DATASET_DIR, corpus)
    assert len(dataset.rows) == 16
    assert len(dataset.split("development")) == 8
    assert len(dataset.split("test")) == 8
    assert dataset.fixture is True


def test_dangling_provision_id_is_rejected(corpus):
    errors = validate_rows([_row(pid="MISSING_A1")], corpus)
    assert any("not in the corpus" in error for error in errors)


def test_scenario_in_both_splits_is_rejected(corpus):
    rows = [_row("R1", "S1", "development"), _row("R2", "S1", "test")]
    errors = validate_rows(rows, corpus)
    assert any("appears in both" in error for error in errors)


def test_invalid_grade_and_label_are_rejected(corpus):
    row = _row()
    row["relevance_by_provision"] = {"TEST_ACT_A1": 9}
    row["applicability_by_provision"] = {"TEST_ACT_A1": "maybe"}
    errors = validate_rows([row], corpus)
    assert any("not 0-3" in error for error in errors)
    assert any("invalid applicability" in error for error in errors)
