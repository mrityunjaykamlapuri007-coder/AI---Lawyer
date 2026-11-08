from __future__ import annotations

import json
from copy import deepcopy

import pytest

from ai_lawyer.config.settings import get_settings
from ai_lawyer.contracts.models import Condition, Fact, Provision
from ai_lawyer.legal_engine.applicability import evaluate_condition, evaluate_provision
from ai_lawyer.legal_rag.corpus_loader import load_corpus
from ai_lawyer.legal_rag.machine_conditions import run, condition_test_table, validate
from ai_lawyer.tests.unit.test_machine_verification import PROVISION, SOURCE, _write

TEXT = "No seller shall refuse to refund consideration, if paid, if such goods are defective."
STAGED = {"provision_id": "T_P1", "review_status": "machine_verified", "original_text": TEXT}


def _cond(**overrides) -> Condition:
    base = {
        "condition_id": "C1",
        "description": "refund refused",
        "fact_type": "refund_status",
        "operator": "in",
        "expected_value": ["denied", "partial"],
        "source_quote": "refuse to refund consideration",
        "drafted_by": "agent",
    }
    return Condition.model_validate({**base, **overrides})


def _fact(fact_type, value) -> Fact:
    return Fact(case_id="c", fact_type=fact_type, raw_value=str(value), normalised_value=value,
                source_type="user_message", source_id="m", status="user_reported")


@pytest.fixture
def trust(monkeypatch):
    def set_level(level: str):
        monkeypatch.setenv("CORPUS_TRUST_LEVEL", level)
        get_settings.cache_clear()
    yield set_level
    get_settings.cache_clear()


def test_valid_condition_passes_validation_and_table():
    condition = _cond()
    assert validate(condition, STAGED) == []
    ok, rows = condition_test_table(condition)
    assert ok
    assert [r["got"] for r in rows] == [True, False, None]


def test_quote_not_in_provision_is_rejected():
    assert "source quote is not in the provision text" in validate(
        _cond(source_quote="refund within seven days"), STAGED
    )


def test_value_outside_extractor_vocabulary_is_rejected():
    problems = validate(_cond(expected_value=["refused_by_bank"]), STAGED)
    assert any("not in the refund_status vocabulary" in p for p in problems)


def test_condition_on_unverified_provision_is_rejected():
    assert "provision is not verified" in validate(_cond(), {**STAGED, "review_status": "unverified"})


def test_manual_condition_table_is_always_unknown():
    ok, rows = condition_test_table(_cond(operator="manual", expected_value=None))
    assert ok and all(r["got"] is None for r in rows)


def test_run_writes_machine_status_and_rejects_bad_quote(tmp_path):
    (tmp_path / "draft_provisions.json").write_text(json.dumps([STAGED]), encoding="utf-8")
    conditions = tmp_path / "conditions.json"
    good = _cond().model_dump(mode="json")
    bad = _cond(condition_id="C2", source_quote="not in the text").model_dump(mode="json")
    conditions.write_text(json.dumps({"conditions": {"T_P1": [good, bad]}}), encoding="utf-8")

    report = run(tmp_path, apply=False, conditions_file=conditions)

    accepted = {e["condition_id"]: e["accepted"] for e in report["provisions"]["T_P1"]}
    assert accepted == {"C1": True, "C2": False}


def test_machine_condition_counts_only_at_trust_level_machine(trust):
    condition = _cond(machine_review_status="machine_verified")
    denied = [_fact("refund_status", "denied")]

    trust("machine")
    assert evaluate_condition(condition, denied).value is True
    trust("human")
    assert evaluate_condition(condition, denied).value is None


def test_unverified_agent_condition_is_unknown(trust):
    trust("machine")
    condition = _cond(machine_review_status="unreviewed")
    assert evaluate_condition(condition, [_fact("refund_status", "denied")]).value is None


def test_trust_level_human_makes_machine_rows_uncitable(tmp_path, trust):
    _write(tmp_path, [deepcopy(SOURCE)], [deepcopy(PROVISION)])

    trust("machine")
    assert load_corpus("real", corpus_dir=tmp_path).usable_count == 1
    trust("human")
    with pytest.raises(Exception):
        load_corpus("real", corpus_dir=tmp_path)  # zero citable rows: gate refuses


def test_gate_rejects_machine_condition_whose_quote_is_not_in_text(tmp_path):
    provision = deepcopy(PROVISION)
    provision["conditions"] = [
        _cond(machine_review_status="machine_verified", source_quote="words not present")
        .model_dump(mode="json")
    ]
    _write(tmp_path, [deepcopy(SOURCE)], [provision])

    with pytest.raises(Exception) as exc:
        load_corpus("real", corpus_dir=tmp_path)
    assert any("quote is not in the provision text" in e for e in exc.value.errors)


def test_provision_applicability_with_manual_condition_is_never_true(trust):
    trust("machine")
    provision = Provision.model_validate(
        {**deepcopy(PROVISION), "conditions": [
            _cond(machine_review_status="machine_verified").model_dump(mode="json"),
            _cond(condition_id="C3", operator="manual", expected_value=None,
                  machine_review_status="machine_verified").model_dump(mode="json"),
        ]}
    )
    assert evaluate_provision(provision, [_fact("refund_status", "denied")]).value is None
    assert evaluate_provision(provision, [_fact("refund_status", "processed")]).value is False
