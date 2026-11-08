"""FAISS + BM25 index build / load with a verified manifest.

Only local indexes built by this project are loaded.  We use
``faiss.read_index`` (not pickle-based deserialisation), so no
``allow_dangerous_deserialization`` flag exists in this code path.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from ai_lawyer.config.settings import Settings, get_settings
from ai_lawyer.contracts.errors import IndexStale
from ai_lawyer.contracts.models import CorpusManifest
from ai_lawyer.legal_rag.chunker import chunk_corpus
from ai_lawyer.legal_rag.corpus_loader import Corpus
from ai_lawyer.legal_rag.embedders import get_embedder

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_.:/-]+")


def bm25_tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


@dataclass
class IndexBundle:
    chunks: list[dict[str, Any]]
    chunk_ids: list[str]
    faiss_index: Any
    bm25: Any
    bm25_tokens: list[list[str]]
    manifest: dict[str, Any]
    embedder: Any

    @property
    def index_version(self) -> str:
        return str(self.manifest.get("built_at", ""))

    def chunk(self, chunk_id: str) -> dict[str, Any] | None:
        for item in self.chunks:
            if item["chunk_id"] == chunk_id:
                return item
        return None

    def dense_search(self, query: str, top_k: int = 20) -> list[tuple[str, float]]:
        if not query.strip() or not self.chunk_ids:
            return []
        if hasattr(self.embedder, "embed_query"):
            vec = np.asarray(self.embedder.embed_query(query), dtype="float32")
        else:
            vec = np.asarray(self.embedder.embed([query]), dtype="float32")
        scores, positions = self.faiss_index.search(vec, min(top_k, len(self.chunk_ids)))
        out: list[tuple[str, float]] = []
        for pos, score in zip(positions[0], scores[0]):
            if int(pos) < 0:
                continue
            out.append((self.chunk_ids[int(pos)], float(score)))
        return out

    def sparse_search(self, query: str, top_k: int = 20) -> list[tuple[str, float]]:
        toks = bm25_tokens(query)
        if not toks or not self.bm25_tokens:
            return []
        scores = self.bm25.get_scores(toks)
        if len(scores) == 0 or float(np.max(scores)) <= 0:
            return []
        order = sorted(range(len(scores)), key=lambda i: (-float(scores[i]), self.chunk_ids[i]))
        return [(self.chunk_ids[i], float(scores[i])) for i in order[:top_k] if scores[i] > 0]


def _clear_readonly_and_retry(func, path, _exc) -> None:
    """Windows refuses to delete read-only files and folders (OneDrive sets the flag)."""
    import stat

    os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
    func(path)


def _atomic_replace_dir(target: Path, source: Path) -> None:
    if target.exists():
        shutil.rmtree(target, onexc=_clear_readonly_and_retry)
    os.replace(source, target)


def build_index(
    corpus: Corpus,
    embedder,
    *,
    out_dir: str | Path | None = None,
    max_chunk_chars: int = 1800,
) -> IndexBundle:
    import faiss  # lazy

    out = Path(out_dir) if out_dir else get_settings().vectorstore_path
    out.parent.mkdir(parents=True, exist_ok=True)
    temp = out.parent / f".{out.name}.tmp-{uuid.uuid4().hex}"

    chunks = chunk_corpus(corpus, max_chars=max_chunk_chars)
    chunk_dicts = [c.to_dict() for c in chunks]
    chunk_ids = [c.chunk_id for c in chunks]
    texts = [c.search_text for c in chunks]
    vectors = np.asarray(embedder.embed(texts), dtype="float32")

    index = faiss.IndexFlatIP(vectors.shape[1])
    if len(vectors):
        index.add(vectors)
    tokenised = [bm25_tokens(t) for t in texts]
    built_at = datetime.now(timezone.utc).isoformat()

    manifest = {
        "corpus_version": corpus.corpus_version,
        "corpus_mode": corpus.mode,
        "embedder_id": embedder.model_id,
        "embedder_model_hash": getattr(embedder, "model_hash", None),
        "dimension": int(vectors.shape[1]),
        "chunk_count": len(chunks),
        "provision_count": len(corpus.provisions),
        "built_at": built_at,
    }
    if corpus.mode == "real" and not manifest["embedder_model_hash"]:
        raise IndexStale("real-mode index needs an embedder with a model_hash (remote_http)")

    temp.mkdir(parents=True, exist_ok=True)
    try:
        faiss.write_index(index, str(temp / "faiss.index"))
        (temp / "chunks.json").write_text(
            json.dumps(chunk_dicts, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (temp / "chunk_ids.json").write_text(json.dumps(chunk_ids), encoding="utf-8")
        (temp / "bm25_tokens.json").write_text(json.dumps(tokenised), encoding="utf-8")
        (temp / "index_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        # Same record under the name the spec uses (G2 / REAL_RAG_BUILD Stage 2).
        (temp / "index_meta.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        _atomic_replace_dir(out, temp)
    finally:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)

    from rank_bm25 import BM25Okapi

    return IndexBundle(
        chunks=chunk_dicts,
        chunk_ids=chunk_ids,
        faiss_index=index,
        bm25=BM25Okapi(tokenised) if tokenised else None,
        bm25_tokens=tokenised,
        manifest=manifest,
        embedder=embedder,
    )


def load_index(
    corpus: Corpus | None = None,
    *,
    embedder=None,
    index_dir: str | Path | None = None,
    settings: Settings | None = None,
) -> IndexBundle:
    import faiss  # lazy
    from rank_bm25 import BM25Okapi

    settings = settings or get_settings()
    directory = Path(index_dir) if index_dir else settings.vectorstore_path
    manifest_path = directory / "index_manifest.json"
    if not manifest_path.exists():
        raise IndexStale("no index manifest; run the build command")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if corpus is not None and manifest.get("corpus_version") != corpus.corpus_version:
        raise IndexStale(
            f"index corpus_version={manifest.get('corpus_version')} "
            f"!= current {corpus.corpus_version}"
        )

    embedder = embedder or get_embedder(settings)
    check_embedder_matches(manifest, embedder)

    chunks = json.loads((directory / "chunks.json").read_text(encoding="utf-8"))
    chunk_ids = json.loads((directory / "chunk_ids.json").read_text(encoding="utf-8"))
    tokenised = json.loads((directory / "bm25_tokens.json").read_text(encoding="utf-8"))
    faiss_index = faiss.read_index(str(directory / "faiss.index"))
    return IndexBundle(
        chunks=chunks,
        chunk_ids=chunk_ids,
        faiss_index=faiss_index,
        bm25=BM25Okapi(tokenised) if tokenised else None,
        bm25_tokens=tokenised,
        manifest=manifest,
        embedder=embedder,
    )


def check_embedder_matches(manifest: dict[str, Any], embedder: Any) -> None:
    """Refuse an index built by a different embedder (id or model hash)."""
    if manifest.get("embedder_id") != getattr(embedder, "model_id", None):
        raise IndexStale(
            f"index embedder {manifest.get('embedder_id')!r} != live embedder "
            f"{getattr(embedder, 'model_id', None)!r}"
        )
    built_hash = manifest.get("embedder_model_hash")
    live_hash = getattr(embedder, "model_hash", None)
    if (built_hash or live_hash) and built_hash != live_hash:
        raise IndexStale(
            f"index embedder model_hash {built_hash!r} != live model_hash {live_hash!r}"
        )


def build_or_load(
    corpus: Corpus,
    settings: Settings | None = None,
    *,
    embedder=None,
) -> IndexBundle:
    settings = settings or get_settings()
    embedder = embedder or get_embedder(settings)
    try:
        return load_index(corpus, embedder=embedder, settings=settings)
    except IndexStale:
        logger.info("Building search index for corpus %s", corpus.corpus_version)
        return build_index(
            corpus,
            embedder,
            out_dir=settings.vectorstore_path,
            max_chunk_chars=settings.max_chunk_chars,
        )


def main() -> None:
    """CLI: python -m ai_lawyer.legal_rag.index_manager build"""
    import argparse

    from ai_lawyer.legal_rag.corpus_loader import load_corpus, startup_summary

    parser = argparse.ArgumentParser(description="Build or inspect the legal search index")
    parser.add_argument("command", choices=["build", "inspect"])
    parser.add_argument("--mode", choices=["real", "fixture"], default=None)
    args = parser.parse_args()

    settings = get_settings()
    corpus = load_corpus(args.mode, settings=settings)
    print(startup_summary(corpus))
    if args.command == "build":
        embedder = get_embedder(settings)
        bundle = build_index(
            corpus,
            embedder,
            out_dir=settings.vectorstore_path,
            max_chunk_chars=settings.max_chunk_chars,
        )
        print(
            f"index built: chunks={len(bundle.chunk_ids)} "
            f"embedder={bundle.manifest['embedder_id']} dir={settings.vectorstore_path}"
        )
    else:
        bundle = load_index(corpus, settings=settings)
        print(json.dumps(bundle.manifest, indent=2))


if __name__ == "__main__":
    main()
