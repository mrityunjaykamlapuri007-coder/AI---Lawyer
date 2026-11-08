from __future__ import annotations

import math

from ai_lawyer.legal_rag.rrf import fuse


def test_rrf_sums_reciprocal_ranks_and_breaks_ties_by_id():
    fused = fuse({"dense": ["x", "y"], "sparse": ["y", "x"]}, k=60)
    assert [f.chunk_id for f in fused] == ["x", "y"]
    expected = 1 / 61 + 1 / 62
    assert math.isclose(fused[0].score, expected)
    assert fused[0].ranks == {"dense": 1, "sparse": 2}
    assert fused[1].ranks == {"dense": 2, "sparse": 1}


def test_duplicate_within_one_list_is_counted_once():
    fused = fuse([["a", "a", "b"]], k=60)
    by_id = {f.chunk_id: f for f in fused}
    assert math.isclose(by_id["a"].score, 1 / 61)
    assert math.isclose(by_id["b"].score, 1 / 62)
    assert by_id["a"].ranks == {"list_0": 1}


def test_absent_chunk_contributes_zero_from_other_lists():
    fused = fuse([["a"], ["b"]], k=60)
    by_id = {f.chunk_id: f for f in fused}
    assert by_id["a"].score == 1 / 61
    assert "list_1" not in by_id["a"].ranks
    assert [f.chunk_id for f in fused] == ["a", "b"]


def test_output_is_deterministic_across_runs():
    lists = {"a": ["m", "n", "o"], "b": ["o", "m", "p"]}
    first = [(f.chunk_id, f.score) for f in fuse(lists)]
    second = [(f.chunk_id, f.score) for f in fuse(lists)]
    assert first == second


def test_empty_input_returns_empty():
    assert fuse({}) == []
    assert fuse([]) == []
