"""Single typed settings object, loaded once from environment / .env.

No model is loaded here.  All paths are resolved relative to the project root so
that commands work from any working directory.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "local"
    corpus_mode: Literal["real", "fixture"] = "fixture"
    # Which verification level this deployment claims.  ``machine`` is the
    # default for the submission: the corpus was checked by the automated
    # pipeline, not by a lawyer or a human.  The banner says which is in force.
    corpus_trust_level: Literal["machine", "human"] = "machine"
    corpus_dir: str = "ai_lawyer/legal_corpus"
    vectorstore_dir: str = "ai_lawyer/vectorstore"
    sqlite_path: str = "ai_lawyer/data/lawyer.db"
    evidence_dir: str = "ai_lawyer/data/evidence"

    # ``remote_http`` = the BGE service in the Kaggle notebook (kaggle/embed_server.py).
    # ``hash`` is a test embedder and is refused in real mode.
    # ``openai_compatible`` = any hosted ``/embeddings`` API (model = EMBEDDING_MODEL_ID).
    embedding_backend: Literal["hash", "sentence_transformers", "remote_http", "openai_compatible"] = "hash"
    embedding_model_id: str = "BAAI/bge-large-en-v1.5"
    embedder_query_prefix: str = ""
    embedder_base_url: str = ""
    embedder_api_key: str = ""
    embedder_timeout_s: int = 60
    embedder_batch_size: int = 32

    reranker_enabled: bool = False
    reranker_model_id: str = "BAAI/bge-reranker-large"

    rrf_k: int = 60
    dense_top_k: int = 20
    sparse_top_k: int = 20
    fused_top_k: int = 10
    final_top_k: int = 5
    max_retrieval_retries: int = 2
    relevance_min_grade: int = 2
    max_chunk_chars: int = 1800

    # Reference-stack parity stages.  Both are off by default so the fixture
    # evaluation stays reproducible; enable to measure their effect.
    boost_enabled: bool = False
    exact_reference_boost: float = 0.5
    qualifier_tiebreak: bool = True
    compression_enabled: bool = False
    compression_max_chars: int = 1200

    llm_provider: Literal["fake", "openai_compatible", "hf_local"] = "fake"
    llm_model: str = ""
    llm_model_id: str = ""
    llm_model_path: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_temperature: float = 0.0
    llm_max_tokens: int = 1500
    llm_timeout_s: int = 120
    # JSON-schema constrained decoding.  On by default for the 8B Kaggle model,
    # which is weak at strict JSON; the retry-then-reject rule stays on top.
    llm_json_schema_mode: bool = True
    llm_max_retries_http: int = 2
    llm_call_log: str = "ai_lawyer/evaluation/results/llm_calls.jsonl"
    llm_failure_log: str = "ai_lawyer/evaluation/results/llm_failures.jsonl"

    max_upload_mb: int = 5
    max_message_chars: int = 4000
    request_timeout_s: int = 120
    allowed_origins: str = "http://localhost:8501"
    log_level: str = "INFO"
    demo_user_id: str = "demo-user"

    snapshot_every_n_events: int = 20

    @field_validator(
        "corpus_dir",
        "vectorstore_dir",
        "sqlite_path",
        "evidence_dir",
        "llm_call_log",
        "llm_failure_log",
        mode="before",
    )
    @classmethod
    def _resolve_path(cls, value: str) -> str:
        p = Path(value)
        return str(p if p.is_absolute() else (PROJECT_ROOT / p).resolve())

    @property
    def allowed_origins_list(self) -> list[str]:
        return [x.strip() for x in self.allowed_origins.split(",") if x.strip()]

    @property
    def corpus_path(self) -> Path:
        return Path(self.corpus_dir)

    @property
    def vectorstore_path(self) -> Path:
        return Path(self.vectorstore_dir)

    @property
    def db_path(self) -> Path:
        return Path(self.sqlite_path)

    @property
    def evidence_path(self) -> Path:
        return Path(self.evidence_dir)

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def llm_model_name(self) -> str:
        """``LLM_MODEL`` wins; ``LLM_MODEL_ID`` stays for older configs."""
        return self.llm_model or self.llm_model_id


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
