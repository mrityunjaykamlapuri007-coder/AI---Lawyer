"""HTTP routes.

The routes are deliberately thin: validation and ownership checks live here,
all legal behaviour lives in ``Orchestrator``.  Every client-visible error is
an object ``{error_code, user_safe_message, correlation_id, retryable}``.
"""
from __future__ import annotations

import asyncio
import re
from datetime import date
from typing import TYPE_CHECKING

from fastapi import APIRouter, File, Form, Header, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ai_lawyer.backend.db.repo import Database
from ai_lawyer.backend.services.orchestrator import Orchestrator, Upload
from ai_lawyer.config.settings import Settings
from ai_lawyer.contracts.errors import UserSafeError
from ai_lawyer.contracts.models import Candidate, DocumentDraft
from ai_lawyer.documents.generator import generate_document
from ai_lawyer.legal_engine.source_validity import evaluate_source_validity
from ai_lawyer.legal_rag.corpus_loader import Corpus, startup_summary

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ai_lawyer.legal_rag.index_manager import IndexBundle

router = APIRouter()
_CORRELATION_RE = re.compile(r"[^A-Za-z0-9._:-]")
_CHUNK = 64 * 1024


# ---------------------------------------------------------------------------
# dependencies
# ---------------------------------------------------------------------------
def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _db(request: Request) -> Database:
    return request.app.state.db


def _orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator


def _corpus(request: Request) -> Corpus:
    return request.app.state.corpus


def current_user(request: Request, x_user_id: str | None = Header(default=None, alias="X-User-Id")) -> str:
    """Demo identity from a header.

    This is intentionally *not* authentication.  A public deployment must put a
    real authenticated identity here before accepting private evidence.
    """
    if x_user_id:
        cleaned = _CORRELATION_RE.sub("", x_user_id.strip())[:128]
        if cleaned:
            return cleaned
    return _settings(request).demo_user_id


def _user(request: Request, x_user_id: str | None) -> str:
    return current_user(request, x_user_id)


# ---------------------------------------------------------------------------
# request bodies
# ---------------------------------------------------------------------------
class ConversationOut(BaseModel):
    conversation_id: str
    user_id: str
    created_at: str


class DocumentRequest(BaseModel):
    draft_type: str = Field(pattern="^(support_request|formal_grievance)$")
    as_of_date: date | None = None


class CaseOut(BaseModel):
    case_id: str
    status: str
    summary: dict
    created_at: str
    updated_at: str
    facts: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    drafts: list[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------
@router.get("/health")
def health(request: Request) -> dict:
    corpus: Corpus = _corpus(request)
    index: IndexBundle | None = getattr(request.app.state, "index", None)
    settings = _settings(request)
    db = _db(request)
    database_ok = True
    try:
        with db.connect() as conn:
            conn.execute("SELECT 1").fetchone()
    except Exception:  # noqa: BLE001 - health must never raise
        database_ok = False

    llm = _orchestrator(request).llm
    return {
        "status": "ok" if database_ok else "degraded",
        "app_env": settings.app_env,
        "corpus": {
            "mode": corpus.mode,
            "version": corpus.corpus_version,
            "sources": len(corpus.sources),
            "provisions": len(corpus.provisions),
            "usable": corpus.usable_count,
            "unusable": corpus.unusable_count,
            "fixture_data_not_real_law": corpus.mode == "fixture",
            "warnings": list(corpus.warnings),
        },
        "index": {
            "loaded": index is not None,
            "chunks": len(index.chunk_ids) if index is not None else 0,
            "embedder": (index.manifest.get("embedder_id") if index is not None else ""),
        },
        "llm": {
            "provider": getattr(llm, "provider", "unknown"),
            "offline": getattr(llm, "provider", "") == "fake",
        },
        "database": "ok" if database_ok else "error",
        "startup_summary": startup_summary(corpus),
    }


@router.post("/conversations", response_model=ConversationOut)
def create_conversation(
    request: Request,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> ConversationOut:
    user_id = _user(request, x_user_id)
    conversation = _db(request).create_conversation(user_id)
    return ConversationOut(
        conversation_id=conversation.conversation_id,
        user_id=conversation.user_id,
        created_at=conversation.created_at.isoformat(),
    )


async def _read_uploads(files: list[UploadFile], max_bytes: int) -> list[Upload]:
    uploads: list[Upload] = []
    for item in files:
        total = 0
        chunks: list[bytes] = []
        while True:
            chunk = await item.read(_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise UserSafeError(
                    "file_too_large",
                    "The file is larger than the configured upload limit.",
                    status_code=413,
                )
            chunks.append(chunk)
        uploads.append(
            Upload(filename=item.filename or "upload", data=b"".join(chunks))
        )
    return uploads


@router.post("/conversations/{conversation_id}/messages")
async def post_message(
    conversation_id: str,
    request: Request,
    message: str = Form(""),
    case_id: str | None = Form(None),
    as_of_date: str | None = Form(None),
    files: list[UploadFile] = File(default=[]),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
):
    settings = _settings(request)
    user_id = _user(request, x_user_id)
    parsed_as_of: date | None = None
    if as_of_date:
        try:
            parsed_as_of = date.fromisoformat(as_of_date)
        except ValueError as exc:
            raise UserSafeError(
                "invalid_as_of_date",
                "as_of_date must be an ISO date such as 2026-11-08.",
                status_code=400,
            ) from exc

    uploads = await _read_uploads(files or [], settings.max_upload_bytes)
    orchestrator = _orchestrator(request)

    def _run():
        return orchestrator.handle_message(
            conversation_id=conversation_id,
            user_id=user_id,
            message=message,
            uploads=uploads,
            case_id_hint=case_id,
            as_of_date=parsed_as_of,
        )

    try:
        response = await asyncio.wait_for(
            run_in_threadpool(_run), timeout=settings.request_timeout_s
        )
    except asyncio.TimeoutError as exc:
        raise UserSafeError(
            "request_timeout",
            "That request took too long. Please try again.",
            retryable=True,
            status_code=504,
        ) from exc
    return response.model_dump(mode="json")


@router.get("/cases")
def list_cases(
    request: Request,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> dict:
    user_id = _user(request, x_user_id)
    cases = _db(request).list_cases(user_id)
    return {
        "user_id": user_id,
        "count": len(cases),
        "cases": [
            {
                "case_id": c.case_id,
                "status": c.status,
                "summary": c.summary,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
            }
            for c in cases
        ],
    }


def _owned_case(db: Database, case_id: str, user_id: str):
    case = db.get_case(case_id)
    if case is None or case.user_id != user_id:
        raise UserSafeError("case_not_found", "That case does not exist.", status_code=404)
    return case


@router.get("/cases/{case_id}", response_model=CaseOut)
def get_case(
    case_id: str,
    request: Request,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
) -> CaseOut:
    db = _db(request)
    case = _owned_case(db, case_id, _user(request, x_user_id))
    return CaseOut(
        case_id=case.case_id,
        status=case.status,
        summary=case.summary,
        created_at=case.created_at.isoformat(),
        updated_at=case.updated_at.isoformat(),
        facts=[f.model_dump(mode="json") for f in db.get_facts(case.case_id)],
        events=db.get_events(case.case_id),
        drafts=db.list_drafts(case.case_id),
    )


def _accepted_from_event(
    event: dict, corpus: Corpus, as_of: date | None
) -> list[Candidate]:
    payload = event.get("payload") or {}
    entries = payload.get("accepted_provisions") or []
    if not entries:
        entries = [
            {"provision_id": pid, "role": "primary", "applicability": "unknown"}
            for pid in payload.get("accepted_provision_ids", [])
        ]
    out: list[Candidate] = []
    for entry in entries:
        provision = corpus.get(str(entry.get("provision_id", "")))
        if provision is None:
            continue
        source = corpus.sources.get(provision.source_id)
        validity = entry.get("source_validity")
        if not validity and source is not None:
            validity = evaluate_source_validity(source, as_of)[0]
        out.append(
            Candidate(
                chunk_id=f"{provision.provision_id}::c0",
                provision_id=provision.provision_id,
                source_id=provision.source_id,
                role=entry.get("role") or "primary",
                applicability=entry.get("applicability") or "unknown",
                source_validity=validity or "uncertain",
                citation=provision.citation,
                accepted=True,
            )
        )
    return out


@router.post("/cases/{case_id}/documents", response_model=DocumentDraft)
def create_document(
    case_id: str,
    body: DocumentRequest,
    request: Request,
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
):
    db = _db(request)
    corpus = _corpus(request)
    case = _owned_case(db, case_id, _user(request, x_user_id))
    event = db.latest_event(case.case_id, "assessment_completed")
    if event is None:
        raise UserSafeError(
            "no_assessment",
            "There is no completed assessment for this case yet, so no draft can be prepared.",
            status_code=400,
        )
    accepted = _accepted_from_event(event, corpus, body.as_of_date)
    if not accepted:
        raise UserSafeError(
            "no_accepted_provisions",
            "No verified legal provision supports a document for this case.",
            status_code=400,
        )
    try:
        draft = generate_document(
            draft_type=body.draft_type,
            case_id=case.case_id,
            facts=db.get_facts(case.case_id),
            accepted=accepted,
            corpus=corpus,
        )
    except UserSafeError:
        raise
    db.save_draft(draft)
    return draft
