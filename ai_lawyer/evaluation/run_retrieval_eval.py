"""Retrieval experiments E1/E2/E3/E5 on the FIXTURE corpus.

E4 (cross-encoder reranker) is NOT RUN because RERANKER_ENABLED=false and the
optional model is not installed.  Every output is labelled FIXTURE.

Run with:
    python -m ai_lawyer.evaluation.run_retrieval_eval
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from datetime import date, datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from ai_lawyer.config.settings import PROJECT_ROOT, Settings
from ai_lawyer.contracts.fakes import FakeLLM, HashEmbedder
from ai_lawyer.contracts.models import Fact
from ai_lawyer.evaluation.dataset_loader import load_dataset
from ai_lawyer.evaluation.metrics import (
    applicability_scores,
    mean,
    mrr_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from ai_lawyer.legal_engine.retry_policy import run_with_verification
from ai_lawyer.legal_rag.corpus_loader import load_corpus
from ai_lawyer.legal_rag.index_manager import build_index
from ai_lawyer.legal_rag.query_planner import QueryPlan, plan_query
from ai_lawyer.legal_rag.retriever import Retriever

EVAL_DIR = PROJECT_ROOT / "ai_lawyer" / "evaluation"
RAW_DIR = EVAL_DIR / "raw_outputs"
RESULT_DIR = EVAL_DIR / "results"
DATASET_DIR = EVAL_DIR / "dataset"
FIXTURE_CORPUS = PROJECT_ROOT / "ai_lawyer" / "legal_corpus"
K_VALUES = (5, 10, 20)
PACKAGES = (
    "fastapi",
    "pydantic",
    "numpy",
    "pandas",
    "faiss-cpu",
    "rank-bm25",
    "pymupdf",
    "jinja2",
    "streamlit",
)


def _settings(tmp: Path) -> Settings:
    return Settings(
        app_env="evaluation",
        corpus_mode="fixture",
        corpus_dir=str(FIXTURE_CORPUS),
        vectorstore_dir=str(tmp / "vectorstore"),
        sqlite_path=str(tmp / "lawyer.db"),
        evidence_dir=str(tmp / "evidence"),
        embedding_backend="hash",
        llm_provider="fake",
        reranker_enabled=False,
        # Opt-in parity stages, measured separately so the default run stays
        # reproducible:  RAG_BOOST=1 / RAG_COMPRESSION=1
        boost_enabled=os.getenv("RAG_BOOST", "0") == "1",
        compression_enabled=os.getenv("RAG_COMPRESSION", "0") == "1",
    )


def _facts(row: dict[str, Any], as_of: date) -> list[Fact]:
    facts: list[Fact] = []
    for fact_type, value in (row.get("case_facts") or {}).items():
        facts.append(
            Fact(
                case_id="eval",
                fact_type=fact_type,
                raw_value=str(value),
                normalised_value=value,
                source_type="user_message",
                source_id="eval",
                status="user_reported",
                created_at=datetime.combine(as_of, datetime.min.time()),
            )
        )
    return facts


def _provision_order(chunk_ids: list[str], index) -> list[str]:
    out: list[str] = []
    for chunk_id in chunk_ids:
        chunk = index.chunk(chunk_id)
        if chunk is None:
            continue
        pid = chunk["provision_id"]
        if pid not in out:
            out.append(pid)
    return out


def _relevant(row: dict[str, Any]) -> set[str]:
    grades = row.get("relevance_by_provision") or {}
    return {pid for pid, grade in grades.items() if int(grade) >= 2}


def _row_metrics(retrieved: list[str], row: dict[str, Any], k: int) -> dict[str, Any]:
    grades = {pid: int(g) for pid, g in (row.get("relevance_by_provision") or {}).items()}
    return {
        "precision_at_k": precision_at_k(retrieved, _relevant(row), k),
        "recall_at_k": recall_at_k(retrieved, row.get("essential_provision_ids", []), k),
        "mrr_at_k": mrr_at_k(retrieved, grades, k),
        "ndcg_at_k": ndcg_at_k(retrieved, grades, k),
    }


def _verification_row(row, corpus, retriever, settings) -> dict[str, Any]:
    as_of = date.fromisoformat(row.get("as_of_date") or "2026-11-08")
    facts = _facts(row, as_of)
    plan = plan_query(row["user_query"], facts, {})
    outcome = run_with_verification(
        retriever=retriever,
        corpus=corpus,
        facts=facts,
        as_of_date=as_of,
        plan=plan,
        case_summary=row["user_query"],
        llm=FakeLLM(),
        settings=settings,
        conversation_id=f"eval-{row['test_id']}",
    )
    accepted = [c for c in outcome.candidates if c.accepted]
    ids = [c.provision_id for c in accepted]
    grades = {pid: int(g) for pid, g in (row.get("relevance_by_provision") or {}).items()}
    predicted_applicability = {c.provision_id: c.applicability for c in accepted}
    app = applicability_scores(
        predicted_applicability, row.get("applicability_by_provision") or {}
    )
    return {
        "test_id": row["test_id"],
        "split": row["split"],
        "accepted_provision_ids": ids,
        "retry_count": outcome.retry_count,
        "abstained": outcome.abstained,
        "precision": precision_at_k(ids, _relevant(row), max(1, len(ids))),
        "recall": recall_at_k(ids, row.get("essential_provision_ids", []), max(1, len(ids))),
        "mrr": mrr_at_k(ids, grades, max(1, len(ids))),
        "ndcg": ndcg_at_k(ids, grades, max(1, len(ids))),
        "applicability": app,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        settings = _settings(tmp)
        corpus = load_corpus(settings=settings)
        dataset = load_dataset(DATASET_DIR, corpus)
        index = build_index(
            corpus,
            HashEmbedder(),
            out_dir=settings.vectorstore_path,
            max_chunk_chars=settings.max_chunk_chars,
        )
        retriever = Retriever(index, corpus, settings.model_copy(update={"fused_top_k": 20}))

        raw_path = RAW_DIR / "retrieval_raw.jsonl"
        records: list[dict[str, Any]] = []
        with raw_path.open("w", encoding="utf-8") as raw:
            for row in dataset.rows:
                query = row["user_query"]
                as_of = date.fromisoformat(row.get("as_of_date") or "2026-11-08")
                facts = _facts(row, as_of)
                plan = QueryPlan(
                    original_query=query,
                    self_contained_query=query,
                    expansions=[],
                    issue_tags=[],
                    include_original=True,
                )
                dense = _provision_order(
                    [cid for cid, _ in index.dense_search(query, top_k=max(K_VALUES))],
                    index,
                )
                sparse = _provision_order(
                    [cid for cid, _ in index.sparse_search(query, top_k=max(K_VALUES))],
                    index,
                )
                hybrid_result = retriever.search(
                    plan, include_expansions=False, conversation_id=f"eval-{row['test_id']}"
                )
                hybrid = [c.provision_id for c in hybrid_result.candidates]
                for mode, retrieved in (
                    ("E1_dense_faiss", dense),
                    ("E2_sparse_bm25", sparse),
                    ("E3_hybrid_rrf", hybrid),
                ):
                    for k in K_VALUES:
                        metrics = _row_metrics(retrieved, row, k)
                        record = {
                            "mode": mode,
                            "test_id": row["test_id"],
                            "split": row["split"],
                            "category": row.get("category"),
                            "k": k,
                            "retrieved": retrieved[:k],
                            "labeling_status": row.get("labeling_status", "FIXTURE"),
                            **metrics,
                        }
                        records.append(record)
                        raw.write(json.dumps(record, ensure_ascii=False) + "\n")

                verification = _verification_row(row, corpus, retriever, settings)
                verification["labeling_status"] = row.get("labeling_status", "FIXTURE")
                records.append({"mode": "E5_verification", **verification})
                raw.write(json.dumps({"mode": "E5_verification", **verification}, ensure_ascii=False) + "\n")

        summary: list[dict[str, Any]] = []
        for mode in ("E1_dense_faiss", "E2_sparse_bm25", "E3_hybrid_rrf"):
            for split in ("development", "test"):
                for k in K_VALUES:
                    subset = [
                        r for r in records
                        if r.get("mode") == mode and r.get("split") == split and r.get("k") == k
                    ]
                    summary.append(
                        {
                            "label": "FIXTURE DATA, NOT REAL LAW",
                            "mode": mode,
                            "split": split,
                            "k": k,
                            "n": len(subset),
                            "precision_at_k": mean(r["precision_at_k"] for r in subset),
                            "recall_at_k": mean(r["recall_at_k"] for r in subset),
                            "mrr_at_k": mean(r["mrr_at_k"] for r in subset),
                            "ndcg_at_k": mean(r["ndcg_at_k"] for r in subset),
                            "recall_na": sum(1 for r in subset if r["recall_at_k"] is None),
                            "ndcg_na": sum(1 for r in subset if r["ndcg_at_k"] is None),
                        }
                    )
        _write_csv(RESULT_DIR / "retrieval_summary.csv", summary)

        verification_rows = [r for r in records if r.get("mode") == "E5_verification"]
        verification_summary = []
        for split in ("development", "test"):
            subset = [r for r in verification_rows if r["split"] == split]
            verification_summary.append(
                {
                    "label": "FIXTURE DATA, NOT REAL LAW",
                    "split": split,
                    "n": len(subset),
                    "mean_accepted": mean(len(r["accepted_provision_ids"]) for r in subset),
                    "precision": mean(r["precision"] for r in subset),
                    "recall": mean(r["recall"] for r in subset),
                    "mrr": mean(r["mrr"] for r in subset),
                    "ndcg": mean(r["ndcg"] for r in subset),
                    "applicability_precision": mean(r["applicability"]["precision"] for r in subset),
                    "applicability_recall": mean(r["applicability"]["recall"] for r in subset),
                    "false_acceptance_rate": mean(
                        r["applicability"]["false_acceptance_rate"] for r in subset
                    ),
                    "abstentions": sum(1 for r in subset if r["abstained"]),
                }
            )
        _write_csv(RESULT_DIR / "verification_summary.csv", verification_summary)

        manifest = {
            "label": "FIXTURE DATA, NOT REAL LAW",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "experiments": {
                "E1_dense_faiss": "RUN",
                "E2_sparse_bm25": "RUN",
                "E3_hybrid_rrf": "RUN",
                "E4_reranker": "NOT RUN (RERANKER_ENABLED=false; optional model not installed)",
                "E5_verification": "RUN (deterministic guards + FakeLLM relevance grading)",
            },
            "corpus": {
                "mode": corpus.mode,
                "version": corpus.corpus_version,
                "sources": len(corpus.sources),
                "provisions": len(corpus.provisions),
                "usable": corpus.usable_count,
                "unusable": corpus.unusable_count,
            },
            "embedder": index.manifest.get("embedder_id"),
            "llm": "fake (deterministic, offline)",
            "k_values": list(K_VALUES),
            "dataset": {
                "rows": len(dataset.rows),
                "development": len(dataset.split("development")),
                "test": len(dataset.split("test")),
                "sha256": {
                    name: hashlib.sha256((DATASET_DIR / name).read_bytes()).hexdigest()
                    for name in ("development.jsonl", "test.jsonl")
                },
            },
            "packages": {
                name: metadata.version(name) for name in PACKAGES
            },
            "settings": {
                "rrf_k": settings.rrf_k,
                "dense_top_k": settings.dense_top_k,
                "sparse_top_k": settings.sparse_top_k,
                "fused_top_k_for_eval": 20,
                "max_retrieval_retries": settings.max_retrieval_retries,
                "relevance_min_grade": settings.relevance_min_grade,
                "boost_enabled": settings.boost_enabled,
                "exact_reference_boost": settings.exact_reference_boost,
                "qualifier_tiebreak": settings.qualifier_tiebreak,
                "compression_enabled": settings.compression_enabled,
            },
            "notes": [
                "All metrics are for a synthetic 11-provision fixture corpus.",
                "FakeLLM is a deterministic lexical grader, not a semantic model.",
                "Do not report these numbers as real legal retrieval quality.",
            ],
        }
        (RESULT_DIR / "run_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    print(f"FIXTURE rows={len(dataset.rows)} dev={len(dataset.split('development'))} test={len(dataset.split('test'))}")
    print(f"raw: {raw_path}")
    print(f"summary: {RESULT_DIR / 'retrieval_summary.csv'}")
    for row in summary:
        if row["k"] == 5:
            print(
                f"{row['mode']} {row['split']} k=5 n={row['n']} "
                f"P={row['precision_at_k']} R={row['recall_at_k']} "
                f"MRR={row['mrr_at_k']} nDCG={row['ndcg_at_k']} "
                f"recall_NA={row['recall_na']}"
            )
    print(f"verification: {RESULT_DIR / 'verification_summary.csv'}")


if __name__ == "__main__":
    main()
