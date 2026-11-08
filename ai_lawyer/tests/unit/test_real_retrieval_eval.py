from __future__ import annotations

from ai_lawyer.config.settings import get_settings
from ai_lawyer.evaluation import run_real_retrieval_eval as evaluation


class _Index:
    chunks = [
        {"chunk_id": "A::c0", "provision_id": "A"},
        {"chunk_id": "A::c1", "provision_id": "A"},
        {"chunk_id": "B::c0", "provision_id": "B"},
        {"chunk_id": "C::c0", "provision_id": "C"},
    ]

    def dense_search(self, query, top_k):
        return [("A::c0", 0.9), ("A::c1", 0.8), ("C::c0", 0.5)]

    def sparse_search(self, query, top_k):
        return [("B::c0", 3.0), ("A::c1", 2.0)]


def test_rankings_dedupe_to_provisions_and_fuse():
    ranked = evaluation.rankings(_Index(), "refund", rrf_k=60)

    assert ranked["E1_dense"] == ["A", "C"]
    assert ranked["E2_bm25"] == ["B", "A"]
    assert ranked["E3_hybrid_rrf"][0] == "A"  # in both lists
    assert set(ranked["E3_hybrid_rrf"]) == {"A", "B", "C"}


def test_summary_reports_splits_separately_with_row_counts():
    rows = [
        {"split": "development", "relevance_by_provision": {"A": 2}, "essential_provision_ids": ["A"],
         "rankings": {"E1_dense": ["A"], "E2_bm25": ["B", "A"], "E3_hybrid_rrf": ["A"]}},
        {"split": "test", "relevance_by_provision": {"B": 2}, "essential_provision_ids": ["B"],
         "rankings": {"E1_dense": ["A"], "E2_bm25": ["B"], "E3_hybrid_rrf": ["B", "A"]}},
    ]
    table = evaluation.summarise(rows, corpus_size=3)

    e1_dev = next(t for t in table if t["experiment"] == "E1_dense" and t["split"] == "development")
    e1_test = next(t for t in table if t["experiment"] == "E1_dense" and t["split"] == "test")
    assert e1_dev["rows"] == 1 and e1_dev["k"] == 3  # K clipped to corpus size
    assert e1_dev["recall@k"] == 1.0 and e1_test["recall@k"] == 0.0
    assert e1_dev["mrr@k"] == 1.0


def test_blocked_without_remote_embedder(monkeypatch, capsys):
    monkeypatch.setenv("EMBEDDING_BACKEND", "hash")
    get_settings.cache_clear()
    try:
        code = evaluation.main([])
    finally:
        get_settings.cache_clear()
    assert code == 2
    assert capsys.readouterr().out.startswith("BLOCKED:")
