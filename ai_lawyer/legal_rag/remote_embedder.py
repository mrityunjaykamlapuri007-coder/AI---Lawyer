"""Client for the remote embedding service (kaggle/embed_server.py).

The model runs on Kaggle; this machine never loads embedding weights.

Contract::

    GET  /info   -> {"model_id", "dimension", "model_hash", "device"}
    POST /embed  {"texts": [...], "kind": "query" | "passage"}
                 -> {"vectors": [[...]], "model_id", "dimension", "model_hash"}

Both need ``Authorization: Bearer <EMBEDDER_API_KEY>``.  Vectors are L2-normalised
by the server; the client verifies it.  Timeouts and connection errors are
retried twice, then raised.  There is never a fallback to another embedder.
"""
from __future__ import annotations

import time
from typing import Any, Sequence

import numpy as np

from ai_lawyer.contracts.errors import NotConfigured, UserSafeError

NORM_TOLERANCE = 1e-3


class EmbedderUnavailable(UserSafeError):
    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(
            error_code="embedder_unavailable",
            user_safe_message=message,
            retryable=retryable,
        )


class RemoteHTTPEmbedder:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_s: float = 60,
        batch_size: int = 32,
        retries: int = 2,
        transport: Any = None,
    ) -> None:
        if not base_url:
            raise NotConfigured("EMBEDDER_BASE_URL")
        if not api_key:
            raise NotConfigured("EMBEDDER_API_KEY")
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.timeout_s = timeout_s
        self.batch_size = max(1, batch_size)
        self.retries = retries
        self._transport = transport
        self._info: dict[str, Any] | None = None

    # -- metadata -----------------------------------------------------------
    def info(self) -> dict[str, Any]:
        if self._info is None:
            data = self._request("GET", "/info")
            for key in ("model_id", "dimension", "model_hash"):
                if not data.get(key):
                    raise EmbedderUnavailable(f"embedder /info is missing {key}", retryable=False)
            self._info = data
        return self._info

    @property
    def model_id(self) -> str:
        return str(self.info()["model_id"])

    @property
    def model_hash(self) -> str:
        return str(self.info()["model_hash"])

    @property
    def dimension(self) -> int:
        return int(self.info()["dimension"])

    # -- embedding ----------------------------------------------------------
    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Passages (index build)."""
        return self._embed(texts, "passage")

    def embed_query(self, text: str) -> np.ndarray:
        """A query; the server applies the model's query instruction."""
        return self._embed([text], "query")

    def _embed(self, texts: Sequence[str], kind: str) -> np.ndarray:
        info = self.info()
        if not texts:
            return np.zeros((0, int(info["dimension"])), dtype="float32")
        out: list[np.ndarray] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            data = self._request("POST", "/embed", json={"texts": batch, "kind": kind})
            if data.get("model_hash") != info["model_hash"]:
                raise EmbedderUnavailable(
                    "embedder model changed during the session (model_hash differs); refusing",
                    retryable=False,
                )
            vectors = np.asarray(data.get("vectors"), dtype="float32")
            if vectors.ndim != 2 or vectors.shape != (len(batch), int(info["dimension"])):
                raise EmbedderUnavailable(
                    f"embedder returned shape {vectors.shape}, expected "
                    f"({len(batch)}, {info['dimension']})",
                    retryable=False,
                )
            norms = np.linalg.norm(vectors, axis=1)
            if np.any(np.abs(norms - 1.0) > NORM_TOLERANCE):
                raise EmbedderUnavailable("embedder vectors are not L2-normalised", retryable=False)
            out.append(vectors)
        return np.vstack(out)

    # -- transport ----------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        import httpx  # lazy

        headers = {"Authorization": f"Bearer {self._api_key}"}
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with httpx.Client(
                    timeout=self.timeout_s, transport=self._transport, headers=headers
                ) as client:
                    response = client.request(method, self.base_url + path, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
                if attempt < self.retries:
                    time.sleep(min(2.0, 0.5 * (attempt + 1)))
                    continue
                raise EmbedderUnavailable(
                    f"embedder unreachable after {self.retries + 1} attempts "
                    f"({type(exc).__name__}); is the Kaggle notebook and tunnel running?"
                ) from exc
            if response.status_code in (401, 403):
                raise EmbedderUnavailable(
                    "embedder rejected the key (check EMBEDDER_API_KEY)", retryable=False
                )
            if response.status_code != 200:
                raise EmbedderUnavailable(
                    f"embedder returned HTTP {response.status_code}", retryable=response.status_code >= 500
                )
            return response.json()
        raise EmbedderUnavailable(f"embedder failed: {type(last).__name__}")  # pragma: no cover
