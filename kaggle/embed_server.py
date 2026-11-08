"""Embedding service for the refund assistant.  Runs on Kaggle, never locally.

Started by kaggle/serve_all.ipynb:

    EMBED_API_KEY=... EMBED_MODEL_ID=BAAI/bge-large-en-v1.5 EMBED_DEVICE=cpu \
        uvicorn embed_server:app --host 127.0.0.1 --port 8001

Endpoints (both need ``Authorization: Bearer <EMBED_API_KEY>``):

    GET  /info   -> {"model_id", "dimension", "model_hash", "device"}
    POST /embed  {"texts": [...], "kind": "query"|"passage"}
                 -> {"vectors", "model_id", "dimension", "model_hash"}

Vectors are L2-normalised here.  The query instruction is applied only for
``kind="query"``.  ``model_hash`` fingerprints the loaded weights by embedding
fixed probe texts, so a different model or revision gives a different hash and
the app refuses an index built with another one.
"""

import hashlib
import json
import os
import secrets
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

MODEL_ID = os.environ.get("EMBED_MODEL_ID", "BAAI/bge-large-en-v1.5")
DEVICE = os.environ.get("EMBED_DEVICE", "cpu")
# BGE English v1.5 recommends this prefix for retrieval queries (see the model
# card); override with EMBED_QUERY_INSTRUCTION if the model changes.
QUERY_INSTRUCTION = os.environ.get(
    "EMBED_QUERY_INSTRUCTION", "Represent this sentence for searching relevant passages: "
)
MAX_TEXTS = int(os.environ.get("EMBED_MAX_TEXTS", "256"))
MAX_CHARS = int(os.environ.get("EMBED_MAX_CHARS", "8000"))
PROBES = (
    "refund for a cancelled online order",
    "grievance officer acknowledges the complaint",
    "the seller refused to take back defective goods",
)

STATE: dict = {}


def _api_key() -> str:
    key = os.environ.get("EMBED_API_KEY", "")
    if not key:
        raise RuntimeError("EMBED_API_KEY is not set; refusing to start without auth")
    return key


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from sentence_transformers import SentenceTransformer  # heavy; Kaggle only

    STATE["api_key"] = _api_key()
    model = SentenceTransformer(MODEL_ID, device=DEVICE)
    probe = model.encode(list(PROBES), normalize_embeddings=True, convert_to_numpy=True)
    fingerprint = json.dumps(
        {"model_id": MODEL_ID, "probe": [[round(float(x), 4) for x in row] for row in probe]},
        sort_keys=True,
    )
    STATE.update(
        model=model,
        dimension=int(model.get_sentence_embedding_dimension()),
        model_hash=hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:32],
    )
    yield
    STATE.clear()


app = FastAPI(title="refund-assistant embedder", lifespan=lifespan)


class EmbedRequest(BaseModel):
    texts: list[str] = Field(default_factory=list)
    kind: Literal["query", "passage"] = "passage"


def _authorise(authorization: str | None) -> None:
    expected = f"Bearer {STATE.get('api_key', '')}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="unauthorised")


def _info() -> dict:
    return {
        "model_id": MODEL_ID,
        "dimension": STATE["dimension"],
        "model_hash": STATE["model_hash"],
        "device": DEVICE,
    }


@app.get("/info")
def info(authorization: str | None = Header(default=None)) -> dict:
    _authorise(authorization)
    return _info()


@app.post("/embed")
def embed(request: EmbedRequest, authorization: str | None = Header(default=None)) -> dict:
    _authorise(authorization)
    if len(request.texts) > MAX_TEXTS:
        raise HTTPException(status_code=413, detail=f"at most {MAX_TEXTS} texts per request")
    if any(len(t) > MAX_CHARS for t in request.texts):
        raise HTTPException(status_code=413, detail=f"each text at most {MAX_CHARS} characters")
    texts = request.texts
    if request.kind == "query":
        texts = [QUERY_INSTRUCTION + t for t in texts]
    vectors = (
        STATE["model"].encode(texts, normalize_embeddings=True, convert_to_numpy=True).tolist()
        if texts
        else []
    )
    return {"vectors": vectors, **_info()}
