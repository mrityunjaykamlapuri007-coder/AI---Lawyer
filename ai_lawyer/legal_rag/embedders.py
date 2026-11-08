"""Embedder factory.  Heavy models are imported and loaded lazily."""
from __future__ import annotations

from typing import Sequence

import numpy as np

from ai_lawyer.config.settings import Settings, get_settings
from ai_lawyer.contracts.fakes import HashEmbedder


class SentenceTransformerEmbedder:
    def __init__(self, model_id: str) -> None:
        from sentence_transformers import SentenceTransformer  # lazy

        self.model_id = model_id
        self._model = SentenceTransformer(model_id, device="cpu")
        self.dimension = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype="float32")
        vecs = self._model.encode(
            list(texts), normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False
        )
        return np.asarray(vecs, dtype="float32")


def get_embedder(settings: Settings | None = None):
    settings = settings or get_settings()
    if settings.embedding_backend == "sentence_transformers":
        return SentenceTransformerEmbedder(settings.embedding_model_id)
    return HashEmbedder()
