"""Health check for the remote services on Kaggle (LLM and embedder).

    python -m ai_lawyer.tools.check_remote

Pings each configured service, prints model id, latency and PASS/FAIL.  Never
prints API keys or full URLs (only the host).  Exit 0 only if every service is
configured and passes; otherwise 2.
"""
from __future__ import annotations

import sys
import time
from typing import Any, Callable
from urllib.parse import urlparse

from ai_lawyer.config.settings import Settings, get_settings


def _host(url: str) -> str:
    return urlparse(url).hostname or "(invalid url)"


def check_llm(settings: Settings, transport: Any = None) -> dict[str, Any]:
    import httpx

    if settings.llm_provider != "openai_compatible" or not settings.llm_base_url or not settings.llm_api_key:
        return {"service": "llm", "ok": False, "detail": "not configured (LLM_PROVIDER/LLM_BASE_URL/LLM_API_KEY)"}
    start = time.perf_counter()
    try:
        with httpx.Client(timeout=settings.llm_timeout_s, transport=transport) as client:
            response = client.get(
                settings.llm_base_url.rstrip("/") + "/models",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            )
    except httpx.HTTPError as exc:
        return {"service": "llm", "ok": False, "host": _host(settings.llm_base_url),
                "detail": f"unreachable ({type(exc).__name__})"}
    latency = round(time.perf_counter() - start, 3)
    if response.status_code in (401, 403):
        return {"service": "llm", "ok": False, "host": _host(settings.llm_base_url),
                "latency_s": latency, "detail": "key rejected"}
    if response.status_code != 200:
        return {"service": "llm", "ok": False, "host": _host(settings.llm_base_url),
                "latency_s": latency, "detail": f"HTTP {response.status_code}"}
    models = [m.get("id") for m in response.json().get("data", [])]
    wanted = settings.llm_model_name
    ok = not wanted or wanted in models
    return {"service": "llm", "ok": ok, "host": _host(settings.llm_base_url), "latency_s": latency,
            "model_id": ", ".join(str(m) for m in models),
            "detail": "ok" if ok else f"served models do not include LLM_MODEL={wanted}"}


def check_embedder(settings: Settings, transport: Any = None) -> dict[str, Any]:
    from ai_lawyer.contracts.errors import UserSafeError
    from ai_lawyer.legal_rag.remote_embedder import RemoteHTTPEmbedder

    backends = {"remote_http", "openai_compatible"}
    if settings.embedding_backend not in backends or not settings.embedder_base_url or not settings.embedder_api_key:
        return {"service": "embedder", "ok": False,
                "detail": "not configured (EMBEDDING_BACKEND=remote_http|openai_compatible, "
                          "EMBEDDER_BASE_URL, EMBEDDER_API_KEY)"}
    if settings.embedding_backend == "openai_compatible":
        from ai_lawyer.legal_rag.remote_embedder import OpenAICompatibleEmbedder

        embedder = OpenAICompatibleEmbedder(
            settings.embedder_base_url, settings.embedder_api_key, settings.embedding_model_id,
            query_prefix=settings.embedder_query_prefix,
            timeout_s=settings.embedder_timeout_s, retries=0, transport=transport,
        )
    else:
        embedder = RemoteHTTPEmbedder(
            settings.embedder_base_url, settings.embedder_api_key,
            timeout_s=settings.embedder_timeout_s, retries=0, transport=transport,
        )
    start = time.perf_counter()
    try:
        vector = embedder.embed_query("refund not received")
    except UserSafeError as exc:
        return {"service": "embedder", "ok": False, "host": _host(settings.embedder_base_url),
                "detail": exc.user_safe_message}
    return {"service": "embedder", "ok": True, "host": _host(settings.embedder_base_url),
            "latency_s": round(time.perf_counter() - start, 3), "model_id": embedder.model_id,
            "model_hash": embedder.model_hash, "dimension": int(vector.shape[1]), "detail": "ok"}


def run(settings: Settings | None = None, *, transport: Any = None,
        out: Callable[[str], None] = print) -> int:
    settings = settings or get_settings()
    results = [check_llm(settings, transport), check_embedder(settings, transport)]
    for r in results:
        fields = " ".join(
            f"{k}={r[k]}" for k in ("host", "model_id", "model_hash", "dimension", "latency_s") if k in r
        )
        out(f"{r['service']:9} {'PASS' if r['ok'] else 'FAIL'}  {fields}  ({r['detail']})")
    return 0 if all(r["ok"] for r in results) else 2


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
