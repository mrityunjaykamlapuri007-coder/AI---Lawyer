"""Real-story dataset (public consumer-commission order reports) and label derivation."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from ai_lawyer.config.settings import get_settings
from ai_lawyer.evaluation.derive_labels import derive
from ai_lawyer.legal_rag.corpus_loader import load_corpus
from ai_lawyer.tests.unit.test_machine_verification import PROVISION, SOURCE, _write

DATASET = Path(__file__).resolve().parents[2] / "evaluation" / "dataset"
STORIES = [
    json.loads(line)
    for line in (DATASET / "real_stories.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]
SOURCES = json.loads((DATASET / "real_stories_sources.json").read_text(encoding="utf-8"))["stories"]


def test_every_story_is_tagged_real_anonymised_and_sourced():
    assert len(STORIES) == 17
    for row in STORIES:
        assert row["data_origin"] == "public_commission_order"
        assert row["anonymised"] is True
        assert row["retrieved_at"]
        primary = SOURCES[row["test_id"]][0]
        assert primary["url"].startswith("https://")
        assert len(primary["sha256"]) == 64
        assert primary["passage_used"]


def test_splits_are_fixed_and_disjoint():
    dev = {r["test_id"] for r in STORIES if r["split"] == "development"}
    test = {r["test_id"] for r in STORIES if r["split"] == "test"}
    assert (len(dev), len(test)) == (7, 10)
    assert not dev & test
    urls = [SOURCES[r["test_id"]][0]["url"] for r in STORIES]
    assert len(urls) == len(set(urls))  # one story per reported case


def test_expected_outcomes_use_known_values():
    allowed = {
        "formal_grievance_recommended",
        "needs_more_information",
        "informal_resolution_recommended",
        "no_legal_action_currently_required",
        "formal_legal_proceedings_may_be_justified",
        "out_of_scope",
        "undetermined",
    }
    for row in STORIES:
        assert row["expected"]["outcome"] in allowed
        assert row["expected"]["rationale"]


@pytest.fixture
def machine_trust(monkeypatch):
    monkeypatch.setenv("CORPUS_TRUST_LEVEL", "machine")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _corpus(tmp_path, conditions):
    provision = deepcopy(PROVISION)
    provision["conditions"] = conditions
    provision["original_text"] = "Every e-commerce entity shall appoint a grievance officer."
    _write(tmp_path, [deepcopy(SOURCE)], [provision])
    return load_corpus("real", corpus_dir=tmp_path)


def _condition(operator="exists", **extra):
    return {
        "condition_id": "C1", "description": "platform named", "fact_type": "platform_name",
        "operator": operator, "expected_value": None, "source_quote": "Every e-commerce entity",
        "drafted_by": "agent", "machine_review_status": "machine_verified", **extra,
    }


def _story(case_facts):
    return {"test_id": "X", "data_origin": "public_commission_order", "split": "test",
            "turns": [{"message": "story"}], "case_facts": case_facts, "now": "2026-11-08"}


def test_label_is_derived_only_when_all_conditions_are_true(tmp_path, machine_trust):
    corpus = _corpus(tmp_path, [_condition()])

    labelled = derive(_story({"platform_name": "Amazon"}), corpus)
    unlabelled = derive(_story({}), corpus)

    assert labelled["expected_provision_ids"] == ["MACHINE_ACT_S1"]
    assert labelled["labeling_status"] == "machine_derived"
    assert unlabelled["expected_provision_ids"] == []
    assert unlabelled["labeling_status"] == "excluded_not_derivable"


def test_manual_condition_is_never_gold_relevant(tmp_path, machine_trust):
    corpus = _corpus(tmp_path, [_condition(), _condition(operator="manual", condition_id="C2")])

    assert derive(_story({"platform_name": "Amazon"}), corpus)["expected_provision_ids"] == []
