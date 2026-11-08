"""All Pydantic models used across the application.

Money is stored as integer minor units plus an ISO currency code.  Timestamps
are UTC ISO-8601 datetimes.  IDs are UUID4 strings unless a model says
otherwise (provision ids are deterministic, chunk ids are derived).
"""
from __future__ import annotations

from datetime import date as date_cls, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .ids import new_id, utc_now


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=False)


# ---------------------------------------------------------------------------
# Enums / literals
# ---------------------------------------------------------------------------
class Outcome(str, Enum):
    no_legal_action_currently_required = "no_legal_action_currently_required"
    informal_resolution_recommended = "informal_resolution_recommended"
    formal_grievance_recommended = "formal_grievance_recommended"
    formal_legal_proceedings_may_be_justified = "formal_legal_proceedings_may_be_justified"
    needs_more_information = "needs_more_information"
    out_of_scope = "out_of_scope"


SourceValidity = Literal["current_for_date", "superseded", "not_yet_effective", "uncertain"]
Applicability = Literal["applicable", "not_applicable", "unknown"]
Role = Literal["primary", "supporting", "background", "mandatory_qualifier", "rejected"]
FactStatus = Literal["user_reported", "document_supported", "disputed", "unknown"]
FactSourceType = Literal["user_message", "evidence"]
ConditionOperator = Literal["exists", "equals", "in", "date_before", "date_after", "manual"]
DraftType = Literal[
    "support_request", "formal_grievance", "nch_summary", "consumer_commission_draft"
]
VerificationOverall = Literal[
    "verified", "partially_verified", "unverified", "clarification_required"
]

ALLOWED_FACT_TYPES: tuple[str, ...] = (
    "merchant_name",
    "platform_name",
    "order_id",
    "transaction_id",
    "purchase_date",
    "cancellation_date",
    "return_requested_date",
    "return_approved_date",
    "pickup_date",
    "refund_initiated_date",
    "refund_amount",
    "payment_method",
    "refund_status",
    "merchant_promised_timeline_days",
    "support_contact_made",
    "support_contact_date",
    "support_response",
    "grievance_officer_contacted",
    "grievance_contact_date",
    "bank_credit_confirmed",
)


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------
class Source(StrictModel):
    source_id: str
    title: str
    source_type: Literal["act", "rule", "notification", "regulation", "official_guidance"]
    publisher: str
    official_url: str = ""
    published_date: date_cls | None = None
    retrieved_at: date_cls
    document_sha256: str | None = None
    review_status: Literal["human_verified", "unverified"]
    version_label: str
    effective_from: date_cls | None = None
    effective_to: date_cls | None = None
    version_status: Literal["current", "superseded", "future", "uncertain"]
    # Provenance.  Required for every human_verified source in real mode; the
    # acceptance gate in legal_rag.corpus_acceptance refuses to start without
    # it, because a verified flag with no named reviewer is not evidence.
    reviewed_by: str | None = None
    reviewed_at: date_cls | None = None
    notes: str = ""


class Condition(StrictModel):
    condition_id: str
    description: str
    fact_type: str
    operator: ConditionOperator
    expected_value: Any = None
    human_review_status: Literal["reviewed", "unreviewed"] = "unreviewed"


class Provision(StrictModel):
    provision_id: str
    source_id: str
    citation: str
    hierarchy_type: Literal[
        "section", "rule", "subsection", "clause", "proviso", "explanation", "definition"
    ]
    parent_provision_id: str | None = None
    original_text: str
    search_text: str = ""
    provisos: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    definitions_used: list[str] = Field(default_factory=list)
    cross_references: list[str] = Field(default_factory=list)
    mandatory_context: list[str] = Field(default_factory=list)
    conditions: list[Condition] = Field(default_factory=list)
    page_start: int = 0
    page_end: int = 0
    # Per-provision provenance.  A human_verified source does not make every
    # provision in it reviewed; only provisions a human approved are citable.
    review_status: Literal["human_verified", "unverified", "rejected"] = "unverified"
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None

    @field_validator("original_text")
    @classmethod
    def _text_not_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("original_text must not be empty")
        return value


class CorpusManifest(StrictModel):
    corpus_version: str
    mode: Literal["real", "fixture"]
    sources_count: int
    provisions_count: int
    chunks_count: int = 0
    usable_count: int
    unusable_count: int
    generated_at: datetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# Evidence / extraction
# ---------------------------------------------------------------------------
class PageExtraction(StrictModel):
    page_number: int
    text: str
    method: Literal["text_extraction", "ocr", "pasted_text"] = "text_extraction"
    quality_status: Literal["completed", "partial", "failed", "needs_user_retry"] = "completed"


class Evidence(StrictModel):
    evidence_id: str = Field(default_factory=lambda: new_id("ev_"))
    case_id: str | None = None
    original_filename: str
    storage_key: str
    sha256: str
    mime_type: str
    size_bytes: int
    extraction_status: Literal["completed", "partial", "failed", "needs_user_retry"]
    error_code: str | None = None
    pages: list[PageExtraction] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.pages)


# ---------------------------------------------------------------------------
# Facts / retrieval / verification
# ---------------------------------------------------------------------------
class Fact(StrictModel):
    fact_id: str = Field(default_factory=lambda: new_id("fact_"))
    case_id: str
    fact_type: str
    raw_value: str
    normalised_value: Any = None
    source_type: FactSourceType
    source_id: str
    evidence_id: str | None = None
    page_number: int | None = None
    status: FactStatus
    inferred: bool = False
    ambiguity_flag: bool = False
    supersedes_fact_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class Candidate(StrictModel):
    chunk_id: str
    provision_id: str
    source_id: str
    dense_rank: int | None = None
    sparse_rank: int | None = None
    rrf_score: float = 0.0
    rerank_score: float | None = None
    relevance_grade: int | None = None
    relevance_reason: str | None = None
    applicability: Applicability = "unknown"
    applicability_reasons: list[str] = Field(default_factory=list)
    source_validity: SourceValidity = "uncertain"
    role: Role = "rejected"
    rejection_reason: str | None = None
    added_because: str | None = None
    accepted: bool = False
    conditional: bool = False
    citation: str | None = None


class RetrievalRun(StrictModel):
    run_id: str = Field(default_factory=lambda: new_id("rr_"))
    conversation_id: str | None = None
    query_variants: list[str]
    ranked_lists: dict[str, list[str]] = Field(default_factory=dict)
    fused_chunk_ids: list[str] = Field(default_factory=list)
    corpus_version: str
    index_version: str
    retry_index: int = 0
    latency_ms: float = 0.0
    created_at: datetime = Field(default_factory=utc_now)


class TimelineItem(StrictModel):
    event_type: str
    date: date_cls | None = None
    date_label: str = ""
    precision: Literal["exact", "approximate", "unknown"] = "unknown"
    source_id: str = ""
    source_status: str = ""
    summary: str = ""
    conflict_flag: bool = False


# ---------------------------------------------------------------------------
# LLM structured outputs
# ---------------------------------------------------------------------------
class ScopeDecision(StrictModel):
    in_scope: bool
    domain: str
    reason: str = ""


class FactExtraction(StrictModel):
    facts: list[dict[str, Any]] = Field(default_factory=list)


class RelevanceGrade(StrictModel):
    provision_id: str
    grade: int = Field(ge=0, le=3)
    reason: str


class RelevanceGradeBatch(StrictModel):
    grades: list[RelevanceGrade] = Field(default_factory=list)


class ApplicationAnalysis(StrictModel):
    provision_id: str
    conditional_statement: str
    supporting_fact_ids: list[str] = Field(default_factory=list)


class LawyerNeeded(StrictModel):
    value: bool = False
    reason: str | None = None


class LegalDraft(StrictModel):
    issue_summary: str = ""
    user_reported_facts: list[str] = Field(default_factory=list)
    document_supported_facts: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    relevant_provision_ids: list[str] = Field(default_factory=list)
    application_analysis: list[ApplicationAnalysis] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    possible_options: list[str] = Field(default_factory=list)
    proposed_outcome: Outcome = Outcome.needs_more_information
    proposed_next_step: str = ""
    lawyer_needed: LawyerNeeded = Field(default_factory=LawyerNeeded)


class Assessment(StrictModel):
    outcome: Outcome
    reasons: list[str] = Field(default_factory=list)
    facts_used: list[str] = Field(default_factory=list)
    provision_ids_used: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    urgency: Literal["unknown", "low", "high"] = "unknown"
    next_steps: list[str] = Field(default_factory=list)
    lawyer_needed: bool = False
    lawyer_reason: str | None = None
    rule_trace: list[str] = Field(default_factory=list)
    llm_proposed_outcome: str | None = None


# ---------------------------------------------------------------------------
# Claims (v4 T2-B) and documents
# ---------------------------------------------------------------------------
ClaimType = Literal[
    "citation",
    "legal_rule",
    "deadline_or_timeline",
    "case_fact",
    "application",
    "remedy_or_procedure",
    "recommendation",
]


class Claim(StrictModel):
    claim_id: str = Field(default_factory=lambda: new_id("clm_"))
    claim_type: ClaimType
    text: str
    materiality: Literal["material", "secondary"] = "material"
    cited_provision_ids: list[str] = Field(default_factory=list)
    cited_fact_ids: list[str] = Field(default_factory=list)


class ClaimVerification(StrictModel):
    claim_id: str
    status: Literal[
        "verified", "partially_verified", "unverified", "clarification_required", "outdated_source"
    ]
    reason: str = ""


class DocumentDraft(StrictModel):
    draft_id: str = Field(default_factory=lambda: new_id("doc_"))
    case_id: str
    draft_type: DraftType
    content: str
    status: Literal["needs_review", "approved_by_user"] = "needs_review"
    missing_fields: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


# ---------------------------------------------------------------------------
# State / API payloads
# ---------------------------------------------------------------------------
class Conversation(StrictModel):
    conversation_id: str = Field(default_factory=lambda: new_id("conv_"))
    user_id: str
    created_at: datetime = Field(default_factory=utc_now)


class Message(StrictModel):
    message_id: str = Field(default_factory=lambda: new_id("msg_"))
    conversation_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime = Field(default_factory=utc_now)


class CaseRecord(StrictModel):
    case_id: str
    user_id: str
    status: Literal["open", "resolved", "reopened"] = "open"
    summary: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class RetrievalSummary(StrictModel):
    corpus_version: str = ""
    candidate_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    retry_count: int = 0


class LegalSourceOut(StrictModel):
    provision_id: str
    citation: str
    excerpt: str
    role: str
    applicability: str
    source_validity: str
    official_url: str = ""


class EvidenceProcessing(StrictModel):
    filename: str
    status: Literal["completed", "partial", "failed"]
    error_code: str | None = None


class MessageResponse(StrictModel):
    conversation_id: str
    message_id: str
    assistant_message_id: str
    case_id: str | None = None
    processing_status: Literal["completed", "partial", "needs_clarification", "out_of_scope"]
    assistant_message: str
    case_summary: dict[str, Any] = Field(default_factory=dict)
    extracted_facts: list[Fact] = Field(default_factory=list)
    evidence_processing: list[EvidenceProcessing] = Field(default_factory=list)
    legal_sources: list[LegalSourceOut] = Field(default_factory=list)
    retrieval_summary: RetrievalSummary = Field(default_factory=RetrievalSummary)
    verification: dict[str, Any] = Field(
        default_factory=lambda: {"overall": "unverified", "blocked_claims": []}
    )
    assessment: Assessment | None = None
    missing_information: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    document_draft: DocumentDraft | None = None
