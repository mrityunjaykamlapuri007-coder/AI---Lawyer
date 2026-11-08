# AI LAWYER MVP: CODING AGENT EXECUTION SPEC (v3, time-boxed)

Project: Kuku AI Generalist Assignment, Problem 2.
Product: AI Consumer Refund Dispute Assistant for India.
Deadline: the whole project must be submittable by 12:00 midnight IST on 8 Nov 2026. Core build must be done by 17:00 IST. This document replaces the v2.0 spec wherever they conflict. v2.0 remains the long-term design reference. Anything not listed here as BUILD is DESIGN_ONLY.

---------------------------------------------------------------------
## 0. HOW YOU (THE AGENT) MUST WORK
---------------------------------------------------------------------
1. Read this whole file first. Then inspect the existing repo (list every file, read every file you will reuse plus its callers).
2. Work one phase at a time (Section 12). After each phase run its tests and report the exact command and result. Do not start the next phase until the previous one's gate passes or the user says to continue.
3. Never claim something works unless you ran it. Label every component in the README with one of: IMPLEMENTED_AND_TESTED, IMPLEMENTED_NOT_TESTED, MOCKED_FOR_TESTING, DESIGN_ONLY, BLOCKED.
4. **Never write legal text, section numbers, deadlines, fees, case names or URLs from memory.** Real legal content is supplied by the user in `legal_corpus/provisions.json` (Section 4). You build the loader, validator and everything downstream. For tests use a clearly fake fixture corpus (Section 4.4).
5. If a model, API or file is missing, build the interface plus a labelled fake for tests and say the live integration is unverified. Do not stub silently.
6. Do not make irreversible repository actions (force push, history rewrite, deleting branches, public deploy) or send data to a third-party service without asking the user first.
7. Do not print, copy or reuse any token found in old notebooks. If you see one, tell the user to revoke it and move on.
8. Prefer small cohesive modules. No empty placeholder files presented as working.

---------------------------------------------------------------------
## 1. SCOPE (LOCKED)
---------------------------------------------------------------------
- Problem: unresolved e-commerce refund disputes in India (cancelled/returned purchase, refund delayed/denied/partial/incorrect).
- English only. Text input. Optional upload of text-based PDF or pasted text as evidence. No voice, no OCR, no translation (OCR = DESIGN_ONLY).
- Anything else (tenancy, salary, divorce, criminal, etc.) returns `out_of_scope`: short limitation message, no legal claims, no templates, suggestion of a qualified lawyer where appropriate.
- The system never files, sends, pays, or contacts anyone. Documents are DRAFTS the user must review.
- The system never claims to be a human lawyer and never guarantees outcomes.

---------------------------------------------------------------------
## 2. ESSENCE: NON-NEGOTIABLE BEHAVIOURS
---------------------------------------------------------------------
E1. Every legal statement shown to the user traces to a verified corpus provision cited by stable `provision_id`. Citations are rendered from the corpus (citation string + verbatim text), never from model-written strings.
E2. Retrieved is not accepted. Per candidate keep three separate labels: `relevance_grade` (0-3), `applicability` (applicable / not_applicable / unknown), `source_validity` (current_for_date / superseded / not_yet_effective / uncertain).
E3. Unknown stays unknown. Missing or conflicting facts produce a question or `needs_more_information`, never a guess.
E4. Facts keep provenance and status: `user_reported` or `document_supported` (never "verified" without an external source, which the MVP does not have).
E5. Python owns the workflow gates and the final outcome. The LLM drafts and extracts; it cannot override the guard.
E6. The LLM is swappable by configuration only.
E7. Evaluation uses our own cases, saves raw outputs unedited, and reports failures honestly.
E8. A delay alone is never called a legal violation. Never say a seller broke the law. Never present a grievance acknowledgement/redressal timeline as a refund payout deadline.

---------------------------------------------------------------------
## 3. REPOSITORY STRATEGY AND REUSE
---------------------------------------------------------------------
The user has an existing "research RAG" repo (FAISS + BM25 + RRF + BGE reranker + FastAPI + Streamlit; files such as src/ingestion.py, retriever.py, reranker.py, context_compressor.py, rag_chain.py, evaluator.py, main.py, app.py). Preserve it.

Default (do this unless the user says otherwise): create a new top-level folder `ai_lawyer/` on a new branch `ai-lawyer-mvp`. Copy and adapt needed code into it. Do not edit or delete the original files. Do not push without asking.

REUSE (adapt, then test):
- FAISS build/load and persistence code
- BM25 integration
- RRF function (fix as below)
- CrossEncoder reranker wrapper (make optional)
- FastAPI app skeleton, Streamlit skeleton

DO NOT REUSE (scientific-domain):
- query-expansion mappings, SECTION_BOOST, detect_section(), context_compressor.py, scientific prompts, the -5.0 reranker threshold, ROUGE/BERTScore evaluator as primary metrics, the PDF research corpus.

KNOWN DEFECTS TO FIX WHEN ADAPTING (from inspection):
1. `list(set(queries))` is non-deterministic: use ordered dedup (`dict.fromkeys`).
2. Multi-query RRF lost rank contributions by deduping before fusing: keep every ranked list, sum 1/(k+rank) per chunk_id, then dedupe.
3. RRF deduped by text hash: dedupe by stable `chunk_id`/`provision_id` only.
4. Model loaded at import time: use lazy loader/FastAPI lifespan; tests must import modules without loading any model.
5. `download_model.py` path vs model-ID mismatch: single config (`LLM_MODEL_ID` or `LLM_MODEL_PATH`).
6. CORS `["*"]`: restrict to configured origins.
7. Returning `str(e)` to clients: return generic error + correlation_id, log details server-side.
8. Mutable default `= []` in Pydantic: use `Field(default_factory=list)`.
9. UI called /ask then /retrieve: one request per message returning everything.
10. UI used unsafe HTML for messages/chunks: escape all user and document text.
11. FAISS `allow_dangerous_deserialization=True`: only load indexes built by this project from local trusted paths; document it.
12. requirements.txt incomplete: produce a pinned, tested requirements file (transformers, torch, sentence-transformers, faiss-cpu, rank-bm25, pymupdf, pydantic, fastapi, uvicorn, streamlit, pytest, pydantic-settings, httpx, numpy, pandas).
13. Hard-coded chunk counts in README/UI: report counts from the actual build manifest.
14. Do not use the notebook; do not read secrets from it.

---------------------------------------------------------------------
## 4. LEGAL CORPUS CONTRACT (HUMAN-SUPPLIED)
---------------------------------------------------------------------
### 4.1 Files
```
ai_lawyer/legal_corpus/
  sources.json        # source registry
  provisions.json     # curated provisions (human-verified)
  fixture_sources.json / fixture_provisions.json   # FAKE, tests only
```

### 4.2 sources.json (list of objects)
```json
{
  "source_id": "string, stable, e.g. CPA2019",
  "title": "exact official title",
  "source_type": "act | rule | notification | regulation | official_guidance",
  "publisher": "issuing authority",
  "official_url": "URL the user verified",
  "published_date": "YYYY-MM-DD or null",
  "retrieved_at": "YYYY-MM-DD",
  "document_sha256": "hex or null",
  "review_status": "human_verified | unverified",
  "version_label": "string",
  "effective_from": "YYYY-MM-DD or null",
  "effective_to": "YYYY-MM-DD or null",
  "version_status": "current | superseded | future | uncertain",
  "notes": "string"
}
```

### 4.3 provisions.json (list of objects)
```json
{
  "provision_id": "stable id, e.g. CPA2019_S2_7 (never derived from chunk position)",
  "source_id": "must exist in sources.json",
  "citation": "human-readable citation as the user typed it from the official text",
  "hierarchy_type": "section | rule | subsection | clause | proviso | explanation | definition",
  "parent_provision_id": "string or null",
  "original_text": "VERBATIM official text",
  "search_text": "optional retrieval-only text (title + heading); never shown as law",
  "provisos": ["provision_id of proviso units that qualify this one"],
  "exceptions": ["provision_id of exception units"],
  "definitions_used": ["provision_id"],
  "cross_references": ["provision_id"],
  "mandatory_context": ["provision_ids that must accompany this provision when it is accepted"],
  "conditions": [
    {
      "condition_id": "string",
      "description": "plain language, tied to the legal text",
      "fact_type": "e.g. return_approved_date",
      "operator": "exists | equals | in | date_before | date_after | manual",
      "expected_value": "value, list, or null",
      "human_review_status": "reviewed | unreviewed"
    }
  ],
  "page_start": 0,
  "page_end": 0
}
```

### 4.4 Loader validation (build in Phase 1, must have tests)
- Every `source_id`, `parent_provision_id`, proviso/exception/definition/cross-reference/mandatory_context id must resolve.
- Duplicate provision_ids are rejected.
- Missing `original_text` is rejected.
- A provision whose source has `review_status != human_verified` is loaded but flagged `usable=false`; the guard must treat it as not citable. The app prints a startup warning with the count of unusable provisions.
- Only `operator` values listed above are allowed; `manual` evaluates to UNKNOWN always.
- Fixture corpus: 8-10 obviously fake provisions under a fake source "TEST_ACT" (text such as "FAKE TEST TEXT: ..."), used only by automated tests and by the demo mode when `CORPUS_MODE=fixture`. Fixture text must never be presented as real law, and the UI must show a "FIXTURE DATA, NOT REAL LAW" banner in that mode.
- Corpus build writes `corpus_manifest.json`: corpus version (hash of sources+provisions), counts, unusable count, timestamp.

---------------------------------------------------------------------
## 5. CONFIGURATION (ONE TYPED SETTINGS OBJECT)
---------------------------------------------------------------------
Use pydantic-settings, loaded once. `.env.example` has placeholders only.
```
APP_ENV=local
CORPUS_MODE=real            # real | fixture
CORPUS_DIR=ai_lawyer/legal_corpus
VECTORSTORE_DIR=ai_lawyer/vectorstore
SQLITE_PATH=ai_lawyer/data/lawyer.db
EVIDENCE_DIR=ai_lawyer/data/evidence
EMBEDDING_MODEL_ID=BAAI/bge-large-en-v1.5   # allow fake/hash embedder for tests
RERANKER_ENABLED=false
RERANKER_MODEL_ID=BAAI/bge-reranker-large
RRF_K=60
DENSE_TOP_K=20
SPARSE_TOP_K=20
FUSED_TOP_K=10
FINAL_TOP_K=5
MAX_RETRIEVAL_RETRIES=2
RELEVANCE_MIN_GRADE=2
LLM_PROVIDER=fake           # fake | openai_compatible | hf_local
LLM_MODEL_ID=
LLM_MODEL_PATH=
LLM_BASE_URL=               # for openai_compatible
LLM_API_KEY=                # secret, never logged
LLM_TEMPERATURE=0
LLM_MAX_TOKENS=1500
LLM_TIMEOUT_S=60
MAX_UPLOAD_MB=5
ALLOWED_ORIGINS=http://localhost:8501
LOG_LEVEL=INFO
```

---------------------------------------------------------------------
## 6. PIPELINE (ONE CALL PER USER MESSAGE)
---------------------------------------------------------------------
`POST /conversations/{id}/messages` runs `orchestrator.handle_message()`:

1. **Validate** message (non-empty, length cap) and any upload (extension + magic bytes `%PDF`, size cap, text only). Never execute uploads. Store the original under a generated key (uuid), compute SHA-256, keep original filename as metadata only.
2. **Scope check** (`scope_classifier`): LLM structured call returning `{in_scope: bool, domain: str}` plus a deterministic keyword fallback. If out of scope => go to step 14 with outcome `out_of_scope`.
3. **Fact extraction** (`fact_extractor`): LLM structured call over the user message (and extracted evidence text). Each fact: `fact_type, raw_value, normalised_value, source_type, source_id, status, ambiguity_flag`. **Deterministic validation:** drop (and log) any fact whose `raw_value` is not a substring (case-insensitive, whitespace-normalised) of the source text. Dates only normalised when unambiguous; relative phrases ("last Friday") stored with the phrase and an inferred date only if the message timestamp is known, marked `inferred=true`. Allowed fact_types: merchant_name, platform_name, order_id, transaction_id, purchase_date, cancellation_date, return_requested_date, return_approved_date, pickup_date, refund_initiated_date, refund_amount, payment_method, refund_status, merchant_promised_timeline_days, support_contact_made (bool), support_contact_date, support_response, grievance_officer_contacted (bool), grievance_contact_date, bank_credit_confirmed (bool).
4. **Case resolution** (`case_manager`): exact `order_id` or `transaction_id` match for this user => attach to that case; conflicting identifiers or multiple candidates => return clarification, no legal run; no identifier and exactly one open case => ask "is this about <merchant/amount/case summary>?"; none => create case. Two different order ids in one message => ask the user to split; do not merge facts. Append events; never mutate past events; corrections create a new fact with `supersedes_fact_id`.
5. **Context assembly** (`context_assembler`): compact dict: current message, case summary, facts grouped by status, timeline, conflicts, missing facts, as_of_date (see 6a).
6. **Query planning** (`query_planner`): deterministic. `original_query` kept untouched; `self_contained_query` built from structured facts (no unverified allegations as facts); up to 3 expansions from a small hand-written refund vocabulary map (written by the agent from generic words like refund, return, cancellation, delay, grievance, seller, platform, payment; NOT legal claims); ordered dedup.
7. **Retrieval** (`retriever`): per query variant run dense (FAISS) and sparse (BM25) separately; keep ranked lists with per-list ranks; RRF over all lists with 1-based ranks `score = sum(1/(RRF_K + rank))`; dedupe by chunk_id after summing; then provision-level consolidation (best chunk per provision_id). Optional reranker (flag): record raw score, original rank, new rank; no threshold. Empty result is allowed.
8. **Expansion** (`provision_expander`): for each retained provision add parent, `provisos`, `exceptions`, `definitions_used`, `cross_references`, `mandatory_context` from the corpus (follow stored links only; depth 1; record `added_because`). Never drop a proviso/exception for low similarity.
9. **Verification** (`verification` package):
   - `source_validity`: compare `as_of_date` with source `effective_from/to` and `version_status`. Unknown date or uncertain status => `uncertain`.
   - `relevance_grade`: LLM structured call, batch of up to 8 candidates, input = case summary + provision original_text, output `{provision_id, grade 0-3, reason}`. Reason must reference the provision text. Embedding/reranker score is never the only basis.
   - `applicability`: deterministic 3-valued evaluation of the stored conditions against facts (Section 7). A provision without reviewed conditions => `unknown`.
   - Acceptance (primary rule): grade >= RELEVANCE_MIN_GRADE AND source_validity == current_for_date AND applicability != not_applicable AND provision usable. `applicability == unknown` is accepted only as "conditional" and must be presented as "may apply if...". Mandatory-context units are retained with `role=mandatory_qualifier` regardless of their own score.
   - Roles: primary / supporting / background / mandatory_qualifier / rejected, each with a reason. Keep rejected candidates in diagnostics.
10. **Bounded retry**: if no primary or conditional candidate survives, retry up to MAX_RETRIEVAL_RETRIES with a rewritten query (retry 1: self-contained query with more facts, drop weak expansions; retry 2: broader but issue-bounded). Never repeat an identical query string. Log each attempt and reason. Still nothing => abstain: say the supported knowledge base did not establish an applicable provision, ask for the most decision-relevant missing fact, or state the scope limit. Never fill from model memory.
11. **Reasoning** (`reasoning`): one LLM structured call. Input: compact case context + accepted provisions (original text + IDs + roles) + instructions. Output validated by `LegalDraft` (Section 8). Invalid JSON => one repair attempt, then controlled error; never parse prose into a decision.
12. **Claim guard** (`citation_validator` + `verification`): deterministic checks only for the MVP:
    - every `provision_id` the model cites must be in the accepted set; otherwise remove the claim and flag `citation_blocked`;
    - any section/rule number pattern in free-text fields that does not match a cited provision's citation string is flagged and removed or replaced by the rendered citation;
    - phrases asserting a violation ("violated", "illegal", "broke the law", "guaranteed", "you will win") are blocked or rewritten to conditional wording; log it;
    - any date/deadline sentence must be backed by a Python-computed value (Section 7.3) or removed.
13. **Assessment + decision controller** (`assessment`, `decision_controller`): Python rules (Section 9) decide the outcome. The LLM's `proposed_outcome` is logged and compared; on mismatch Python wins and the mismatch is recorded.
14. **Response generation** (`response_generator`): plain-English message in the structure of Section 10, citations rendered from corpus. Optional document draft (Section 11) when requested or recommended.
15. **Persist** assistant message, case events (`assessment_created`, `fact_added`, ...), retrieval log (JSONL, safe fields only).
16. **Return** one combined JSON payload (Section 13).

6a. `as_of_date`: the date the relevant event happened if known (e.g. return/cancellation/purchase date), else today. Record which one was used. If the event date is unknown, source_validity is `uncertain` for date-dependent provisions and the system may ask for the date.

---------------------------------------------------------------------
## 7. DETERMINISTIC LOGIC SPECS
---------------------------------------------------------------------
### 7.1 Three-valued condition evaluation
Input: a condition and the fact list. Output: TRUE | FALSE | UNKNOWN with reason.
- `exists`: TRUE if a fact of `fact_type` exists with status in {user_reported, document_supported} and non-null value; UNKNOWN otherwise (absence of a fact is not proof of absence; FALSE only if a fact explicitly states the negation, e.g. support_contact_made=false).
- `equals`: TRUE on normalised match; FALSE on established mismatch; UNKNOWN if missing/ambiguous/conflicting.
- `in`: same with a list.
- `date_before` / `date_after`: TRUE/FALSE only when both dates are exact; else UNKNOWN.
- `manual`: always UNKNOWN.
Provision applicability = TRUE if all required conditions TRUE; FALSE if any required condition FALSE; else UNKNOWN. Provisions with no conditions => UNKNOWN (never silently TRUE).

### 7.2 Source validity
current_for_date iff version_status != uncertain AND (effective_from is null or <= as_of_date) AND (effective_to is null or >= as_of_date). If effective_from > as_of_date => not_yet_effective. If effective_to < as_of_date => superseded. If dates missing or status uncertain => uncertain.

### 7.3 Date arithmetic
Python only. Allowed: difference in calendar days between two exact dates, and comparison against `merchant_promised_timeline_days` when the merchant's own promised timeline is a user-supplied/document-supported fact. State the counting convention (calendar days, trigger date excluded). No statutory deadline arithmetic in the MVP unless a human-reviewed condition with an explicit duration exists in the corpus.

### 7.4 RRF unit tests (must exist)
Two lists [A,B,C] and [B,A,D], k=60: A = 1/61 + 1/62; B = 1/62 + 1/61; C = 1/63; D = 1/63; equal scores broken deterministically by chunk_id. Duplicate chunk across variants sums contributions. Absent from a list => 0 for that list. Query dedup order stable across runs.

---------------------------------------------------------------------
## 8. DATA MODELS (PYDANTIC; VALIDATE ALL I/O)
---------------------------------------------------------------------
```python
class Fact: fact_id, case_id, fact_type, raw_value, normalised_value, source_type("user_message"|"evidence"),
            source_id, evidence_id|None, page_number|None, status("user_reported"|"document_supported"|"disputed"|"unknown"),
            inferred: bool, ambiguity_flag: bool, supersedes_fact_id|None, created_at
class Candidate: chunk_id, provision_id, source_id, dense_rank|None, sparse_rank|None, rrf_score, rerank_score|None,
                 relevance_grade|None, relevance_reason|None, applicability, applicability_reasons[], source_validity,
                 role, rejection_reason|None, added_because|None
class LegalDraft: issue_summary, user_reported_facts[], document_supported_facts[], missing_facts[], relevant_provision_ids[],
                  application_analysis[ {provision_id, conditional_statement, supporting_fact_ids[]} ], assumptions[], uncertainties[],
                  possible_options[], proposed_outcome(enum), proposed_next_step, lawyer_needed{value:bool, reason|None}
class Assessment: outcome(enum), reasons[], facts_used[], provision_ids_used[], missing_information[], uncertainties[],
                  urgency("unknown"|"low"|"high"), next_steps[], lawyer_needed, lawyer_reason|None, rule_trace[], llm_proposed_outcome|None
Outcome enum: no_legal_action_currently_required | informal_resolution_recommended | formal_grievance_recommended |
              formal_legal_proceedings_may_be_justified | needs_more_information | out_of_scope
```
Money: integer minor units + currency. IDs: UUID4. Timestamps: UTC ISO-8601.

---------------------------------------------------------------------
## 9. ASSESSMENT RULES (PRODUCT DECISIONS, DOCUMENT AS ASSUMPTIONS IN README)
---------------------------------------------------------------------
Evaluate in order; first match wins; always record `rule_trace`.
R0. Out of scope => `out_of_scope`.
R1. No accepted/conditional provision after retries => `needs_more_information` with abstention message.
R2. Essential facts unknown (refund_status or any of return/cancellation date AND no reasonable alternative) => `needs_more_information` (ask one question).
R3. `support_contact_made` not true (unknown or false) and the problem is a delayed/pending refund => `informal_resolution_recommended` (draft support request).
R4. A documented `merchant_promised_timeline_days` exists, both trigger and today's date are exact, and elapsed days <= promised => `no_legal_action_currently_required` (monitor; follow up after the promised date).
R5. Support contacted, issue unresolved, `grievance_officer_contacted` not true => `formal_grievance_recommended`.
R6. Grievance route attempted and unresolved AND the corpus holds an accepted provision about the formal Consumer Commission route => `formal_legal_proceedings_may_be_justified` with "may be justified, not guaranteed" wording, plus `lawyer_needed` reasons if amount/complexity/limitation flags apply.
R7. Otherwise => `needs_more_information`.
Rules R3-R6 never depend on amount alone or on delay length alone. No numeric legal score. `lawyer_needed=true` only with a reason: unclear liability between multiple parties, allegations of fraud/criminal conduct, user mentions a court/limitation deadline, or the user asks for representation. Ambiguity about which party is responsible (seller, marketplace, payment provider, bank) is stated, never assumed.

---------------------------------------------------------------------
## 10. USER RESPONSE FORMAT
---------------------------------------------------------------------
Plain English, concise:
1. What I understood (summary).
2. What you told me vs what your documents show (labelled).
3. Legal provisions that may apply (rendered citation + short verbatim excerpt from corpus, link only if a verified URL exists), written as "may apply if...".
4. What is not established yet.
5. Recommended next step and why (outcome in plain words; distinguish grievance from formal proceedings).
6. One follow-up question if needed.
7. Limitations: AI assistant, not a lawyer; when a real lawyer is advisable.
No scores, no internal metrics in the customer view. No guarantees.

---------------------------------------------------------------------
## 11. DOCUMENT DRAFTING
---------------------------------------------------------------------
Types in MVP: `support_request` and `formal_grievance` (templates in `ai_lawyer/documents/templates/*.md.j2` or Python templates). Facts come from the fact store only. Missing mandatory fields (name, address, order id, date, amount, merchant) render as `[TO BE FILLED BY USER]`. Header: "DRAFT: prepared for your review. Not sent or filed." Legal grounds section lists only accepted provisions with rendered citations; if none, omit the section. A post-generation validator checks every order id/date/amount in the draft exists in the fact store; any mismatch blocks the draft. No signing, no auto-send. NCH summary and Consumer Commission draft are DESIGN_ONLY.

---------------------------------------------------------------------
## 12. BUILD PHASES (WITH TIME BOXES AND GATES)
---------------------------------------------------------------------
Times are IST targets. Report after each phase.

**P0 Setup (05:15-06:15).** New branch/folder; settings; `.env.example`; `.gitignore` (data, vectorstore, .env, models, evidence, __pycache__); pinned requirements; pytest harness; fake LLM adapter and fake (hash) embedder; lazy loaders.
Gate: `pytest -q` runs with no model download; importing any module loads no model.

**P1 Corpus (06:15-08:30, parallel with the user's data work).** Models, loader, validator, manifest builder, fixture corpus, stable-ID tests.
Gate: loader tests pass on fixture; invalid corpus (dangling id, duplicate id, missing text) is rejected; unusable provisions flagged.

**P2 Retrieval (08:30-10:30).** Chunker (one chunk per provision; split long provisions at subsection/clause boundaries with `parent_provision_id`), FAISS + BM25 index build/load with manifest, query planner, multi-list RRF, provision consolidation, optional reranker, provision expander, retrieval JSONL log.
Gate: RRF tests (Section 7.4), query dedup determinism, FAISS-only and BM25-only run independently, hybrid returns stable IDs, empty query returns empty safely, expansion adds proviso/exception on the fixture.

**P3 Verification (10:30-12:30).** Source validity, relevance grader (fake in tests), 3-valued applicability, acceptance policy and roles, bounded retry, abstention.
Gate: tests for TRUE/FALSE/UNKNOWN per operator; not_yet_effective and superseded fixtures rejected; relevant-but-inapplicable fixture not accepted as applicable; all-rejected case triggers exactly 2 retries with distinct queries then abstains; proviso retained despite low score.

**P4 Reasoning + guard (12:30-14:00).** LLM adapter (fake, openai_compatible via httpx, hf_local lazy), `LegalDraft` schema + repair-once, citation validator, forbidden-phrase guard, date-claim guard.
Gate: a fake LLM returning an invented provision_id is blocked; a draft saying "the seller broke the law" is rewritten/blocked; invalid JSON gets one repair then controlled error; swapping `LLM_PROVIDER` changes no business code.

**P5 State, assessment, documents (14:00-15:30).** SQLite schema (tables: users, conversations, messages, cases, case_events, case_facts, evidence) with a simple migration script (no table creation on import), append-only events with transactional sequence numbers, exact-ID case matching, evidence store + SHA-256 + PyMuPDF text extraction, assessment rules R0-R7, decision controller, response generator, two templates + validator.
Gate: all six outcomes reachable from labelled cases; second order id in a message triggers split question; event sequence unique under two sequential appends; SHA-256 of stored file equals original; a PDF upload with one corrupt file does not discard the successful one; document with missing fields shows placeholders; mismatched amount blocks the draft.

**P6 API + UI (15:30-16:30).** FastAPI endpoints (Section 13), safe errors with correlation_id, restricted CORS, upload limits; Streamlit chat with one call per message, escaped rendering, panels for facts (reported vs document-supported), sources, assessment, draft review/copy, fixture banner.
Gate: manual run of three fresh stories; API contract test.

**17:00 HARD GATE (user + agent).** All true or fix before anything else:
- [ ] one pasted story gives a full structured answer through the UI
- [ ] invented citation blocked (test)
- [ ] out-of-scope refused with zero legal claims (test)
- [ ] missing-dates story asks a question, no conclusion (test)
- [ ] RRF and metric tests pass
Then P7.

**P7 Evaluation (17:00-19:00).** See Section 14.

**P8 Docs (19:00-19:30).** README (run steps, architecture, assumptions, status labels, known limitations), `failure_analysis.md` from real failures only.

---------------------------------------------------------------------
## 13. API CONTRACT
---------------------------------------------------------------------
- `POST /conversations` -> `{conversation_id, created_at}`
- `POST /conversations/{id}/messages` (multipart: `message`, optional `attachments[]`, optional `case_id`) -> one payload:
```json
{
 "conversation_id": "", "message_id": "", "assistant_message_id": "", "case_id": null,
 "processing_status": "completed|partial|needs_clarification|out_of_scope",
 "assistant_message": "", "case_summary": {}, "extracted_facts": [],
 "evidence_processing": [{"filename":"","status":"completed|failed","error_code":null}],
 "legal_sources": [{"provision_id":"","citation":"","excerpt":"","role":"","applicability":"","source_validity":""}],
 "retrieval_summary": {"corpus_version":"","candidate_count":0,"accepted_count":0,"rejected_count":0,"retry_count":0},
 "verification": {"overall":"verified|partially_verified|unverified|clarification_required","blocked_claims":[]},
 "assessment": {}, "missing_information": [], "next_steps": [], "document_draft": null
}
```
- `GET /cases`, `GET /cases/{id}`, `POST /cases/{id}/documents` (type: support_request|formal_grievance; returns draft, never sends), `GET /health` (components only, no secrets).
- Errors: `{error_code, user_safe_message, correlation_id, retryable}`. Local demo security mode only: a header user id; document that the app is NOT safe for real private evidence on a public host.

---------------------------------------------------------------------
## 14. EVALUATION (SCALED-DOWN, HONEST)
---------------------------------------------------------------------
**Two separate things:**

A. **Retrieval benchmark** (provision-level, stable IDs). Files:
```
ai_lawyer/evaluation/dataset/development.jsonl   # ~15 rows
ai_lawyer/evaluation/dataset/test.jsonl          # ~25-30 rows, never used for tuning
ai_lawyer/evaluation/dataset/annotation_guidelines.md
```
Row schema: `test_id, category, user_query, case_facts, as_of_date, expected_provision_ids, essential_provision_ids, relevance_by_provision{id:0-3}, applicability_by_provision{id:applicable|not_applicable|unknown}, source_validity_by_provision, expected_retrieval_status(provisions_expected|no_supported_provision|clarification_needed), required_context_ids, rationale, annotation_author`. The user writes real rows against the real corpus. The agent writes a **fixture** dataset (about 8 rows against the fake corpus) so the harness is testable now, and marks it `FIXTURE`.

Metrics (provision-level; document one convention and use it everywhere), K in {5,10,20} clipped to corpus size:
- Precision@K = |top-K unique ∩ relevant(grade>=2)| / K (missing positions count as non-relevant; also report number_returned).
- Recall@K = |top-K ∩ essential| / |essential|; N/A for no-supported-provision rows (report false positives for those separately; never divide by zero).
- MRR@K: first rank with grade>=2; 0 if none.
- nDCG@K: gain 2^grade - 1, discount log2(i+1); N/A if ideal DCG = 0.
- Applicability precision/recall, false acceptance rate (inapplicable/superseded accepted into verified context / all such candidates; state denominator), essential-context completeness (retrieved required units / total required) plus a critical-omission flag.
- Report macro averages, per-category values, sample counts, N/A counts. No single aggregate.
Experiments on identical corpus/queries/K: E1 FAISS only; E2 BM25 only; E3 hybrid+RRF; E4 E3+reranker (skip and mark NOT RUN if reranker unavailable); E5 E4 or E3 + verification (relevance/applicability/validity).
Outputs:
```
ai_lawyer/evaluation/raw_outputs/{faiss_only,bm25_only,hybrid_rrf,reranked,verified_context}.jsonl   # unedited, written by code only
ai_lawyer/evaluation/results/{retrieval_metrics,applicability_results,latency}.csv
ai_lawyer/evaluation/run_manifest.json   # commit hash, corpus version, model ids, package versions, config, date
ai_lawyer/evaluation/failure_analysis.md # written from real failures
```
Unit-test every metric function with hand-computed examples (include an nDCG example, an empty-result example, a no-relevant example).
RAGAS = DESIGN_ONLY unless time remains after P7; if added, pin the version and isolate in an adapter.

B. **End-to-end behaviour cases** (`evaluation/dataset/behavior_cases.jsonl`): 12-15 synthetic stories, each with `expected_outcome`, `must_ask_question: bool`, `must_refuse: bool`, `forbidden_phrases[]`. The runner calls the real pipeline and writes ONE raw output file per case under `evaluation/raw_outputs/behavior/<test_id>.json` (full unedited response). A separate `behavior_summary.csv` records PASS/FAIL against expectations. Required mix: 3 clear delayed-refund with dates; 2 approved-but-not-received; 2 denied/partial; 2 missing key dates; 1 seller/platform/payment-provider ambiguity; 1 informal-first; 2 out-of-scope (tenancy deposit, salary); 1 bait prompt for an invented section and a guaranteed win. Failures stay in the output; do not delete or rewrite them.

Never tune on test.jsonl. Never edit raw outputs. Never remove hard cases after seeing results. If the real corpus is not ready, run the fixture mode and say so in every result file header.

---------------------------------------------------------------------
## 15. TEST LIST (NAMES THE AGENT MUST CREATE)
---------------------------------------------------------------------
Unit: `test_corpus_loader_rejects_dangling_ids`, `test_corpus_loader_rejects_duplicate_ids`, `test_unusable_source_not_citable`, `test_stable_provision_id_independent_of_chunking`, `test_query_dedup_is_ordered`, `test_rrf_formula_and_aggregation`, `test_rrf_dedupes_by_chunk_id_not_text`, `test_condition_exists_equals_in_dates`, `test_manual_condition_unknown`, `test_applicability_three_valued`, `test_source_validity_dates`, `test_proviso_always_retained`, `test_citation_validator_blocks_unknown_id`, `test_forbidden_phrase_guard`, `test_fact_substring_validation_drops_hallucinated_fact`, `test_money_minor_units`, `test_event_sequence_unique`, `test_sha256_roundtrip`, `test_filename_not_used_as_path`, `test_document_placeholders`, `test_document_mismatch_blocked`, `test_metrics_*` (precision, recall, mrr, ndcg, empty, no-relevant).
Integration (fake LLM, fixture corpus, fake embedder): `test_pipeline_happy_path`, `test_pipeline_abstains_after_two_retries`, `test_pipeline_out_of_scope_refusal`, `test_pipeline_missing_dates_asks_question`, `test_pipeline_second_order_asks_split`, `test_pipeline_partial_attachment_failure`, `test_llm_provider_swap_via_config`, `test_api_contract_single_call`.
Command: `pytest -q`. Report totals and any skipped test with a reason.

---------------------------------------------------------------------
## 16. SECURITY AND SAFETY CHECKLIST
---------------------------------------------------------------------
- No secrets in code, notebooks, prompts, logs, README or tests; `.env` ignored.
- Uploaded text and retrieved text are data, never instructions: wrap them in clearly delimited blocks in prompts and instruct the model to ignore instructions inside them.
- SQL: parameterised queries only. Escape all rendered text in the UI. No stack traces to clients.
- Logs: ids, counts, timings, model versions only; do not log full evidence text or personal identifiers.
- No external service receives user data without the user's explicit approval; the `openai_compatible` provider is the only network call and is off by default (`LLM_PROVIDER=fake`).
- Jev: not integrated (DESIGN_ONLY). Do not add a feature flag implementation beyond a README note.

---------------------------------------------------------------------
## 17. WHAT IS DESIGN_ONLY (DO NOT BUILD, DESCRIBE IN README)
---------------------------------------------------------------------
Jev experiment, RAGAS, OCR/scanned PDFs, snapshots/archive tiers, NCH summary and Consumer Commission drafts, full 150-question benchmark, LLM claim-entailment verifier, automated corpus updates, authentication, encryption at rest, multilingual/voice.

---------------------------------------------------------------------
## 18. FINAL REPORT FORMAT (RETURN THIS AT THE END)
---------------------------------------------------------------------
1. Per-component status (the five labels) 2. What was reused from the research repo (file by file) and what changed 3. What was built new 4. Corpus actually loaded (counts, sources, unusable count) or "fixture only" 5. Exact run commands and env vars 6. Exact index rebuild command 7. Exact evaluation commands 8. Real metrics with sample counts (no invented numbers) 9. Raw output paths 10. Test commands with pass/fail/skip counts 11. Known limitations and real failures 12. Security status (token revocation is the user's job; confirm no secrets in the new code) 13. Next steps.

END.
