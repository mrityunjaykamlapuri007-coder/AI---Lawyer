from __future__ import annotations

from dataclasses import replace

import pytest

from ai_lawyer.contracts.errors import IndexStale
from ai_lawyer.tests.fakes import HashEmbedder
from ai_lawyer.legal_rag.index_manager import bm25_tokens, load_index


def test_bm25_tokeniser_keeps_identifiers():
    assert bm25_tokens("Section 5") == ["section", "5"]
    assert bm25_tokens("Order FM-1001") == ["order", "fm-1001"]


def test_build_writes_a_verified_manifest(index_bundle, corpus, settings):
    assert index_bundle.manifest["corpus_version"] == corpus.corpus_version
    assert index_bundle.manifest["corpus_mode"] == "fixture"
    assert index_bundle.manifest["chunk_count"] == len(index_bundle.chunk_ids)
    assert index_bundle.manifest["provision_count"] == len(corpus.provisions)
    assert (settings.vectorstore_path / "faiss.index").exists()
    assert (settings.vectorstore_path / "index_manifest.json").exists()


def test_load_round_trip_keeps_chunk_mapping(index_bundle, corpus, settings):
    loaded = load_index(corpus, embedder=HashEmbedder(), index_dir=settings.vectorstore_path)
    assert loaded.chunk_ids == index_bundle.chunk_ids
    assert loaded.chunks == index_bundle.chunks
    assert loaded.chunk(loaded.chunk_ids[0])["chunk_id"] == loaded.chunk_ids[0]


def test_dense_scores_are_higher_is_better(index_bundle):
    results = index_bundle.dense_search("grievance officer consumer refund complaint", top_k=5)
    assert results
    scores = [score for _, score in results]
    assert scores == sorted(scores, reverse=True)
    assert all(chunk_id in index_bundle.chunk_ids for chunk_id, _ in results)


def test_sparse_search_finds_grievance_provision(index_bundle):
    results = index_bundle.sparse_search("grievance officer complaint", top_k=10)
    ids = [chunk_id for chunk_id, _ in results]
    assert any(chunk_id.startswith("TEST_ACT_A3") for chunk_id in ids)


def test_whitespace_query_returns_nothing(index_bundle):
    assert index_bundle.dense_search("   ") == []
    assert index_bundle.sparse_search("   ") == []


def test_stale_corpus_version_is_rejected(corpus, settings):
    stale = replace(corpus, corpus_version="not-the-built-version")
    with pytest.raises(IndexStale):
        load_index(stale, embedder=HashEmbedder(), index_dir=settings.vectorstore_path)


def test_missing_manifest_is_rejected(corpus, tmp_path):
    with pytest.raises(IndexStale):
        load_index(corpus, embedder=HashEmbedder(), index_dir=tmp_path / "empty")


def test_index_rebuild_replaces_a_read_only_folder(tmp_path):
    """OneDrive marks folders read-only; the rebuild must still replace them."""
    import os
    import stat

    from ai_lawyer.legal_rag.index_manager import _atomic_replace_dir

    target = tmp_path / "vectorstore"
    target.mkdir()
    (target / "old.txt").write_text("old")
    os.chmod(target / "old.txt", stat.S_IREAD)
    os.chmod(target, stat.S_IREAD | stat.S_IEXEC)
    source = tmp_path / "new"
    source.mkdir()
    (source / "new.txt").write_text("new")

    _atomic_replace_dir(target, source)

    assert (target / "new.txt").read_text() == "new"
    assert not (target / "old.txt").exists()
