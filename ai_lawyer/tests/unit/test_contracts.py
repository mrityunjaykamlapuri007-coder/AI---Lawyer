from __future__ import annotations

import numpy as np
import pytest

from ai_lawyer.contracts.errors import ModelOutputInvalid
from ai_lawyer.contracts.fakes import FakeLLM, HashEmbedder
from ai_lawyer.contracts.ids import make_provision_id
from ai_lawyer.contracts.models import (
    Fact,
    LegalDraft,
    Outcome,
    Provision,
    RelevanceGradeBatch,
    ScopeDecision,
)


def test_fact_round_trip_keeps_provenance():
    fact = Fact(
        case_id="case_1",
        fact_type="refund_status",
        raw_value="refund initiated",
        normalised_value="initiated",
        source_type="evidence",
        source_id="ev_1",
        evidence_id="ev_1",
        page_number=2,
        status="document_supported",
    )
    again = Fact.model_validate(fact.model_dump(mode="json"))
    assert again.fact_type == "refund_status"
    assert again.page_number == 2
    assert again.status == "document_supported"


def test_provision_rejects_empty_text():
    with pytest.raises(ValueError):
        Provision(
            provision_id="X",
            source_id="S",
            citation="X",
            hierarchy_type="section",
            original_text="   ",
        )


def test_outcome_values_are_the_contract():
    assert Outcome.no_legal_action_currently_required.value == "no_legal_action_currently_required"
    assert {o.value for o in Outcome} >= {
        "informal_resolution_recommended",
        "formal_grievance_recommended",
        "formal_legal_proceedings_may_be_justified",
        "needs_more_information",
        "out_of_scope",
    }


def test_fake_llm_scripted_invalid_and_default():
    llm = FakeLLM()
    scope = llm.generate_structured("x", ScopeDecision, {"task": "scope_classifier"})
    assert scope.in_scope is True
    assert scope.domain == "consumer_refund"

    bad = FakeLLM(scripts={"relevance_grader": ["__INVALID_JSON__"]})
    with pytest.raises(ModelOutputInvalid):
        bad.generate_structured("x", RelevanceGradeBatch, {"task": "relevance_grader"})


def test_fake_llm_scripts_and_default_relevance_grading():
    llm = FakeLLM()
    batch = llm.generate_structured(
        "x",
        RelevanceGradeBatch,
        {
            "task": "relevance_grader",
            "case_summary": "What is the definition of refund?",
            "candidates": [
                {
                    "provision_id": "A6",
                    "citation": "",
                    "original_text": "'refund' means the return of money paid for goods.",
                    "search_text": "",
                },
                {
                    "provision_id": "A2",
                    "citation": "",
                    "original_text": "This does not apply where the consumer has not returned the goods.",
                    "search_text": "",
                },
            ],
        },
    )
    grades = {item.provision_id: item.grade for item in batch.grades}

    assert grades["A6"] >= 2


def test_fake_llm_invented_provision_is_visible_to_guards():
    llm = FakeLLM(invented_provision_id="INVENTED_A99")
    draft = llm.generate_structured(
        "x",
        LegalDraft,
        {"task": "reasoning", "accepted_provision_ids": ["TEST_ACT_A1"]},
    )
    assert draft.relevant_provision_ids == ["INVENTED_A99"]
    assert draft.application_analysis[0].provision_id == "INVENTED_A99"


def test_hash_embedder_is_deterministic_and_normalised():
    embedder = HashEmbedder()
    first = embedder.embed(["refund not received", "grievance officer"])
    second = embedder.embed(["refund not received", "grievance officer"])
    assert first.shape == (2, 512)
    assert np.array_equal(first, second)
    assert np.allclose(np.linalg.norm(first, axis=1), 1.0)
    assert not np.array_equal(first[0], first[1])


def test_provision_ids_are_chunk_independent_and_stable():
    assert make_provision_id("CPA2019", 2) == "CPA2019_S2"
    assert make_provision_id("CPA2019", 2, 1) == "CPA2019_S2_1"
    assert make_provision_id("rules 2020", 3, "2", "a") == "RULES_2020_S3_2_A"
    assert make_provision_id("CPA2019", 2) == make_provision_id("CPA2019", "2")
