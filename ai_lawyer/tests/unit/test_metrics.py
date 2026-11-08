from __future__ import annotations

import math

import pytest

from ai_lawyer.evaluation.metrics import (
    applicability_scores,
    essential_context_completeness,
    mean,
    mrr_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def test_precision_uses_k_as_denominator():
    assert precision_at_k(["a", "b", "c"], {"a", "c"}, 4) == pytest.approx(0.5)
    assert precision_at_k([], {"a"}, 5) == 0.0
    assert precision_at_k(["a"], {"a"}, 0) is None


def test_recall_uses_essential_set_and_is_na_when_empty():
    assert recall_at_k(["a", "b"], {"a", "d", "e"}, 2) == pytest.approx(1 / 3)
    assert recall_at_k(["a"], set(), 5) is None


def test_mrr_counts_first_grade_at_least_two():
    grades = {"a": 1, "b": 3, "c": 2}
    assert mrr_at_k(["a", "b", "c"], grades, 3) == pytest.approx(0.5)
    assert mrr_at_k(["a", "b", "c"], grades, 1) == 0.0
    assert mrr_at_k(["c"], grades, 5) == 1.0


def test_ndcg_hand_computed_and_na_for_zero_ideal():
    grades = {"a": 3, "b": 1, "c": 2}
    assert ndcg_at_k(["a", "c", "b"], grades, 3) == pytest.approx(1.0)

    actual_dcg = 1 / math.log2(2) + 3 / math.log2(3) + 7 / math.log2(4)
    ideal_dcg = 7 / math.log2(2) + 3 / math.log2(3) + 1 / math.log2(4)
    assert ndcg_at_k(["b", "c", "a"], grades, 3) == pytest.approx(actual_dcg / ideal_dcg)
    assert ndcg_at_k(["x"], {}, 5) is None


def test_applicability_precision_recall_and_false_acceptance():
    scores = applicability_scores(
        {"a": "applicable", "b": "not_applicable", "c": "applicable", "d": "not_applicable"},
        {"a": "applicable", "b": "applicable", "c": "not_applicable", "d": "not_applicable"},
    )
    assert scores["tp"] == 1 and scores["fp"] == 1 and scores["fn"] == 1 and scores["tn"] == 1
    assert scores["precision"] == pytest.approx(0.5)
    assert scores["recall"] == pytest.approx(0.5)
    assert scores["false_acceptance_rate"] == pytest.approx(0.5)


def test_essential_context_completeness_and_critical_omission():
    result = essential_context_completeness(["a", "b"], ["a", "c"])
    assert result["completeness"] == pytest.approx(0.5)
    assert result["critical_omission"] is True
    assert result["missing"] == ["c"]
    assert essential_context_completeness([], [])["completeness"] is None


def test_mean_ignores_na():
    assert mean([1.0, None, 0.0]) == pytest.approx(0.5)
    assert mean([None]) is None
