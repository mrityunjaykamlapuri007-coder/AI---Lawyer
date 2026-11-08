"""Hybrid retrieval: dense (FAISS) + sparse (BM25), multi-list RRF, provision
consolidation and optional reranking.  Empty results are allowed.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

from ai_lawyer.config.settings import Settings, get_settings
from ai_lawyer.contracts.models import Candidate, RetrievalRun
from ai_lawyer.legal_rag.corpus_loader import Corpus
from ai_lawyer.legal_rag.index_manager import IndexBundle
from ai_lawyer.legal_rag.query_planner import QueryPlan
from ai_lawyer.legal_rag.rrf import fuse

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    candidates: list[Candidate] = field(default_factory=list)
    run: RetrievalRun | None = None


class Retriever:
    def __init__(
        self,
        index: IndexBundle,
        corpus: Corpus,
        settings: Settings | None = None,
        reranker=None,
    ) -> None:
        self.index = index
        self.corpus = corpus
        self.settings = settings or get_settings()
        self.reranker = reranker

    def _dense(self, query: str, top_k: int) -> list[str]:
        return [cid for cid, _ in self.index.dense_search(query, top_k=top_k)]

    def _sparse(self, query: str, top_k: int) -> list[str]:
        return [cid for cid, _ in self.index.sparse_search(query, top_k=top_k)]

    def search(
        self,
        plan: QueryPlan,
        *,
        include_expansions: bool = True,
        conversation_id: str | None = None,
        retry_index: int = 0,
    ) -> RetrievalResult:
        started = perf_counter()
        variants = plan.variants(include_expansions=include_expansions)
        if not variants:
            return RetrievalResult(
                candidates=[],
                run=RetrievalRun(
                    conversation_id=conversation_id,
                    query_variants=[],
                    corpus_version=self.corpus.corpus_version,
                    index_version=self.index.index_version,
                    retry_index=retry_index,
                    latency_ms=0.0,
                ),
            )

        ranked_lists: dict[str, list[str]] = {}
        for i, query in enumerate(variants):
            ranked_lists[f"dense_{i}"] = self._dense(query, self.settings.dense_top_k)
            ranked_lists[f"sparse_{i}"] = self._sparse(query, self.settings.sparse_top_k)

        fused = fuse(ranked_lists, k=self.settings.rrf_k)

        # Provision-level consolidation: keep the best fused chunk per provision.
        by_provision: dict[str, tuple[Any, dict]] = {}
        for item in fused:
            chunk = self.index.chunk(item.chunk_id)
            if not chunk:
                continue
            pid = chunk["provision_id"]
            if pid not in by_provision:
                by_provision[pid] = (item, chunk)

        candidates: list[Candidate] = []
        for pid, (item, chunk) in list(by_provision.items())[: self.settings.fused_top_k]:
            dense_ranks = [r for name, r in item.ranks.items() if name.startswith("dense_")]
            sparse_ranks = [r for name, r in item.ranks.items() if name.startswith("sparse_")]
            candidates.append(
                Candidate(
                    chunk_id=chunk["chunk_id"],
                    provision_id=pid,
                    source_id=chunk["source_id"],
                    dense_rank=min(dense_ranks) if dense_ranks else None,
                    sparse_rank=min(sparse_ranks) if sparse_ranks else None,
                    rrf_score=item.score,
                    citation=chunk.get("citation"),
                )
            )

        if self.reranker is not None and candidates:
            payload = []
            for cand in candidates:
                chunk = self.index.chunk(cand.chunk_id)
                payload.append(
                    {
                        "provision_id": cand.provision_id,
                        "chunk_id": cand.chunk_id,
                        "text": (chunk or {}).get("search_text", ""),
                    }
                )
            reranked = self.reranker.rerank(plan.original_query or plan.self_contained_query, payload)
            by_id = {c.provision_id: c for c in candidates}
            new_order: list[Candidate] = []
            for item in reranked:
                cand = by_id.get(item["provision_id"])
                if cand is None:
                    continue
                cand.rerank_score = item.get("rerank_score")
                new_order.append(cand)
            if len(new_order) == len(candidates):
                candidates = new_order

        run = RetrievalRun(
            conversation_id=conversation_id,
            query_variants=variants,
            ranked_lists={name: ids for name, ids in ranked_lists.items()},
            fused_chunk_ids=[c.chunk_id for c in candidates],
            corpus_version=self.corpus.corpus_version,
            index_version=self.index.index_version,
            retry_index=retry_index,
            latency_ms=round((perf_counter() - started) * 1000, 3),
        )
        return RetrievalResult(candidates=candidates, run=run)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def append_retrieval_log(run: RetrievalRun, path: str | Path) -> None:
    """Append safe diagnostics only (no raw query, no evidence, no PII)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "run_id": run.run_id,
        "conversation_id": run.conversation_id,
        "query_variant_hashes": [_hash(q) for q in run.query_variants],
        "query_variant_lengths": [len(q) for q in run.query_variants],
        "ranked_list_sizes": {k: len(v) for k, v in run.ranked_lists.items()},
        "fused_count": len(run.fused_chunk_ids),
        "corpus_version": run.corpus_version,
        "index_version": run.index_version,
        "retry_index": run.retry_index,
        "latency_ms": run.latency_ms,
    }
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
