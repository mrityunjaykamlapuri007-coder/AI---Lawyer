# IMPLEMENTATION_PLAN.md: ordered task list for the coding agent

Execute tasks in order. Each task has: Goal, Files, Steps, Test, Done when. After each task: run the test, update `PROGRESS.md`, commit on branch `ai-lawyer-mvp` with message `T<id>: <summary>`. Details of behaviour live in `AGENT_EXECUTION_SPEC.md` (v3); section numbers below refer to it.

Time targets (IST): P0 05:30-06:30, P1 06:30-08:30, P2 08:30-10:30, P3 10:30-12:30, P4 12:30-14:00, P5 14:00-15:30, P6 15:30-16:30, gate 17:00, P7 eval 17:00-19:00, P8 docs 19:00-19:30.

Target layout (create as needed, no empty placeholder files):
```
ai_lawyer/
  config/settings.py
  contracts/{models.py,interfaces.py,fakes.py,errors.py,ids.py}
  legal_corpus/{sources.json,provisions.json,fixture_sources.json,fixture_provisions.json}
  legal_rag/{corpus_loader.py,chunker.py,index_manager.py,query_planner.py,rrf.py,retriever.py,reranker.py,provision_expander.py}
  legal_engine/{source_validity.py,relevance_filter.py,applicability.py,retry_policy.py,reasoning.py,
                citation_validator.py,phrase_guard.py,assessment.py,decision_controller.py}
  backend/{main.py,api/,services/{orchestrator.py,scope_classifier.py,fact_extractor.py,case_manager.py,
           context_assembler.py,evidence_store.py,pdf_text.py,response_generator.py},db/{schema.sql,migrate.py,repo.py}}
  documents/{generator.py,validator.py,templates/}
  frontend/app.py
  evaluation/{metrics.py,run_retrieval_eval.py,run_behavior_eval.py,dataset/,raw_outputs/,results/}
  tests/{unit,integration}/
```

---------------------------------------------------------------------
## PHASE 0: SETUP (05:30-06:30)
---------------------------------------------------------------------
### T0.1 Repo inspection and branch
Goal: understand the existing research-RAG repo; create the workspace.
Steps: list all files; read `src/ingestion.py, retriever.py, reranker.py, rag_chain.py, main.py, app.py` and their imports; write `docs/reuse_notes.md` listing what to reuse, what to drop, and the 14 defects in v3 Section 3. Create branch `ai-lawyer-mvp` and folder `ai_lawyer/`. Do not edit original files.
Test: `git status` shows only new files.
Done when: `docs/reuse_notes.md` exists and names each reused function with its file.

### T0.2 Settings, env, gitignore, requirements
Files: `config/settings.py`, `.env.example`, `.gitignore`, `requirements.txt`.
Steps: `Settings(BaseSettings)` with every variable in v3 Section 5, typed, loaded once via cached `get_settings()`. `.gitignore`: `.env`, `.venv`, `ai_lawyer/data/`, `ai_lawyer/vectorstore/`, models, `__pycache__`, `*.db`, evidence. Pin only imported packages (pydantic, pydantic-settings, fastapi, uvicorn, streamlit, httpx, numpy, pandas, pytest, faiss-cpu, rank-bm25, pymupdf, sentence-transformers, torch, transformers, jinja2); install in a clean venv and record versions.
Test: `pytest -q` collects zero errors; `python -c "from ai_lawyer.config.settings import get_settings; get_settings()"`.
Done when: install works in a clean venv and nothing downloads a model.

### T0.3 Contracts, fakes, fixtures
Files: `contracts/*`, `legal_corpus/fixture_*.json`, `tests/unit/test_contracts.py`.
Steps: Pydantic models from v3 Section 8 (`Fact, Candidate, LegalDraft, Assessment, Outcome enum, Evidence, Claim, DocumentDraft, CorpusManifest, RetrievalRun`). Interfaces (Protocols): `LLMAdapter(generate_structured(prompt, schema, options), generate_text, health_check)`, `Embedder(embed(texts)->ndarray)`, `Reranker(rerank(query, candidates))`. Fakes: `FakeLLM` (scripted responses keyed by a label; can return invalid JSON or an invented provision id on demand), `HashEmbedder` (deterministic, bag-of-hashed-tokens, L2-normalised), identity reranker, in-memory repos. `ids.make_provision_id(source_id, section, subsection=None, clause=None)` deterministic, independent of chunking. Fixture corpus: 8-10 obviously fake provisions under fake source `TEST_ACT` (text starts "FAKE TEST TEXT:"), including one with a proviso, one with an exception, one with `effective_from` in the future, one superseded, one with a `manual` condition, one definition.
Test: `pytest tests/unit/test_contracts.py -q` (schema round trips; FakeLLM scripted/invalid/invented modes; HashEmbedder determinism; id stability).
Done when: all pass offline.

---------------------------------------------------------------------
## PHASE 1: CORPUS (06:30-08:30)
---------------------------------------------------------------------
### T1.1 Corpus loader and validator
Files: `legal_rag/corpus_loader.py`, `tests/unit/test_corpus_loader.py`.
Steps: `load_corpus(mode)` reads real or fixture files per `CORPUS_MODE`. Validate per v3 Section 4.4: resolvable ids (source, parent, provisos, exceptions, definitions_used, cross_references, mandatory_context), no duplicate ids, non-empty `original_text`, allowed operators only, `usable=false` when source `review_status != human_verified`. Return `Corpus` with `.provisions`, `.sources`, `.get(id)`, `.children(id)`, `.usable_ids`. Write `corpus_manifest.json` (hash, counts, unusable count).
Test: `pytest tests/unit/test_corpus_loader.py -q`: dangling id rejected, duplicate rejected, missing text rejected, unusable source flagged, manifest hash stable across runs.
Done when: loader works on the fixture and rejects bad corpora.

### T1.2 Real corpus hookup (user-supplied data)
Steps: if `provisions.json` exists, load it and print counts and unusable count at startup; if missing, run in fixture mode with a visible banner. Do not create real legal text yourself. If the user placed a PDF in `legal_corpus/originals/`, tell the user the parser (Tier 2) can propose units; do not build it yet.
Test: start app functions with `CORPUS_MODE=fixture` and `real` (real with missing file must fail with a clear message, not crash).
Done when: both modes behave as described.

### T1.3 Chunker
Files: `legal_rag/chunker.py`, `tests/unit/test_chunker.py`.
Steps: one chunk per provision by default; split long provisions at clause boundaries only, each child chunk carries `provision_id`, `parent_provision_id`, `chunk_order`, source and version ids. `chunk_id = f"{provision_id}::c{order}"`. `search_text` may prepend citation/heading for embedding; `original_text` untouched.
Test: provision ids unchanged when chunk size config changes; proviso unit stays linked to its parent.
Done when: tests pass.

---------------------------------------------------------------------
## PHASE 2: RETRIEVAL (08:30-10:30)
---------------------------------------------------------------------
### T2.1 RRF
Files: `legal_rag/rrf.py`, `tests/unit/test_rrf.py`.
Signature: `fuse(ranked_lists: list[list[str]], k: int=60) -> list[tuple[str, float, dict]]` returning chunk_id, fused score, per-list ranks. 1-based ranks; sum `1/(k+rank)` across all lists; tie-break by chunk_id ascending.
Test: the worked example in v3 Section 7.4; duplicates across lists/variants sum; absent list contributes 0; output order stable across runs.
Done when: green.

### T2.2 Indexes
Files: `legal_rag/index_manager.py`, `tests/unit/test_index_manager.py`.
Steps: `build(corpus, embedder)` writes FAISS (inner product on L2-normalised vectors, so score direction is "higher is better"; test it), BM25 (tokenizer keeps digits, section numbers and punctuation inside identifiers), `chunk_ids.json` mapping position->chunk_id, `index_manifest.json` (corpus version, embedder id, counts, built_at). Build to a temp dir then atomically rename. `load()` verifies manifest corpus hash equals current corpus hash, else raises `IndexStale`. Load only local project-built artifacts; comment the `allow_dangerous_deserialization` risk.
Test: with HashEmbedder, `build` then `load`; stale hash rejected; mapping position->chunk_id correct.
Done when: green. CLI `python -m ai_lawyer.legal_rag.index_manager build` works on the fixture.

### T2.3 Query planner
Files: `legal_rag/query_planner.py`, tests.
Steps: `plan(message, facts, case_summary) -> QueryPlan{original_query, self_contained_query, expansions[], issue_tags[], reason_per_expansion}`. Self-contained query built from structured facts only (no allegation as fact). Expansions from a small hand-written refund vocabulary dict (generic terms only: refund, return, cancel, delay, pending, denied, partial, grievance, seller, platform, payment). Ordered dedup via `dict.fromkeys`. `original_query` never overwritten.
Test: deterministic across 20 runs; dedup keeps first occurrence; no scientific terms.
Done when: green.

### T2.4 Retriever and expander
Files: `legal_rag/retriever.py`, `legal_rag/provision_expander.py`, `legal_rag/reranker.py` (wrapper, disabled by default), tests.
Steps: `search(plan, filters)`: per variant, `dense_search` and `sparse_search` return ranked lists; keep every list; `rrf.fuse`; consolidate to provision level (best-ranked chunk per provision); optional reranker (flag) records raw score/old rank/new rank; return `Candidate` objects with `dense_rank`, `sparse_rank`, `rrf_score`. Empty result allowed. `expand(candidates, corpus)`: depth-1 expansion over `parent`, `provisos`, `exceptions`, `definitions_used`, `cross_references`, `mandatory_context` with `added_because`; never dropped by score. Append a `RetrievalRun` JSONL line (query variants, per-list ranks, corpus/index version, latency).
Test: FAISS-only and BM25-only run independently; hybrid stable IDs; empty/whitespace query returns []; expansion adds the proviso and exception fixture units; JSONL has per-list ranks.
Done when: green.

**GATE P2:** `pytest -q` green; `python -m ai_lawyer.legal_rag.index_manager build` works.

---------------------------------------------------------------------
## PHASE 3: VERIFICATION (10:30-12:30)
---------------------------------------------------------------------
### T3.1 Source validity
Files: `legal_engine/source_validity.py`, tests. Implement v3 Section 7.2 exactly. Tests: not_yet_effective fixture, superseded fixture, uncertain when `as_of_date` missing or status uncertain.

### T3.2 Applicability
Files: `legal_engine/applicability.py`, tests. Implement v3 Section 7.1: operators `exists, equals, in, date_before, date_after, manual`; three-valued result with reasons; provision-level aggregation; provisions with no conditions => `unknown`. Tests per operator including absence-of-fact => UNKNOWN, explicit negation => FALSE, `manual` => UNKNOWN.

### T3.3 Relevance filter
Files: `legal_engine/relevance_filter.py`, tests. `grade(case_summary, candidates, llm) -> list[{provision_id, grade 0-3, reason}]`, batch up to 8, structured output via `LLMAdapter`; reason must quote or paraphrase the provision text; validate every returned id is in the batch; invalid output => retry once then grade 0 with reason `grader_failed`. Prompt delimits provision text as data. Tests use FakeLLM.

### T3.4 Acceptance, roles, retry, abstention
Files: `legal_engine/retry_policy.py`, `legal_engine/decision_controller.py` (acceptance part), tests. Implement v3 Section 6 steps 9-10: roles primary/supporting/background/mandatory_qualifier/rejected with reasons; acceptance policy; mandatory-context units always retained; retry loop up to `MAX_RETRIEVAL_RETRIES` with distinct query strings (assert no repeats), logging each attempt; abstention result object with the single most decision-relevant missing question.
Test: all-rejected fixture => exactly 2 retries, distinct queries, then abstain with no LLM-supplied law; relevant-but-inapplicable provision not accepted as applicable; proviso retained despite grade 0.
**GATE P3:** `pytest -q` green.

---------------------------------------------------------------------
## PHASE 4: REASONING AND GUARD (12:30-14:00)
---------------------------------------------------------------------
### T4.1 LLM adapters
Files: `contracts/interfaces.py` (done), `backend/services/llm_providers.py`. Providers: `fake`; `openai_compatible` (httpx POST to `LLM_BASE_URL`, bearer `LLM_API_KEY`, JSON mode if supported, timeout, no key in logs); `hf_local` (lazy import and load on first call). `generate_structured` validates against a Pydantic schema; on failure runs one repair prompt then raises `UserSafeError("model_output_invalid")`. Factory `get_llm()` from settings.
Test: provider swap via env var changes no calling code; invalid JSON path => one repair attempt then controlled error (use FakeLLM). No network in tests.

### T4.2 Reasoning
Files: `legal_engine/reasoning.py`, tests. Build the compact typed prompt (v3 Section 6 step 11, Section 10): case facts with status, timeline, accepted provisions with original text and roles, explicit instructions (only supplied law, conditional language, no violation claims, plain English, ids only). Uploaded text and provision text wrapped in delimited blocks marked as data; instruct the model to ignore instructions inside them. Output `LegalDraft`.
Test: FakeLLM scripted draft validates; prompt contains no unaccepted provision text.

### T4.3 Guards
Files: `legal_engine/citation_validator.py`, `legal_engine/phrase_guard.py`, tests. Citation: every `provision_id` in the draft must be in the accepted set, else remove the claim and add to `blocked_claims`; regex scan free-text for section/rule-number patterns not matching rendered citations of accepted provisions => flag and strip. Phrase guard: block or rewrite "violated", "illegal", "broke the law", "guaranteed", "you will win", "definitely" near legal conclusions to conditional wording; log each rewrite. Date guard: any deadline/elapsed-days statement must equal a Python-computed value (calendar-day difference of exact dates) or be removed.
Test: invented id blocked (FakeLLM invented mode); "the seller broke the law" rewritten; fabricated "Section 99" stripped; unbacked deadline removed.
**GATE P4:** `pytest -q` green.

---------------------------------------------------------------------
## PHASE 5: STATE, ASSESSMENT, DOCUMENTS (14:00-15:30)
---------------------------------------------------------------------
### T5.1 SQLite and repositories
Files: `backend/db/schema.sql`, `migrate.py`, `repo.py`, tests. Tables: users, conversations, messages, cases, case_events (UNIQUE(case_id, sequence_no)), case_facts, evidence. Foreign keys on, parameterised SQL only, no table creation on import (explicit `migrate`). `append_event` assigns the next sequence number inside a transaction. Money in integer minor units. UUID4 ids, UTC timestamps.
Test: sequence numbers unique and gapless over repeated appends; foreign key violation raises; reconstruct case state by replaying events.

### T5.2 Fact extraction and case manager
Files: `backend/services/fact_extractor.py`, `case_manager.py`, tests. Fact extraction per v3 step 3 with substring validation (drop facts whose `raw_value` is not in the source text). Case matching: exact `order_id`/`transaction_id`; conflicts or multiple candidates => clarification; two order ids in one message => split question; corrections create new facts with `supersedes_fact_id`; resolved case + new evidence => reopen same case_id.
Test: hallucinated fact dropped; second order id asks to split; same order id attaches; correction supersedes without mutating the old fact.

### T5.3 Evidence store
Files: `backend/services/evidence_store.py`, `pdf_text.py`, tests. Validate extension and magic bytes (`%PDF`), size cap while streaming, generated storage key (never filename-based), SHA-256, atomic write (temp then rename), PyMuPDF per-page text with 1-based page numbers, extraction status; corrupt or encrypted PDF => clear status, other inputs continue. No OCR (DESIGN_ONLY until T2-D).
Test: signature spoof rejected; hash roundtrip equals; filename traversal ignored; one bad file among two does not discard the good one.

### T5.4 Assessment
Files: `legal_engine/assessment.py`, tests. Implement rules R0-R7 from v3 Section 9 in order with `rule_trace`; separate `lawyer_needed` with reason; compare to `llm_proposed_outcome` and log mismatch; Python wins. Tests: every outcome reachable from a labelled fact set; delay or amount alone never yields formal proceedings; unknown essential facts => needs_more_information.

### T5.5 Documents
Files: `documents/generator.py`, `validator.py`, `templates/support_request.md.j2`, `formal_grievance.md.j2`, tests. Per v3 Section 11: facts from store only, placeholders `[TO BE FILLED BY USER]`, DRAFT header, legal grounds only from accepted provisions with rendered citations, validator blocks any id/date/amount not in the fact store. Tests: placeholders present when facts missing; mismatched amount blocked.

### T5.6 Orchestrator and response generator
Files: `backend/services/orchestrator.py`, `scope_classifier.py`, `context_assembler.py`, `response_generator.py`, integration tests. Wire v3 steps 1-16 in order; scope check (LLM + keyword fallback); response in the v3 Section 10 structure with citations rendered from the corpus; persist message, events, retrieval log.
Test (FakeLLM + fixture corpus + HashEmbedder): `test_pipeline_happy_path`, `test_pipeline_abstains_after_two_retries`, `test_pipeline_out_of_scope_refusal`, `test_pipeline_missing_dates_asks_question`, `test_pipeline_second_order_asks_split`, `test_pipeline_partial_attachment_failure`, `test_llm_provider_swap_via_config`.
**GATE P5:** `pytest -q` green.

---------------------------------------------------------------------
## PHASE 6: API AND UI (15:30-16:30)
---------------------------------------------------------------------
### T6.1 FastAPI
Files: `backend/main.py`, `backend/api/*.py`, tests. Lifespan loads corpus/index/LLM once. Endpoints per v3 Section 13 (`POST /conversations`, `POST /conversations/{id}/messages` multipart, `GET /cases`, `GET /cases/{id}`, `POST /cases/{id}/documents`, `GET /health`). One combined response payload. Errors as `{error_code, user_safe_message, correlation_id, retryable}`; no tracebacks to clients; CORS restricted to `ALLOWED_ORIGINS`; request timeout; demo user from a header (document: not safe for real private evidence on a public host).
Test: API contract test with `TestClient`: one call returns all fields; unknown conversation => safe error; health lists components without secrets.

### T6.2 Streamlit UI
Files: `frontend/app.py`. Chat thread; text input; optional PDF/text upload; one backend call per message; escape all user, document and corpus text before rendering (no `unsafe_allow_html` with untrusted content); panels: facts (reported vs document-supported), sources (citation, role, applicability, validity), assessment (plain-English outcome, reasons, unknowns, next step), document draft (editable text, placeholders highlighted, copy button, no send button); fixture-mode banner; limitation note.
Test: manual run with three fresh stories (delayed refund with dates; approved but not received, no dates; tenancy deposit). Record the observed behaviour in `PROGRESS.md`.

---------------------------------------------------------------------
## 17:00 HARD GATE
---------------------------------------------------------------------
- [ ] `pytest -q` green (or each failure documented in PROGRESS.md)
- [ ] a new pasted story returns a full structured answer through the UI
- [ ] invented citation blocked; forbidden phrases blocked
- [ ] out-of-scope refused; missing dates asks a question; all-rejected abstains after exactly 2 distinct retries
- [ ] text PDF upload is stored, hashed, extracted; facts show `document_supported` with page
- [ ] provider swap by env var only
- [ ] every component's status label matches reality
If any fail, fix only these before anything else.

---------------------------------------------------------------------
## PHASE 7: EVALUATION (17:00-19:00)
---------------------------------------------------------------------
### T7.1 Metrics
Files: `evaluation/metrics.py`, tests. Implement precision@K (denominator K), recall@K (essential set, N/A for no-provision rows), MRR@K (grade>=2), nDCG@K (gain 2^g-1, discount log2(i+1), N/A if ideal DCG=0), applicability precision/recall and false acceptance rate, essential-context completeness with critical-omission flag. Hand-computed unit tests including empty result and no-relevant cases.

### T7.2 Dataset and loaders
Files: `evaluation/dataset/development.jsonl`, `test.jsonl`, `annotation_guidelines.md`, `evaluation/dataset_loader.py`. Row schema v3 Section 14A. Loader verifies every provision id exists in the corpus and fails if a scenario id appears in both splits. Agent writes a FIXTURE dataset (about 8 rows against the fake corpus) marked `FIXTURE`. The user supplies real rows. Never tune on `test.jsonl`.

### T7.3 Retrieval experiments
Files: `evaluation/run_retrieval_eval.py`. Run E1 FAISS only, E2 BM25 only, E3 hybrid+RRF, E5 verification (E4 reranker only if available, else mark NOT RUN). Identical corpus, queries, K in {5,10,20}. Write raw outputs (code only) to `raw_outputs/*.jsonl`, `results/*.csv`, `run_manifest.json` (commit, corpus version, model ids, package versions, config, date). Print sample counts and N/A counts.

### T7.4 Behaviour suite
Files: `evaluation/dataset/behavior_cases.jsonl`, `run_behavior_eval.py`. 12-15 cases per v3 Section 14B; one unedited JSON output per case under `raw_outputs/behavior/<id>.json`; `behavior_summary.csv` with PASS/FAIL against expectations. Keep failures; never rewrite outputs.

### T7.5 Failure analysis
Write `evaluation/failure_analysis.md` from real failures only, with reason codes from v2 Section 40.2.

---------------------------------------------------------------------
## PHASE 8: DOCS (19:00-19:30)
---------------------------------------------------------------------
### T8.1 README
Run steps (exact commands), architecture, assumptions (including assessment rules R3-R6 as product decisions), status table with the five labels, known limitations, DESIGN_ONLY list (Jev, RAGAS, OCR, snapshots, extra documents, full 150-question set), security note (token revocation is the user's job; app is local demo only).

### T8.2 Final report
Return the report format in v3 Section 18.

---------------------------------------------------------------------
## AFTER THE 17:00 GATE ONLY (STRETCH, IN THIS ORDER, FROM v4)
---------------------------------------------------------------------
1. T2-C reranker and calibration (dev set only) and E4/E5
2. T2-B claim extractor + LLM entailment
3. T2-F National Consumer Helpline and Consumer Commission drafts (only with supporting accepted provisions)
4. T2-E snapshots and archive checks
5. T2-A corpus parser (propose-only)
6. T2-D OCR behind `OCRProvider`
7. T2-H RAGAS adapter (pinned, smoke-tested)
8. T3-A Jev adapter (interface and fake only)
Stretch work must not delay evaluation, README or the user's doc time. Stop all stretch work by 18:00 if evaluation has not run.
