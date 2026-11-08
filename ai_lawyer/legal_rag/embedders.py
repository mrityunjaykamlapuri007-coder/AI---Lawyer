"""Embedder factory.  Heavy models are imported and loaded lazily."""
from __future__ import annotations

from typing import Sequence

import numpy as np

from ai_lawyer.config.settings import Settings, get_settings
from ai_lawyer.contracts.errors import UserSafeError


class RealModeEmbedderRefused(UserSafeError):
    def __init__(self, message: str) -> None:
        super().__init__("embedder_refused", message, status_code=503)


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
    if settings.embedding_backend == "remote_http":
        from ai_lawyer.legal_rag.remote_embedder import RemoteHTTPEmbedder

        return RemoteHTTPEmbedder(
            settings.embedder_base_url,
            settings.embedder_api_key,
            timeout_s=settings.embedder_timeout_s,
            batch_size=settings.embedder_batch_size,
        )
    if settings.embedding_backend == "openai_compatible":
        from ai_lawyer.legal_rag.remote_embedder import OpenAICompatibleEmbedder

        return OpenAICompatibleEmbedder(
            settings.embedder_base_url,
            settings.embedder_api_key,
            settings.embedding_model_id,
            query_prefix=settings.embedder_query_prefix,
            timeout_s=settings.embedder_timeout_s,
            batch_size=settings.embedder_batch_size,
        )
    if settings.embedding_backend == "sentence_transformers":
        return SentenceTransformerEmbedder(settings.embedding_model_id)
    if settings.corpus_mode == "real":
        # R-2 / C7.2: a hashed embedder is never a stand-in for a real one.
        raise RealModeEmbedderRefused(
            "CORPUS_MODE=real needs a real embedder; the hashed test "
            "embedder is refused"
        )
    from ai_lawyer.tests.fakes import HashEmbedder  # test/fixture mode only

    return HashEmbedder()
