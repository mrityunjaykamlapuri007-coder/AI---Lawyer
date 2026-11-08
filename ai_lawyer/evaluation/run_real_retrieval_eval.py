"""Retrieval evaluation on the REAL corpus and real stories (REAL_RAG_BUILD Stage 5).

    python -m ai_lawyer.evaluation.run_real_retrieval_eval

E1 dense (FAISS, remote BGE embedder), E2 BM25, E3 hybrid RRF (k=RRF_K) over the
verified runtime corpus.  Rows: ``real_retrieval_labels.jsonl`` with
``labeling_status: machine_derived`` only; development and test reported
separately with row counts.  E4 (reranker) and the false acceptance rate (needs
the LLM verification step) are reported as NOT RUN with the reason.

Fails closed (``BLOCKED``, exit 2) if the real corpus or the remote embedder is
unavailable.  Raw ranked lists are written by code and hashed in the manifest.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_lawyer.config.settings import PROJECT_ROOT, get_settings
from ai_lawyer.contracts.errors import UserSafeError
from ai_lawyer.evaluation.metrics import mean, mrr_at_k, ndcg_at_k, precision_at_k, recall_at_k
from ai_lawyer.legal_rag.rrf import fuse

EVAL_DIR = PROJECT_ROOT / "ai_lawyer" / "evaluation"
LABELS = EVAL_DIR / "dataset" / "real_retrieval_labels.jsonl"
SYNTHETIC = EVAL_DIR / "dataset" / "retrieval_stories_to_label.jsonl"
OUT_DIR = EVAL_DIR / "results" / "real_retrieval"
K_VALUES = (5, 10, 20)
DEPTH = 20
LABEL_CAVEAT = (
    "Gold labels are machine-derived from machine-verified conditions (not human labels). "
    "Only provisions whose conditions are fully extractable can be labelled, so most rows "
    "share the same 2-3 gold provisions and unlabelled provisions are not known to be "
    "irrelevant: precision is a lower bound."
)


def provision_order(chunk_ids: list[str], chunk_to_provision: dict[str, str]) -> list[str]:
    out: list[str] = []
    for chunk_id in chunk_ids:
        pid = chunk_to_provision.get(chunk_id)
        if pid and pid not in out:
            out.append(pid)
    return out


def rankings(index: Any, query: str, rrf_k: int) -> dict[str, list[str]]:
    """Provision rankings for E1/E2/E3 from one index."""
    chunk_to_provision = {c["chunk_id"]: c["provision_id"] for c in index.chunks}
    dense = [cid for cid, _ in index.dense_search(query, DEPTH)]
    sparse = [cid for cid, _ in index.sparse_search(query, DEPTH)]
    hybrid = [r.chunk_id for r in fuse({"dense": dense, "sparse": sparse}, k=rrf_k)]
    return {
        "E1_dense": provision_order(dense, chunk_to_provision),
        "E2_bm25": provision_order(sparse, chunk_to_provision),
        "E3_hybrid_rrf": provision_order(hybrid, chunk_to_provision),
    }


def row_metrics(ranked: list[str], row: dict[str, Any], k: int) -> dict[str, float | None]:
    grades = {pid: int(g) for pid, g in row["relevance_by_provision"].items()}
    relevant = {pid for pid, g in grades.items() if g >= 2}
    return {
        "precision": precision_at_k(ranked, relevant, k),
        "recall": recall_at_k(ranked, row["essential_provision_ids"], k),
        "mrr": mrr_at_k(ranked, grades, k),
        "ndcg": ndcg_at_k(ranked, grades, k),
    }


def summarise(per_row: list[dict[str, Any]], corpus_size: int) -> list[dict[str, Any]]:
    table: list[dict[str, Any]] = []
    for experiment in ("E1_dense", "E2_bm25", "E3_hybrid_rrf"):
        for split in ("development", "test"):
            rows = [r for r in per_row if r["split"] == split]
            for k in K_VALUES:
                kk = min(k, corpus_size)
                values = [row_metrics(r["rankings"][experiment], r, kk) for r in rows]
                table.append({
                    "experiment": experiment, "split": split, "k": kk, "rows": len(rows),
                    **{f"{m}@k": mean(v[m] for v in values) for m in ("precision", "recall", "mrr", "ndcg")},
                    "recall_na_rows": sum(1 for v in values if v["recall"] is None),
                })
    return table


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    from ai_lawyer.legal_rag.corpus_loader import load_corpus
    from ai_lawyer.legal_rag.embedders import get_embedder
    from ai_lawyer.legal_rag.index_manager import build_index

    settings = get_settings().model_copy(update={"corpus_mode": "real"})
    try:
        corpus = load_corpus("real", settings=settings)
        embedder = get_embedder(settings)
        with tempfile.TemporaryDirectory() as tmp:
            index = build_index(corpus, embedder, out_dir=Path(tmp) / "index",
                                max_chunk_chars=settings.max_chunk_chars)
            labels = [json.loads(l) for l in LABELS.read_text(encoding="utf-8").splitlines() if l.strip()]
            usable = [r for r in labels if r["labeling_status"] == "machine_derived"]
            per_row = [{**r, "rankings": rankings(index, r["user_query"], settings.rrf_k)} for r in usable]
    except UserSafeError as exc:
        print(f"BLOCKED: {exc.user_safe_message}")
        if exc.details.get("detail"):
            print(f"  - {exc.details['detail']}")
        print("Start kaggle/serve_all.ipynb, fill .env, run `python -m ai_lawyer.tools.check_remote`.")
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_dir = OUT_DIR / "raw"
    raw_dir.mkdir(exist_ok=True)
    for experiment in ("E1_dense", "E2_bm25", "E3_hybrid_rrf"):
        (raw_dir / f"{experiment}.jsonl").write_text(
            "".join(json.dumps({"test_id": r["test_id"], "split": r["split"],
                                "ranked_provision_ids": r["rankings"][experiment],
                                "gold": r["essential_provision_ids"]}) + "\n" for r in per_row),
            encoding="utf-8",
        )
    table = summarise(per_row, len(corpus.usable_ids()))
    with (OUT_DIR / "retrieval_metrics.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)

    synthetic_labelled = sum(
        1 for l in SYNTHETIC.read_text(encoding="utf-8").splitlines()
        if l.strip() and json.loads(l).get("labeling_status") not in {None, "TODO_human"}
    )
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_origin": "public_commission_order",
        "label_note": LABEL_CAVEAT,
        "rows": {"total_labels_file": len(labels), "machine_derived": len(usable),
                 "development": sum(r["split"] == "development" for r in usable),
                 "test": sum(r["split"] == "test" for r in usable)},
        "corpus_version": corpus.corpus_version, "corpus_usable": corpus.usable_count,
        "trust_level": settings.corpus_trust_level,
        "embedder_id": index.manifest.get("embedder_id"),
        "embedder_model_hash": index.manifest.get("embedder_model_hash"),
        "rrf_k": settings.rrf_k, "k_values_clipped_to": len(corpus.usable_ids()),
        "experiments": {"E1_dense": "RUN", "E2_bm25": "RUN", "E3_hybrid_rrf": "RUN",
                        "E4_reranker": "NOT RUN: reranker not deployed on Kaggle",
                        "false_acceptance_rate": "NOT RUN here: needs the LLM verification step; see behaviour run"},
        "synthetic_table": f"{synthetic_labelled} labelled synthetic rows; no synthetic metrics reported",
        "tuning": "none; parameters are the configured defaults, not chosen on these rows",
        "raw_sha256": {p.name: _sha(p) for p in sorted(raw_dir.glob("*.jsonl"))},
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"rows: {manifest['rows']}")
    for row in table:
        print(f"{row['experiment']:14} {row['split']:11} k={row['k']:2} n={row['rows']:2} "
              f"P={row['precision@k']} R={row['recall@k']} MRR={row['mrr@k']} nDCG={row['ndcg@k']}")
    print("NOTE:", LABEL_CAVEAT)
    print(f"results: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
