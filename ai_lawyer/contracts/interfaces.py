"""Interfaces (Protocols) every work stream codes against.

They are intentionally small and dependency-free so tests can substitute fakes.
"""
from __future__ import annotations

from typing import Any, Protocol, Sequence, TypeVar, runtime_checkable

from pydantic import BaseModel

from .models import Candidate, DocumentDraft, Evidence, Fact, Source

TModel = TypeVar("TModel", bound=BaseModel)


@runtime_checkable
class LLMAdapter(Protocol):
    def generate_structured(
        self, prompt: str, schema: type[TModel], options: dict[str, Any] | None = None
    ) -> TModel: ...

    def generate_text(self, prompt: str, options: dict[str, Any] | None = None) -> str: ...

    def health_check(self) -> dict[str, Any]: ...


@runtime_checkable
class Embedder(Protocol):
    model_id: str
    dimension: int

    def embed(self, texts: Sequence[str]) -> Any: ...


@runtime_checkable
class Reranker(Protocol):
    model_id: str

    def rerank(self, query: str, candidates: Sequence[dict[str, Any]]) -> list[dict[str, Any]]: ...


@runtime_checkable
class OCRProvider(Protocol):
    name: str

    def extract(self, image_bytes: bytes) -> dict[str, Any]: ...


@runtime_checkable
class CorpusRepository(Protocol):
    def get(self, provision_id: str) -> Any: ...

    def all_provisions(self) -> list[Any]: ...

    def sources(self) -> dict[str, Source]: ...


@runtime_checkable
class Retriever(Protocol):
    def search(self, plan: Any, **kwargs: Any) -> list[Candidate]: ...


@runtime_checkable
class Verifier(Protocol):
    def verify(self, candidates: list[Candidate], *args: Any, **kwargs: Any) -> list[Candidate]: ...


@runtime_checkable
class CaseRepository(Protocol):
    def create_case(self, user_id: str, summary: dict[str, Any]) -> str: ...

    def add_fact(self, fact: Fact) -> str: ...

    def append_event(self, case_id: str, event_type: str, payload: dict[str, Any]) -> int: ...


@runtime_checkable
class EvidenceStore(Protocol):
    def save(self, filename: str, data: bytes, case_id: str | None = None) -> Evidence: ...


@runtime_checkable
class DocumentGenerator(Protocol):
    def generate(self, draft_type: str, **kwargs: Any) -> DocumentDraft: ...


@runtime_checkable
class JevClient(Protocol):
    def is_enabled(self) -> bool: ...

    def advise(self, minimised_state: dict[str, Any]) -> dict[str, Any]: ...
