"""FastAPI application entry point.

Run with:
    uvicorn ai_lawyer.backend.main:app --reload

The lifespan loads the corpus, the search index, the database schema and the
LLM adapter exactly once.  Health checks never expose keys, paths or prompts.
"""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ai_lawyer.backend.api.routes import router
from ai_lawyer.backend.db.migrate import migrate
from ai_lawyer.backend.db.repo import Database
from ai_lawyer.backend.services.llm_providers import get_llm
from ai_lawyer.backend.services.orchestrator import Orchestrator
from ai_lawyer.config.settings import Settings, get_settings
from ai_lawyer.contracts.errors import UserSafeError
from ai_lawyer.contracts.ids import new_id
from ai_lawyer.legal_rag.corpus_loader import load_corpus, startup_summary
from ai_lawyer.legal_rag.embedders import get_embedder
from ai_lawyer.legal_rag.index_manager import build_or_load
from ai_lawyer.legal_rag.retriever import Retriever

logger = logging.getLogger(__name__)
_SAFE_CORRELATION = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _correlation_id(request: Request) -> str:
    supplied = request.headers.get("X-Correlation-Id", "")
    if _SAFE_CORRELATION.match(supplied or ""):
        return supplied
    return new_id("req_")


def _error_payload(request: Request, error_code: str, message: str, retryable: bool) -> dict:
    return {
        "error_code": error_code,
        "user_safe_message": message,
        "correlation_id": getattr(request.state, "correlation_id", ""),
        "retryable": retryable,
    }


def create_app(
    *,
    settings: Settings | None = None,
    orchestrator: Orchestrator | None = None,
) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = resolved
        if orchestrator is not None:
            app.state.orchestrator = orchestrator
            app.state.db = orchestrator.db
            app.state.corpus = orchestrator.corpus
            app.state.index = getattr(orchestrator.retriever, "index", None)
        else:
            corpus = load_corpus(settings=resolved)
            logger.info(startup_summary(corpus))
            index = build_or_load(corpus, resolved, embedder=get_embedder(resolved))
            migrate(resolved.db_path)
            db = Database(resolved.db_path)
            retriever = Retriever(index, corpus, resolved)
            app.state.corpus = corpus
            app.state.index = index
            app.state.db = db
            app.state.orchestrator = Orchestrator(
                db=db,
                corpus=corpus,
                retriever=retriever,
                llm=get_llm(resolved),
                settings=resolved,
            )
        app.state.fixture_mode = app.state.corpus.mode == "fixture"
        logger.info(
            "startup complete: corpus=%s index_loaded=%s fixture=%s",
            app.state.corpus.corpus_version,
            app.state.index is not None,
            app.state.fixture_mode,
        )
        yield

    app = FastAPI(
        title="AI Consumer Refund Dispute Assistant",
        version="0.1.0",
        description=(
            "Local demo for unresolved e-commerce refund disputes in India. "
            "Not legal advice. Fixture mode uses synthetic law, not real law."
        ),
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.allowed_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-User-Id", "X-Correlation-Id"],
    )

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):
        correlation_id = _correlation_id(request)
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = correlation_id
        return response

    @app.exception_handler(UserSafeError)
    async def user_safe_error_handler(request: Request, exc: UserSafeError):
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload(request, exc.error_code, exc.user_safe_message, exc.retryable),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=_error_payload(
                request,
                "invalid_request",
                "The request was not valid. Check the message, case id and file fields.",
                False,
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        # Log the type only: prompts, evidence and user text must not reach logs.
        logger.exception(
            "unhandled error correlation_id=%s type=%s",
            getattr(request.state, "correlation_id", ""),
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content=_error_payload(
                request,
                "internal_error",
                "Something went wrong. Please try again.",
                True,
            ),
        )

    app.include_router(router)
    return app


app = create_app()
