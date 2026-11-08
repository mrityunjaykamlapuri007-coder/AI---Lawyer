"""Optional cross-encoder reranker.  Lazy import; disabled by default."""
from __future__ import annotations

import logging
from typing import Any, Sequence

from ai_lawyer.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    def __init__(self, model_id: str) -> None:
        from sentence_transformers import CrossEncoder  # lazy

        self.model_id = model_id
        self._model = CrossEncoder(model_id, device="cpu")

    def rerank(self, query: str, candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        if not candidates:
            return []
        pairs = [(query, str(c.get("text", ""))) for c in candidates]
        scores = self._model.predict(pairs)
        out: list[dict[str, Any]] = []
        for old_rank, (cand, score) in enumerate(zip(candidates, scores), start=1):
            item = dict(cand)
            item["rerank_score"] = float(score)
            item["original_rank"] = old_rank
            out.append(item)
        out.sort(key=lambda c: (-float(c["rerank_score"]), str(c["provision_id"])))
        for new_rank, item in enumerate(out, start=1):
            item["new_rank"] = new_rank
        return out


def get_reranker(settings: Settings | None = None):
    settings = settings or get_settings()
    if not settings.reranker_enabled:
        return None
    try:
        return CrossEncoderReranker(settings.reranker_model_id)
    except Exception as exc:  # model unavailable
        logger.warning("Reranker could not be loaded (%s); continuing without it", type(exc).__name__)
        return None
