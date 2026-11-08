"""Pipeline orchestrator: v3 steps 1-16 in one place.

The orchestrator is deliberately synchronous and dependency-injected so the
integration tests can run it with FakeLLM, HashEmbedder and the fixture corpus
without FastAPI, a network, or a model download.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from ai_lawyer.backend.db.repo import Database
from ai_lawyer.backend.services import case_manager
from ai_lawyer.backend.services.context_assembler import (
    assemble_context,
    choose_as_of_date,
    facts_for_prompt,
)
from ai_lawyer.backend.services.evidence_store import EvidenceStore
from ai_lawyer.backend.services.fact_extractor import extract_fact_dicts, mark_conflicts
from ai_lawyer.backend.services.llm_providers import get_llm
from ai_lawyer.backend.services.response_generator import generate_response
from ai_lawyer.backend.services.scope_classifier import classify_scope, keyword_scope
from ai_lawyer.config.settings import Settings, get_settings
from ai_lawyer.contracts.errors import UserSafeError
from ai_lawyer.contracts.ids import today_utc
from ai_lawyer.contracts.models import (
    Assessment,
    EvidenceProcessing,
    Fact,
    LegalSourceOut,
    MessageResponse,
    Outcome,
    RetrievalSummary,
)
from ai_lawyer.documents.generator import generate_document
from ai_lawyer.legal_engine import citation_validator, date_guard, phrase_guard
from ai_lawyer.legal_engine.acceptance import accepted as accepted_candidates
from ai_lawyer.legal_engine.applicability import active_facts
from ai_lawyer.legal_engine.assessment import assess_case
from ai_lawyer.legal_engine.decision_controller import apply_python_decision
from ai_lawyer.legal_engine.reasoning import generate_draft
from ai_lawyer.legal_engine.retry_policy import run_with_verification
from ai_lawyer.legal_rag.corpus_loader import Corpus
from ai_lawyer.legal_rag.query_planner import plan_query
from ai_lawyer.legal_rag.retriever import Retriever, append_retrieval_log

logger = logging.getLogger(__name__)

_CORRECTION_RE = re.compile(r"\b(?:update|correction|correct|actually|sorry)\b", re.IGNORECASE)
_DRAFT_OUTCOMES = {
    Outcome.informal_resolution_recommended: "support_request",
    Outcome.formal_grievance_recommended: "formal_grievance",
    Outcome.formal_legal_proceedings_may_be_justified: "formal_grievance",
}


@dataclass
class Upload:
    filename: str
    data: bytes


class Orchestrator:
    def __init__(
        self,
        *,
        db: Database,
        corpus: Corpus,
        retriever: Retriever,
        llm=None,
        settings: Settings | None = None,
        evidence_store: EvidenceStore | None = None,
    ) -> None:
        self.db = db
        self.corpus = corpus
        self.retriever = retriever
        self.settings = settings or get_settings()
        self.llm = llm or get_llm(self.settings)
        self.evidence_store = evidence_store or EvidenceStore(self.settings)

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------
    def handle_message(
        self,
        *,
        conversation_id: str,
        user_id: str,
        message: str,
        uploads: Iterable[Upload] | None = None,
        case_id_hint: str | None = None,
        as_of_date: date | None = None,
    ) -> MessageResponse:
        message = (message or "").strip()
        if not message:
            raise UserSafeError("empty_message", "Please type a message.", status_code=400)
        if len(message) > self.settings.max_message_chars:
            raise UserSafeError(
                "message_too_long",
                f"Please keep the message under {self.settings.max_message_chars} characters.",
                status_code=413,
            )
        conversation = self.db.get_conversation(conversation_id)
        if conversation is None:
            raise UserSafeError(
                "conversation_not_found",
                "That conversation does not exist. Start a new conversation.",
                status_code=404,
            )
        if conversation.get("user_id") != user_id:
            raise UserSafeError(
                "conversation_forbidden",
                "That conversation belongs to a different user.",
                status_code=403,
            )

        self.db.ensure_user(user_id)
        user_message = self.db.add_message(conversation_id, "user", message)
        reference_year = (as_of_date or today_utc()).year

        # Step 1: scope gate before any retrieval.  A follow-up with no scope
        # terms (e.g. "the 999 rupees arrived") stays in scope when the same
        # conversation already has a refund case.
        scope = classify_scope(message, self.llm)
        if not scope.in_scope:
            deterministic = keyword_scope(message)
            has_case = bool(self.db.cases_for_conversation(conversation_id))
            if has_case and deterministic is None:
                scope = type(scope)(
                    in_scope=True,
                    domain="consumer_refund",
                    reason="follow-up message in an existing refund conversation",
                )
            else:
                assessment = Assessment(
                    outcome=Outcome.out_of_scope,
                    reasons=[scope.reason or "outside the supported scope"],
                    next_steps=[
                        "This assistant cannot help with this issue. Please speak to a qualified lawyer."
                    ],
                )
                text = generate_response(
                    assessment=assessment,
                    draft=None,
                    facts=[],
                    accepted=[],
                    corpus=self.corpus,
                    out_of_scope_domain=scope.domain,
                )
                assistant = self._save_assistant(
                    conversation_id, text, {"status": "out_of_scope"}
                )
                return MessageResponse(
                    conversation_id=conversation_id,
                    message_id=user_message.message_id,
                    assistant_message_id=assistant.message_id,
                    case_id=None,
                    processing_status="out_of_scope",
                    assistant_message=text,
                    assessment=assessment,
                )

        evidence_processing: list[EvidenceProcessing] = []
        evidence_notes: list[str] = []
        evidence_facts, evidence_ids = self._process_uploads(
            uploads or [], evidence_processing, evidence_notes, reference_year
        )

        message_facts = extract_fact_dicts(
            message,
            source_type="user_message",
            source_id="user",
            llm=self.llm,
            default_year=reference_year,
        )
        all_fact_dicts = mark_conflicts(message_facts + evidence_facts)

        resolution = case_manager.resolve_case(
            self.db,
            user_id=user_id,
            conversation_id=conversation_id,
            facts=all_fact_dicts,
            message=message,
            case_id_hint=case_id_hint,
        )
        if resolution.clarification or resolution.case_id is None:
            clarification = resolution.clarification or (
                "Please share the order id so I can keep this case separate."
            )
            assessment = Assessment(
                outcome=Outcome.needs_more_information,
                reasons=[clarification],
                missing_information=[clarification],
                next_steps=["Send one message per order, with the order id."],
            )
            text = generate_response(
                assessment=assessment,
                draft=None,
                facts=[],
                accepted=[],
                corpus=self.corpus,
                clarification=clarification,
            )
            assistant = self._save_assistant(
                conversation_id, text, {"status": "needs_clarification", "split": resolution.split_required}
            )
            return MessageResponse(
                conversation_id=conversation_id,
                message_id=user_message.message_id,
                assistant_message_id=assistant.message_id,
                case_id=None,
                processing_status="needs_clarification",
                assistant_message=text,
                assessment=assessment,
                missing_information=[clarification],
            )

        case_id = resolution.case_id
        for evidence_id in evidence_ids:
            self.db.attach_evidence_to_case(evidence_id, case_id)
        case_manager.persist_facts(
            self.db,
            case_id,
            all_fact_dicts,
            correction=bool(_CORRECTION_RE.search(message)),
        )
        facts = self.db.get_facts(case_id)
        case_manager.update_resolution_status(self.db, case_id, facts)
        case = self.db.get_case(case_id)
        case_summary = case.summary if case else {}

        # Steps 8-10: retrieval with bounded, distinct-query retries.
        as_of, basis = choose_as_of_date(facts, as_of_date)
        plan = plan_query(message, facts, case_summary)
        verification = run_with_verification(
            retriever=self.retriever,
            corpus=self.corpus,
            facts=facts,
            as_of_date=as_of,
            plan=plan,
            case_summary=f"{message}\n{case_summary}",
            llm=self.llm,
            settings=self.settings,
            conversation_id=conversation_id,
        )
        accepted = accepted_candidates(verification.candidates)
        for run in verification.runs:
            append_retrieval_log(run, self.settings.db_path.parent / "retrieval_log.jsonl")

        context = assemble_context(
            case_id=case_id,
            case_summary=case_summary,
            facts=facts,
            message=message,
            as_of_date=as_of,
            as_of_basis=basis,
        )

        draft = None
        blocked: list[dict[str, Any]] = []
        if accepted:
            draft = generate_draft(
                context,
                accepted,
                self.corpus,
                self.llm,
                facts,
                missing_facts=[
                    f.fact_type for f in active_facts(facts) if f.normalised_value is None
                ],
                settings=self.settings,
            )
            draft = self._apply_guards(draft, accepted, facts, blocked)

        assessment = assess_case(
            in_scope=True,
            accepted_candidates=verification.candidates,
            corpus=self.corpus,
            facts=facts,
            as_of_date=as_of,
            user_text=message,
            llm_proposed_outcome=draft.proposed_outcome.value if draft else None,
        )
        assessment = apply_python_decision(assessment, draft)

        document = None
        draft_type = _DRAFT_OUTCOMES.get(assessment.outcome)
        if accepted and draft_type:
            try:
                document = generate_document(
                    draft_type=draft_type,
                    case_id=case_id,
                    facts=facts,
                    accepted=accepted,
                    corpus=self.corpus,
                )
                self.db.save_draft(document)
            except UserSafeError as exc:
                logger.info("document generation blocked: %s", exc.error_code)
                document = None

        text = generate_response(
            assessment=assessment,
            draft=draft,
            facts=facts,
            accepted=accepted,
            corpus=self.corpus,
            evidence_notes=evidence_notes,
            document_offered=document.draft_type if document else None,
            as_of_date=as_of,
        )

        processing_status = "completed"
        if assessment.outcome == Outcome.needs_more_information:
            processing_status = "needs_clarification"
        elif any(item.status in {"partial", "failed"} for item in evidence_processing):
            processing_status = "partial"

        verification_payload = {
            "overall": "unverified" if not accepted else ("partially_verified" if blocked else "verified"),
            "blocked_claims": blocked,
            "note": "deterministic citation/date/phrase guards only; claim-level entailment is DESIGN_ONLY",
        }
        sources = self._sources(accepted)
        assistant = self._save_assistant(
            conversation_id,
            text,
            {
                "status": processing_status,
                "outcome": assessment.outcome.value,
                "case_id": case_id,
            },
        )
        self.db.append_event(
            case_id,
            "assessment_completed",
            {
                "outcome": assessment.outcome.value,
                "accepted_provision_ids": [c.provision_id for c in accepted],
                "accepted_provisions": [
                    {
                        "provision_id": c.provision_id,
                        "role": c.role,
                        "applicability": c.applicability,
                        "source_validity": c.source_validity,
                    }
                    for c in accepted
                ],
                "retry_count": verification.retry_count,
                "blocked_claims": len(blocked),
            },
        )

        return MessageResponse(
            conversation_id=conversation_id,
            message_id=user_message.message_id,
            assistant_message_id=assistant.message_id,
            case_id=case_id,
            processing_status=processing_status,  # type: ignore[arg-type]
            assistant_message=text,
            case_summary=case_summary,
            extracted_facts=facts,
            evidence_processing=evidence_processing,
            legal_sources=sources,
            retrieval_candidates=verification.candidates,
            retrieval_summary=RetrievalSummary(
                corpus_version=self.corpus.corpus_version,
                candidate_count=len(verification.candidates),
                accepted_count=len(accepted),
                rejected_count=verification.rejected_count,
                retry_count=verification.retry_count,
            ),
            verification=verification_payload,
            assessment=assessment,
            missing_information=list(assessment.missing_information),
            next_steps=list(assessment.next_steps),
            document_draft=document,
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _process_uploads(
        self,
        uploads: Iterable[Upload],
        processing: list[EvidenceProcessing],
        notes: list[str],
        default_year: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        facts: list[dict[str, Any]] = []
        evidence_ids: list[str] = []
        for upload in uploads:
            try:
                evidence = self.evidence_store.save(upload.filename, upload.data)
                self.db.save_evidence(evidence)
                evidence_ids.append(evidence.evidence_id)
                processing.append(
                    EvidenceProcessing(
                        filename=evidence.original_filename,
                        status=evidence.extraction_status,
                        error_code=evidence.error_code,
                        methods=sorted({p.method for p in evidence.pages if p.text}),
                    )
                )
                notes.append(
                    f"{evidence.original_filename}: {evidence.extraction_status}"
                    + (f" ({evidence.error_code})" if evidence.error_code else "")
                )
                for page in evidence.pages:
                    if not page.text:
                        continue
                    facts.extend(
                        extract_fact_dicts(
                            page.text,
                            source_type="evidence",
                            source_id=evidence.evidence_id,
                            evidence_id=evidence.evidence_id,
                            page_number=page.page_number,
                            llm=None,
                            default_year=default_year,
                        )
                    )
            except UserSafeError as exc:
                processing.append(
                    EvidenceProcessing(
                        filename=upload.filename,
                        status="failed",
                        error_code=exc.error_code,
                    )
                )
                notes.append(f"{upload.filename}: rejected — {exc.user_safe_message}")
            except Exception as exc:  # noqa: BLE001 - one bad file must not stop the rest
                logger.warning("evidence processing failed: %s", type(exc).__name__)
                processing.append(
                    EvidenceProcessing(
                        filename=upload.filename,
                        status="failed",
                        error_code="evidence_processing_failed",
                    )
                )
                notes.append(f"{upload.filename}: could not be processed.")
        return facts, evidence_ids

    def _apply_guards(self, draft, accepted, facts, blocked: list[dict[str, Any]]):
        phrase = phrase_guard.sanitize_draft(draft)
        draft = phrase.draft
        citation = citation_validator.validate_draft(draft, accepted, self.corpus)
        draft = citation.draft
        blocked.extend(citation.blocked_claims)
        numbers: set[int] = set()
        dates: set[str] = set()
        for fact in active_facts(facts):
            if fact.fact_type == "merchant_promised_timeline_days" and fact.normalised_value is not None:
                try:
                    numbers.add(int(fact.normalised_value))
                except (TypeError, ValueError):
                    pass
            if fact.fact_type.endswith("_date"):
                dates.add(fact.raw_value)
                if fact.normalised_value:
                    dates.add(str(fact.normalised_value))
        dated = date_guard.validate_dates(draft, numbers, dates)
        blocked.extend(dated.blocked_claims)
        return dated.draft

    def _sources(self, accepted) -> list[LegalSourceOut]:
        out: list[LegalSourceOut] = []
        for cand in accepted:
            provision = self.corpus.get(cand.provision_id)
            if provision is None:
                continue
            source = self.corpus.sources.get(provision.source_id)
            out.append(
                LegalSourceOut(
                    provision_id=provision.provision_id,
                    citation=provision.citation,
                    excerpt=provision.original_text[:600],
                    role=cand.role,
                    applicability=cand.applicability,
                    source_validity=cand.source_validity,
                    official_url=(source.official_url if source else "") or "",
                )
            )
        return out

    def _save_assistant(self, conversation_id: str, text: str, payload: dict[str, Any]):
        return self.db.add_message(conversation_id, "assistant", text, payload)
