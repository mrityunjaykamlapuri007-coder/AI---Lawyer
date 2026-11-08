"""Stage 2: remote embedder client, embed server, index integrity, check_remote, notebook."""
from __future__ import annotations

import ast
import importlib.util
import json
import math
from pathlib import Path

import httpx
import numpy as np
import pytest

from ai_lawyer.config.settings import Settings
from ai_lawyer.contracts.errors import IndexStale
from ai_lawyer.legal_rag.embedders import get_embedder
from ai_lawyer.legal_rag.index_manager import build_index, check_embedder_matches, load_index
from ai_lawyer.legal_rag.remote_embedder import EmbedderUnavailable, RemoteHTTPEmbedder
from ai_lawyer.tools import check_remote

ROOT = Path(__file__).resolve().parents[3]
KEY = "test-key-not-a-secret"
INFO = {"model_id": "BAAI/test-bge", "dimension": 3, "model_hash": "h1", "device": "cpu"}


def _unit(rows: int) -> list[list[float]]:
    return [[1.0, 0.0, 0.0] for _ in range(rows)]


def _transport(calls: list, *, vectors=_unit, status=200, info=INFO, embed_hash="h1"):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.headers.get("authorization") != f"Bearer {KEY}":
            return httpx.Response(401)
        if status != 200:
            return httpx.Response(status)
        if request.url.path == "/info":
            return httpx.Response(200, json=info)
        body = json.loads(request.content)
        return httpx.Response(200, json={**info, "model_hash": embed_hash,
                                         "vectors": vectors(len(body["texts"]))})
    return httpx.MockTransport(handler)


def _client(calls, **kw) -> RemoteHTTPEmbedder:
    return RemoteHTTPEmbedder("https://embed.example", KEY, batch_size=2, retries=2,
                              transport=_transport(calls, **{k: v for k, v in kw.items()}))


# --- client -------------------------------------------------------------------
def test_batches_and_returns_normalised_vectors():
    calls: list = []
    vectors = _client(calls).embed(["a", "b", "c", "d", "e"])

    assert vectors.shape == (5, 3)
    embed_calls = [c for c in calls if c.url.path == "/embed"]
    assert [len(json.loads(c.content)["texts"]) for c in embed_calls] == [2, 2, 1]
    assert all(json.loads(c.content)["kind"] == "passage" for c in embed_calls)


def test_query_uses_query_kind():
    calls: list = []
    _client(calls).embed_query("refund?")
    assert json.loads([c for c in calls if c.url.path == "/embed"][0].content)["kind"] == "query"


def test_unnormalised_vectors_are_refused():
    with pytest.raises(EmbedderUnavailable, match="not L2-normalised"):
        _client([], vectors=lambda n: [[2.0, 0.0, 0.0]] * n).embed(["a"])


def test_dimension_mismatch_is_refused():
    with pytest.raises(EmbedderUnavailable, match="shape"):
        _client([], vectors=lambda n: [[1.0, 0.0]] * n).embed(["a"])


def test_model_hash_change_mid_session_is_refused():
    with pytest.raises(EmbedderUnavailable, match="model changed"):
        _client([], embed_hash="h2").embed(["a"])


def test_bad_key_is_a_clear_error_without_retry():
    calls: list = []
    embedder = RemoteHTTPEmbedder("https://embed.example", "wrong", retries=2, transport=_transport(calls))
    with pytest.raises(EmbedderUnavailable, match="rejected the key"):
        embedder.embed(["a"])
    assert len(calls) == 1


def test_timeout_retries_twice_then_raises(monkeypatch):
    monkeypatch.setattr("ai_lawyer.legal_rag.remote_embedder.time.sleep", lambda s: None)
    calls: list = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectTimeout("slow")

    embedder = RemoteHTTPEmbedder("https://embed.example", KEY, retries=2, transport=httpx.MockTransport(handler))
    with pytest.raises(EmbedderUnavailable, match="unreachable after 3 attempts"):
        embedder.embed(["a"])
    assert len(calls) == 3


def test_factory_builds_remote_embedder_and_needs_config():
    built = get_embedder(Settings(embedding_backend="remote_http", embedder_base_url="https://e.example",
                                  embedder_api_key=KEY))
    assert isinstance(built, RemoteHTTPEmbedder)
    with pytest.raises(Exception):
        get_embedder(Settings(embedding_backend="remote_http"))


# --- index integrity ------------------------------------------------------------
class _Hashed:
    def __init__(self, model_hash):
        from ai_lawyer.tests.fakes import HashEmbedder
        self._inner = HashEmbedder()
        self.model_id = self._inner.model_id
        self.model_hash = model_hash

    def embed(self, texts):
        return self._inner.embed(texts)


def test_index_refuses_a_different_embedder_hash(settings, tmp_path):
    from ai_lawyer.legal_rag.corpus_loader import load_corpus

    corpus = load_corpus(settings=settings)
    out = tmp_path / "index"
    build_index(corpus, _Hashed("h1"), out_dir=out)
    assert json.loads((out / "index_meta.json").read_text())["embedder_model_hash"] == "h1"

    load_index(corpus, embedder=_Hashed("h1"), index_dir=out, settings=settings)
    with pytest.raises(IndexStale) as stale:
        load_index(corpus, embedder=_Hashed("h2"), index_dir=out, settings=settings)
    assert "model_hash" in stale.value.details["detail"]


def test_index_refuses_a_changed_corpus(settings, tmp_path):
    from ai_lawyer.legal_rag.corpus_loader import load_corpus

    corpus = load_corpus(settings=settings)
    out = tmp_path / "index"
    build_index(corpus, _Hashed("h1"), out_dir=out)
    corpus.corpus_version = "changed"
    with pytest.raises(IndexStale) as stale:
        load_index(corpus, embedder=_Hashed("h1"), index_dir=out, settings=settings)
    assert "corpus_version" in stale.value.details["detail"]


def test_embedder_id_mismatch_is_refused():
    with pytest.raises(IndexStale) as stale:
        check_embedder_matches({"embedder_id": "a", "embedder_model_hash": None},
                               type("E", (), {"model_id": "b"})())
    assert "embedder" in stale.value.details["detail"]


# --- embed server (no model download: a fake model is injected) --------------------
def _load_server():
    spec = importlib.util.spec_from_file_location("embed_server", ROOT / "kaggle" / "embed_server.py")
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules["embed_server"] = module
    spec.loader.exec_module(module)
    return module


class _FakeModel:
    def __init__(self):
        self.seen = []

    def encode(self, texts, normalize_embeddings, convert_to_numpy):
        assert normalize_embeddings
        self.seen.extend(texts)
        return np.array([[0.6, 0.8, 0.0] for _ in texts])


def test_embed_server_auth_query_instruction_and_limits():
    from fastapi.testclient import TestClient

    server = _load_server()
    model = _FakeModel()
    server.STATE.update(api_key=KEY, model=model, dimension=3, model_hash="h1")
    client = TestClient(server.app)  # no context manager: lifespan (model load) is skipped
    auth = {"Authorization": f"Bearer {KEY}"}

    assert client.get("/info").status_code == 401
    assert client.get("/info", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/info", headers=auth).json()["model_hash"] == "h1"

    body = client.post("/embed", headers=auth, json={"texts": ["refund"], "kind": "query"}).json()
    assert math.isclose(sum(x * x for x in body["vectors"][0]), 1.0)
    assert model.seen[-1].startswith(server.QUERY_INSTRUCTION)
    client.post("/embed", headers=auth, json={"texts": ["law text"], "kind": "passage"})
    assert model.seen[-1] == "law text"
    too_many = client.post("/embed", headers=auth, json={"texts": ["x"] * (server.MAX_TEXTS + 1)})
    assert too_many.status_code == 413
    server.STATE.clear()


def test_embed_server_refuses_to_start_without_key(monkeypatch):
    monkeypatch.delenv("EMBED_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="EMBED_API_KEY"):
        _load_server()._api_key()


# --- check_remote -----------------------------------------------------------------
def test_check_remote_unconfigured_fails():
    lines: list[str] = []
    assert check_remote.run(Settings(), out=lines.append) == 2
    assert all("FAIL" in line for line in lines)


def test_check_remote_passes_and_never_prints_key_or_path():
    def handler(request):
        if request.headers.get("authorization") != f"Bearer {KEY}":
            return httpx.Response(401)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "refund-llm"}]})
        if request.url.path == "/info":
            return httpx.Response(200, json=INFO)
        return httpx.Response(200, json={**INFO, "vectors": [[1.0, 0.0, 0.0]]})

    settings = Settings(
        llm_provider="openai_compatible", llm_base_url="https://llm.example/v1/secretpath",
        llm_api_key=KEY, llm_model="refund-llm", embedding_backend="remote_http",
        embedder_base_url="https://embed.example/secretpath", embedder_api_key=KEY,
    )
    lines: list[str] = []
    code = check_remote.run(settings, transport=httpx.MockTransport(handler), out=lines.append)

    text = "\n".join(lines)
    assert code == 0, text
    assert KEY not in text and "secretpath" not in text
    assert "llm.example" in text and "h1" in text


# --- notebook ---------------------------------------------------------------------
def test_serve_all_notebook_parses_inlines_server_and_never_prints_secrets():
    nb = json.loads((ROOT / "kaggle" / "serve_all.ipynb").read_text(encoding="utf-8"))
    code = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    for source in code:
        ast.parse(source)
    joined = "\n".join(code)
    server_source = (ROOT / "kaggle" / "embed_server.py").read_text(encoding="utf-8")
    assert repr(server_source) in joined  # notebook cannot drift from the tested file
    leaks = []
    for source in code:
        for node in ast.walk(ast.parse(source)):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print"):
                continue
            guarded = {
                id(n)
                for call in ast.walk(node)
                if isinstance(call, ast.Call) and getattr(call.func, "id", None) == "bool"
                for n in ast.walk(call)
            }
            for n in ast.walk(node):
                if isinstance(n, ast.Name) and n.id in {"API_KEY", "HF_TOKEN"} and id(n) not in guarded:
                    leaks.append(ast.unparse(node))
    assert leaks == []


# --- hosted OpenAI-compatible embeddings (interview route without Kaggle) -----------
def _openai_transport(calls: list, *, vector=(3.0, 4.0, 0.0), count_override=None):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.headers.get("authorization") != f"Bearer {KEY}":
            return httpx.Response(401)
        body = json.loads(request.content)
        n = count_override if count_override is not None else len(body["input"])
        return httpx.Response(200, json={"data": [{"index": i, "embedding": list(vector)} for i in range(n)]})
    return httpx.MockTransport(handler)


def test_openai_compatible_embedder_normalises_fingerprints_and_prefixes_queries():
    from ai_lawyer.legal_rag.remote_embedder import OpenAICompatibleEmbedder

    calls: list = []
    embedder = OpenAICompatibleEmbedder("https://api.example/v1", KEY, "bge-test", query_prefix="Q: ",
                                        batch_size=2, transport=_openai_transport(calls))
    passages = embedder.embed(["a", "b", "c"])
    query = embedder.embed_query("refund?")

    assert passages.shape == (3, 3)
    assert np.allclose(np.linalg.norm(passages, axis=1), 1.0)
    assert embedder.model_id == "bge-test" and len(embedder.model_hash) == 32
    assert json.loads(calls[-1].content)["input"] == ["Q: refund?"]
    assert all(json.loads(c.content)["model"] == "bge-test" for c in calls)
    assert query.shape == (1, 3)


def test_openai_compatible_embedder_hash_changes_with_model_output():
    from ai_lawyer.legal_rag.remote_embedder import OpenAICompatibleEmbedder

    a = OpenAICompatibleEmbedder("https://api.example/v1", KEY, "m", transport=_openai_transport([]))
    b = OpenAICompatibleEmbedder("https://api.example/v1", KEY, "m",
                                 transport=_openai_transport([], vector=(0.0, 1.0, 0.0)))
    assert a.model_hash != b.model_hash


def test_openai_compatible_embedder_refuses_wrong_count_and_bad_key():
    from ai_lawyer.legal_rag.remote_embedder import OpenAICompatibleEmbedder

    short = OpenAICompatibleEmbedder("https://api.example/v1", KEY, "m",
                                     transport=_openai_transport([], count_override=1))
    with pytest.raises(EmbedderUnavailable, match="returned 1 vectors"):
        short.embed(["a", "b"])
    wrong = OpenAICompatibleEmbedder("https://api.example/v1", "bad", "m", transport=_openai_transport([]))
    with pytest.raises(EmbedderUnavailable, match="rejected the key"):
        wrong.embed(["a"])
