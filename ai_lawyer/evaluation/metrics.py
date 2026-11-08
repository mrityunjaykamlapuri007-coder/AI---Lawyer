"""Retrieval and verification metrics.

Definitions follow the implementation plan:
- precision@K uses K as the denominator, even when fewer items were returned;
- recall@K uses the essential set and is N/A when that set is empty;
- MRR@K counts the first item with relevance grade >= 2;
- nDCG@K uses gain 2**grade - 1 and discount log2(rank + 1); N/A when ideal
  DCG is zero;
- applicability reports precision/recall for the positive label and a false
  acceptance rate over everything expected to be not applicable;
- essential-context completeness reports a critical-omission flag.
"""
from __future__ import annotations

import math
from typing import Iterable, Mapping, Sequence


def precision_at_k(retrieved: Sequence[str], relevant: Iterable[str], k: int) -> float | None:
    if k <= 0:
        return None
    relevant_set = set(relevant)
    hits = sum(1 for item in list(retrieved)[:k] if item in relevant_set)
    return hits / k


def recall_at_k(retrieved: Sequence[str], essential: Iterable[str], k: int) -> float | None:
    essential_set = set(essential)
    if not essential_set:
        return None
    hits = sum(1 for item in list(retrieved)[:k] if item in essential_set)
    return hits / len(essential_set)


def mrr_at_k(retrieved: Sequence[str], grades: Mapping[str, int], k: int, threshold: int = 2) -> float | None:
    for rank, item in enumerate(list(retrieved)[:k], start=1):
        if grades.get(item, 0) >= threshold:
            return 1.0 / rank
    return 0.0


def dcg(grades: Sequence[int]) -> float:
    return sum(
        (2 ** grade - 1) / math.log2(rank + 1)
        for rank, grade in enumerate(grades, start=1)
    )


def ndcg_at_k(retrieved: Sequence[str], grades: Mapping[str, int], k: int) -> float | None:
    actual = [grades.get(item, 0) for item in list(retrieved)[:k]]
    ideal_grades = sorted((g for g in grades.values() if g > 0), reverse=True)[:k]
    ideal = dcg(ideal_grades)
    if ideal <= 0:
        return None
    return dcg(actual) / ideal


def applicability_scores(
    predicted: Mapping[str, str],
    expected: Mapping[str, str],
    positive: str = "applicable",
) -> dict[str, float | int | None]:
    tp = sum(1 for pid, label in expected.items() if label == positive and predicted.get(pid) == positive)
    fp = sum(1 for pid, label in expected.items() if label != positive and predicted.get(pid) == positive)
    fn = sum(1 for pid, label in expected.items() if label == positive and predicted.get(pid) != positive)
    tn = sum(1 for pid, label in expected.items() if label != positive and predicted.get(pid) != positive)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    false_acceptance_rate = fp / (fp + tn) if fp + tn else None
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "false_acceptance_rate": false_acceptance_rate,
    }


def essential_context_completeness(
    retrieved: Sequence[str], required: Iterable[str]
) -> dict[str, float | bool | None]:
    required_set = set(required)
    if not required_set:
        return {"completeness": None, "critical_omission": False, "missing": []}
    present = required_set & set(retrieved)
    missing = sorted(required_set - set(retrieved))
    return {
        "completeness": len(present) / len(required_set),
        "critical_omission": bool(missing),
        "missing": missing,
    }


def mean(values: Iterable[float | int | None]) -> float | None:
    items = [float(v) for v in values if v is not None]
    if not items:
        return None
    return sum(items) / len(items)
