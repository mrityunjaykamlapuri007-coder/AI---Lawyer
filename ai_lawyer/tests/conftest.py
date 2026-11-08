"""Shared offline fixtures: temp corpus copy, HashEmbedder, FakeLLM, SQLite."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ai_lawyer.backend.db.migrate import migrate
from ai_lawyer.backend.db.repo import Database
from ai_lawyer.backend.services.evidence_store import EvidenceStore
from ai_lawyer.backend.services.orchestrator import Orchestrator
from ai_lawyer.config.settings import PROJECT_ROOT, Settings
from ai_lawyer.tests.fakes import FakeLLM, HashEmbedder
from ai_lawyer.legal_rag.corpus_loader import load_corpus
from ai_lawyer.legal_rag.index_manager import build_index
from ai_lawyer.legal_rag.retriever import Retriever

FIXTURE_DIR = PROJECT_ROOT / "ai_lawyer" / "legal_corpus" / "fixture"

# Unit tests never touch the network, even when a developer's .env points at
# live Kaggle services.  Environment variables override .env values.
_OFFLINE_ENV = {
    "CORPUS_MODE": "fixture",
    "LLM_PROVIDER": "fake",
    "LLM_BASE_URL": "",
    "LLM_API_KEY": "",
    "LLM_MODEL": "",
    "EMBEDDING_BACKEND": "hash",
    "EMBEDDER_BASE_URL": "",
    "EMBEDDER_API_KEY": "",
}


@pytest.fixture(autouse=True)
def _offline_settings(monkeypatch):
    from ai_lawyer.config.settings import get_settings

    for key, value in _OFFLINE_ENV.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    corpus_dir = tmp_path / "corpus"
    (corpus_dir / "fixture").mkdir(parents=True)
    for name in ("sources.json", "provisions.json"):
        shutil.copy2(FIXTURE_DIR / name, corpus_dir / "fixture" / name)
    return Settings(
        app_env="test",
        corpus_mode="fixture",
        corpus_dir=str(corpus_dir),
        vectorstore_dir=str(tmp_path / "vectorstore"),
        sqlite_path=str(tmp_path / "lawyer.db"),
        evidence_dir=str(tmp_path / "evidence"),
        embedding_backend="hash",
        llm_provider="fake",
        reranker_enabled=False,
        max_upload_mb=1,
        ocr_enabled=False,  # tests inject a fake OCR where they need one
        max_message_chars=4000,
        request_timeout_s=60,
        allowed_origins="http://localhost:8501",
    )


@pytest.fixture()
def corpus(settings: Settings):
    return load_corpus(settings=settings)


@pytest.fixture()
def index_bundle(corpus, settings: Settings):
    return build_index(
        corpus,
        HashEmbedder(),
        out_dir=settings.vectorstore_path,
        max_chunk_chars=settings.max_chunk_chars,
    )


@pytest.fixture()
def retriever(index_bundle, corpus, settings: Settings) -> Retriever:
    return Retriever(index_bundle, corpus, settings)


@pytest.fixture()
def db(settings: Settings) -> Database:
    migrate(settings.db_path)
    return Database(settings.db_path)


@pytest.fixture()
def orchestrator(db, corpus, retriever, settings: Settings) -> Orchestrator:
    return Orchestrator(
        db=db,
        corpus=corpus,
        retriever=retriever,
        llm=FakeLLM(),
        settings=settings,
        evidence_store=EvidenceStore(settings),
    )


@pytest.fixture()
def conversation(db, settings: Settings):
    return db.create_conversation(settings.demo_user_id)
