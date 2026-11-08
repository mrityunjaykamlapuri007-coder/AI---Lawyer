# Final report — AI Consumer Refund Dispute Assistant MVP

**Run date:** 2026-11-08  
**Workspace:** `C:\Users\Lenovo\OneDrive\Documents\Default Project`  
**Package:** `ai_lawyer/`  
**Mode:** fixture demo — **`FIXTURE DATA, NOT REAL LAW`**  
**Bottom line:** the fixture-mode MVP is implemented, runs end to end, and is
covered by 141 offline tests plus 18 behaviour checks. A review-only draft
corpus (6 sources, 145 provisions) and a mechanical reviewer checklist were
generated from the English extracted text. Real-law use is still **BLOCKED**:
no reviewed real corpus exists and no real source has been verified. No real
legal metric is reported.

---

## 1. What was implemented

Status labels: `IMPLEMENTED_AND_TESTED`, `IMPLEMENTED_NOT_TESTED`,
`MOCKED_FOR_TESTING`, `DESIGN_ONLY`, `BLOCKED`.

| Module / capability | Status | Evidence / note |
|---|---|---|
| Typed settings, `.env.example`, path resolution, lazy provider factories | IMPLEMENTED_AND_TESTED | `config/settings.py`; suite-wide |
| Contracts (Fact, Candidate, Assessment, LegalDraft, Evidence, DocumentDraft, CorpusManifest) | IMPLEMENTED_AND_TESTED | `contracts/models.py`; `tests/unit/test_contracts.py` |
| Fixture corpus loader, validation, manifest hash, unusable-source gate | IMPLEMENTED_AND_TESTED | `legal_rag/corpus_loader.py`; `test_corpus_loader.py` (9 tests) |
| Real corpus mode | BLOCKED | `sources.json` / `provisions.json` absent; fails closed with `CorpusValidationError`; test `test_real_mode_without_sources_fails_clearly` |
| English extraction from bilingual PDFs | IMPLEMENTED_AND_TESTED | `legal_rag/english_extract.py`; 11 tests; 6 parts; 5 parts 100% Latin, ECR 0.99957 because of 6 Devanagari enumeration markers; candidate metadata quoted from source |
| Draft corpus ingestion (mechanical, review-only) | IMPLEMENTED_AND_TESTED | `legal_rag/draft_ingest.py`; 21 tests; writes `legal_corpus/draft/`; 6 sources, 145 provisions, all `unverified`, 0 usable; `REVIEWER_CHECKLIST.md` with mechanical flags and section-gap report |
| Provision-aware chunker with stable chunk ids | IMPLEMENTED_AND_TESTED | `legal_rag/chunker.py`; 4 tests |
| FAISS dense index, BM25 sparse index, atomic build, stale-index rejection | IMPLEMENTED_AND_TESTED | `legal_rag/index_manager.py`; 8 tests; CLI build verified |
| Reciprocal Rank Fusion | IMPLEMENTED_AND_TESTED | `legal_rag/rrf.py`; 5 tests |
| Query planner and refund vocabulary | IMPLEMENTED_AND_TESTED | `legal_rag/query_planner.py`; exercised by retrieval harness |
| Retriever, provision expansion | IMPLEMENTED_AND_TESTED | `legal_rag/retriever.py`, `provision_expander.py`; exercised by harness and pipeline |
| Optional cross-encoder reranker | IMPLEMENTED_NOT_TESTED | `legal_rag/reranker.py`; lazy import, disabled by default; E4 NOT RUN |
| Source validity (current / superseded / future / uncertain) | IMPLEMENTED_AND_TESTED | `legal_engine/source_validity.py`; `test_engine.py` |
| Three-valued applicability and provision aggregation | IMPLEMENTED_AND_TESTED | `legal_engine/applicability.py`; tests for all operators |
| Relevance grading with FakeLLM + invalid-output fallback | IMPLEMENTED_AND_TESTED | `legal_engine/relevance_filter.py` |
| Acceptance roles, mandatory proviso retention, bounded retries, abstention | IMPLEMENTED_AND_TESTED | `acceptance.py`, `retry_policy.py` |
| Citation, phrase, date guards | IMPLEMENTED_AND_TESTED | `citation_validator.py`, `phrase_guard.py`, `date_guard.py` |
| Assessment rules R0-R7, lawyer flag, rule trace | IMPLEMENTED_AND_TESTED | `legal_engine/assessment.py`; unit + 17 behaviour cases |
| Decision controller: Python outcome wins | IMPLEMENTED_AND_TESTED | `legal_engine/decision_controller.py`; test + live traces |
| Reasoning prompt with data blocks and accepted-text-only constraint | IMPLEMENTED_AND_TESTED | `legal_engine/reasoning.py` |
| SQLite schema, migrations, events, replay, case ownership | IMPLEMENTED_AND_TESTED | `backend/db/`; 15 service tests |
| Fact extraction, date inference, conflict flags, corrections, reopen | IMPLEMENTED_AND_TESTED | `backend/services/fact_extractor.py`, `case_manager.py` |
| Evidence store, PDF/text extraction, quality status, size/type checks | IMPLEMENTED_AND_TESTED | `backend/services/evidence_store.py`, `pdf_text.py` |
| Document generator + validator | IMPLEMENTED_AND_TESTED | `documents/`; 5 tests; templates for `support_request`, `formal_grievance` |
| Orchestrator / response generator | IMPLEMENTED_AND_TESTED | `backend/services/orchestrator.py`, `response_generator.py`; 9 integration tests |
| FastAPI endpoints and safe error envelope | IMPLEMENTED_AND_TESTED | `backend/main.py`, `backend/api/routes.py`; 6 API tests + live smoke |
| Streamlit client | IMPLEMENTED_AND_TESTED | Starts and serves HTTP 200; 2 headless Streamlit `AppTest` interaction tests (banner, chat flow, draft render, offline state); not real-browser automation |
| `FakeLLM`, `HashEmbedder` | MOCKED_FOR_TESTING | Deterministic, offline; used by all tests and the demo |
| OpenAI-compatible / HF-local LLM, SentenceTransformer embedder | IMPLEMENTED_NOT_TESTED | Lazy adapters exist; no network, model download, or GPU run |
| Retrieval evaluation E1/E2/E3/E5 | IMPLEMENTED_AND_TESTED (FIXTURE) | `run_retrieval_eval.py`; 160 raw records over 16 rows |
| Retrieval evaluation E4 | DESIGN_ONLY / NOT RUN | Optional reranker unavailable |
| Behaviour evaluation | IMPLEMENTED_AND_TESTED (FIXTURE) | `run_behavior_eval.py`; 17 core cases + 1 derived check |
| Real legal corpus, OCR, claim entailment, RAGAS, Jev, snapshots | DESIGN_ONLY / BLOCKED | See Sections 11 and 14 |

---

## 2. What was reused from the research RAG assistant

The reference project is preserved unchanged at
`reference/research-rag-assistant/`. Full mapping is in
`ai_lawyer/docs/reuse_notes.md`.

| Reference file / function | Reused or changed |
|---|---|
| `src/ingestion.py::extract_text_from_pdf`, `load_all_papers`, `clean_text` | Reused PyMuPDF page extraction and page metadata; added quality status and provenance in `backend/services/pdf_text.py` |
| `src/ingestion.py::chunk_documents` | Reused clause/sentence-aware splitting concept; changed to provision-first chunks with stable ids in `legal_rag/chunker.py` |
| `src/retriever.py::semantic_search`, `bm25_search` | Reused dense + sparse retrieval shape; rebuilt in `legal_rag/index_manager.py` with manifest and stale-index checks |
| `src/retriever.py::rrf_fusion` | Reused RRF idea; fixed to 1-based ranks and removed post-fusion section boosting in `legal_rag/rrf.py` |
| `src/retriever.py::generate_queries` | Reused query expansion concept; replaced the piezoelectric table with a deterministic refund vocabulary in `legal_rag/query_planner.py` |
| `src/rag_chain.py::rewrite_query` | Reused self-contained-query idea; now built from structured facts without an LLM call |
| `src/rag_chain.py` prompt template | Reused context-delimited prompt shape; rebuilt as typed prompt with accepted provisions only in `legal_engine/reasoning.py` |
| `src/rag_chain.py::clean_answer` | Replaced blind truncation with validation/rewrite guards (`citation_validator.py`, `date_guard.py`, `phrase_guard.py`) |
| `src/reranker.py::rerank` | Reused optional cross-encoder reranking and rank recording; removed hard-coded threshold, added lazy fallback |
| `src/main.py` `/ask`, `/retrieve`, `/health` | Reused FastAPI/health shape; replaced with conversation/case/document endpoints and safe errors |
| `app.py` chat and source panels | Reused Streamlit layout idea; added escaping, fixture banner, and no send button |
| `src/evaluator.py` | Reused evaluation-as-code idea; replaced ROUGE/BERTScore with retrieval, applicability, and behaviour metrics |

Dropped: `context_compressor.py`, `download_model.py`, section boosting, the
piezoelectric expansion table, import-time Llama loading, and the
ROUGE/BERTScore dashboard.

---

## 3. What was built new

- `legal_engine/`: source validity, applicability, relevance filter, acceptance,
  retries/abstention, reasoning prompt, citation/phrase/date guards, R0-R7
  assessment, decision controller.
- `legal_rag/`: provision-aware chunker, FAISS/BM25 index manager with manifest,
  RRF, refund query planner, retriever, expansion, optional reranker, the English
  extractor for the bilingual gazette PDFs, and the mechanical draft-corpus
  builder used for human review.
- `backend/`: FastAPI app, safe error handlers, conversation/case/document
  routes, orchestrator, scope classifier, fact extractor, case manager, context
  assembler, evidence store, PDF text extraction, SQLite schema/repo.
- `documents/`: fact-store-backed support request and formal grievance drafts
  with a validator that blocks unbacked ids, dates, amounts, and citations.
- `frontend/`: Streamlit demo client with escaped rendering, fixture banner,
  facts/sources/assessment/draft panels, and no send button.
- `evaluation/`: metric implementations, 16-row fixture retrieval dataset
  (8 development, 8 test), 17-case behaviour dataset, retrieval/behaviour
  harnesses, raw outputs, run manifests, failure analysis.
- `tests/`: 141 offline unit/integration tests.

---

## 4. Data and legal sources

**No official legal document was ingested, parsed, or cited as real law.**

| Item | Status |
|---|---|
| Real corpus `ai_lawyer/legal_corpus/sources.json` | Absent |
| Real corpus `ai_lawyer/legal_corpus/provisions.json` | Absent |
| Supplied PDFs in `ai_lawyer/legal_corpus/originals/` | Present (gitignored); SHA-256 recorded in draft sources; byte-identical to the copies in `ai-lawyer/legal_corpus/originals/` |
| Extracted English parts (`legal_corpus/extracted_en/`) | 6 parts; 5 parts 100% Latin, ECR 0.99957 Latin because 6 Devanagari enumeration markers were kept; low OCR risk; Hindi lines dropped rather than repaired |
| Draft corpus (`ai_lawyer/legal_corpus/draft/`) | 6 unverified sources, 145 draft provisions, 0 usable; generated 2026-11-08; includes `REVIEWER_CHECKLIST.md` |
| Source review | No real source has `review_status: human_verified`; none was fabricated |
| Draft metadata | Candidate titles, dates, departments and gazette IDs are quoted from the documents; `publisher`, `official_url`, `published_date` and effective dates remain blank for human review |
| Fixture corpus | 11 synthetic provisions under 4 fake sources (`TEST_ACT`, `TEST_OLD`, `TEST_FUTURE`, `TEST_UNVERIFIED`); 10 usable, 1 unusable; every text starts `FAKE TEST TEXT:` |
| Fixture `review_status` | Test metadata only; it is not a claim that any real law is verified |
| Corpus version | `d269bfc2722114f8` |
| Ingestion date | 2026-11-08 |

The fixture sources cover current, superseded, future, and unverified cases so
the validity gate can be exercised. They are **not** legal authorities.

Draft text is copied verbatim from the English extracts; only page markers,
outer whitespace and boilerplate gazette headers are removed. The builder never
guesses an official URL, a publisher, or a date, and it refuses to overwrite
drafts that already contain `human_verified` entries. Mechanical segmentation
produced 145 provisions: Act 107, Commission Rules 18, General Rules 5,
E-Commerce Rules 8, Amendment 2, Jurisdiction Rules 5. All six sources remain
`unverified`, so the loader reports 0 usable provisions.

The generated `REVIEWER_CHECKLIST.md` adds a per-source metadata worksheet, a
section-gap report, and mechanical flags (`short_text`, `replacement_char`,
`devanagari`, `starts_lowercase`, `long_page_span`). A flag is a prompt to look
closer, not a legal judgment. The ECR extract contains six Devanagari
enumeration labels (`क, ख, ग, घ, ङ, च`) on otherwise English list items; they are
flagged and preserved verbatim, not silently translated or deleted. Fixing
them requires a human decision or proper OCR.

---

## 5. How to run locally

From the project root in PowerShell:

```powershell
# Offline test suite
.venv\Scripts\python.exe -m pytest -q

# API (fixture mode is the default)
.venv\Scripts\python.exe -m uvicorn ai_lawyer.backend.main:app --host 127.0.0.1 --port 8000

# UI (second terminal)
.venv\Scripts\python.exe -m streamlit run ai_lawyer/frontend/app.py
```

Environment: copy `.env.example` to `.env` if overrides are needed. Defaults:
`CORPUS_MODE=fixture`, `EMBEDDING_BACKEND=hash`, `LLM_PROVIDER=fake`,
`RERANKER_ENABLED=false`. No model download, external API call, or GPU is used
by the demo or tests.

Live smoke checks performed:

```text
GET http://127.0.0.1:8123/health
→ 200, corpus.mode=fixture, fixture_data_not_real_law=true,
  index.loaded=true, chunks=11, llm.provider=fake, database=ok

POST /conversations + POST /conversations/{id}/messages
→ case created, processing_status=completed,
  outcome=formal_grievance_recommended, 5 fixture sources,
  "FIXTURE DATA, NOT REAL LAW" present in the answer

streamlit run ... --server.headless true --server.port 8502
→ HTTP 200 (server boot only; interaction covered separately by headless AppTest)
```

---

## 6. How to rebuild the legal index

```powershell
.venv\Scripts\python.exe -m ai_lawyer.legal_rag.index_manager build --mode fixture
```

Observed output:

```text
CORPUS_MODE=fixture version=d269bfc2722114f8 sources=4 provisions=11 usable=10 unusable=1
index built: chunks=11 embedder=hash-embedder-v1 dir=...\ai_lawyer\vectorstore
```

Artifacts written to `ai_lawyer/vectorstore/` (gitignored):
`faiss.index`, `bm25_tokens.json`, `chunks.json`, `chunk_ids.json`,
`index_manifest.json`.

For real mode, the same command with `--mode real` currently fails closed until
`legal_corpus/sources.json` and `provisions.json` exist and pass validation.

Draft corpus for human review (never used by the engine):

```powershell
.venv\Scripts\python.exe -m ai_lawyer.legal_rag.english_extract
.venv\Scripts\python.exe -m ai_lawyer.legal_rag.draft_ingest `
  --manifest ai_lawyer\legal_corpus\extracted_en\metadata.json `
  --text-dir ai_lawyer\legal_corpus\extracted_en `
  --originals-dir ai_lawyer\legal_corpus\originals `
  --as-of 2026-11-08
```

Extraction observed (English lines only; Hindi lines dropped):

```text
consumer_commission_rules_2020.pdf: pages_kept=10/18 parts=2 latin_share=100.0%
  consumer_commission_rules_2020_1.txt source_id=CCR_2020 pages=9-16 title='Consumer Protection (Consumer Disputes Redressal Commissions) Rules, 2020'
  consumer_commission_rules_2020_2.txt source_id=CCR_2020_2 pages=17-18 title='Consumer Protection (General) Rules, 2020'
consumer_protection_act_2019.pdf: pages_kept=40/40 parts=1 latin_share=100.0%
  consumer_protection_act_2019_1.txt source_id=CPA_2019 pages=1-40 title='Consumer Protection Act, 2019'
ecommerce_amendment_2021.pdf: pages_kept=1/2 parts=1 latin_share=100.0%
  ecommerce_amendment_2021_1.txt source_id=ECR_AMEND_2021 pages=2-2 title='Consumer Protection (E-Commerce) (Amendment) Rules, 2021'
ecommerce_rules_2020.pdf: pages_kept=5/11 parts=1 latin_share=100.0%
  ecommerce_rules_2020_1.txt source_id=ECR_2020 pages=7-11 title='Consumer Protection (E-Commerce) Rules, 2020'
jurisdiction_rules_2021.pdf: pages_kept=1/2 parts=1 latin_share=100.0%
  jurisdiction_rules_2021_1.txt source_id=JUR_2021 pages=2-2 title='Consumer Protection (Jurisdiction of the District Commission, the State Commission and the National Commission) Rules, 2021'
wrote 6 part files
```

The tool prints `latin_share` at one decimal, so the ECR line shows `100.0%`.
The raw count for that part is 13,848 Latin letters and 6 Devanagari letters,
i.e. `0.99957`; those six labels are kept and flagged.

Draft build observed:

```text
draft sources=6 provisions=145 review_status=unverified citation_ready=false
  CCR_2020: pages=16 sections=18 ascii=99.9% letters=78.5% latin_share=100.0% ocr_risk=low
  CCR_2020_2: pages=18 sections=5 ascii=99.5% letters=75.0% latin_share=100.0% ocr_risk=low
  CPA_2019: pages=40 sections=107 ascii=99.9% letters=79.1% latin_share=100.0% ocr_risk=low
  ECR_AMEND_2021: pages=2 sections=2 ascii=99.8% letters=70.5% latin_share=100.0% ocr_risk=low
  ECR_2020: pages=11 sections=8 ascii=99.8% letters=78.8% latin_share=100.0% ocr_risk=low
  JUR_2021: pages=2 sections=5 ascii=99.5% letters=74.1% latin_share=100.0% ocr_risk=low
```

The draft builder also rounds to one decimal. ECR is the only part with the six
Devanagari labels; the checklist flags the two affected provisions
(`ECR_2020_P004`, `ECR_2020_P005`).

Artifacts: `legal_corpus/draft/{draft_sources.json,draft_provisions.json,
sources_review.csv,provisions_review.csv,draft_manifest.json,DRAFT_REVIEW.md,
REVIEWER_CHECKLIST.md}`.
They are generated, gitignored, and every source is `unverified`, so the
loader reports 0 usable provisions.

---

## 7. How to run evaluation

```powershell
.venv\Scripts\python.exe -m ai_lawyer.evaluation.run_retrieval_eval
.venv\Scripts\python.exe -m ai_lawyer.evaluation.run_behavior_eval
```

- Corpus: fixture, version `d269bfc2722114f8`.
- Retrieval split: 8 development rows + 8 test rows (`evaluation/dataset/`).
- K values: 5, 10, 20.
- Retrieval modes: E1 FAISS dense, E2 BM25 sparse, E3 hybrid + RRF, E5
  verification. E4 reranker: NOT RUN.
- Metrics: `precision_at_k` (fixed K denominator), `recall_at_k` (essential
  set; N/A when empty), `mrr_at_k` (first grade >= 2), `ndcg_at_k`
  (`2^grade - 1`, `log2(rank+1)`; N/A when ideal DCG is 0), applicability
  precision/recall, false-acceptance rate, abstention count.
- Behaviour: 17 unedited cases B01-B17 plus one derived B09 fallback check.

All outputs are labelled `FIXTURE DATA, NOT REAL LAW`.

---

## 8. Actual results

These are the metrics from the runs above. They are **fixture-only** and must
not be reported as real legal retrieval quality.

### 8.1 Retrieval at K=5

| Mode | Split | n | P@5 | R@5 | MRR@5 | nDCG@5 | Recall N/A |
|---|---|---:|---:|---:|---:|---:|---:|
| E1 dense | development | 8 | 0.2250 | 1.0000 | 0.8063 | 0.8014 | 1 |
| E1 dense | test | 8 | 0.2000 | 1.0000 | 0.9000 | 0.9194 | 1 |
| E2 sparse | development | 8 | 0.2250 | 1.0000 | 0.8375 | 0.8436 | 1 |
| E2 sparse | test | 8 | 0.2000 | 1.0000 | 0.9063 | 0.9244 | 1 |
| E3 hybrid | development | 8 | 0.2250 | 1.0000 | 0.8167 | 0.8239 | 1 |
| E3 hybrid | test | 8 | 0.2000 | 1.0000 | 0.9063 | 0.9244 | 1 |

At K=10 the precision values halve to 0.1125 and at K=20 to 0.05625 for the
development split (0.1000 and 0.0500 for the test split), because the fixed-K
denominator is used. Recall, MRR, and nDCG do not change at K>=5 for these rows.
Full values: `evaluation/results/retrieval_summary.csv`.

**Honest reading:** recall@5 is 1.0 for every mode on both splits, but each row
has one essential provision, so recall is easy to saturate. The development
split shows E2 (0.8375) > E3 (0.8167) > E1 (0.8063) on MRR. The hybrid is not
the best configuration on these 8 development rows, and no tuning on the test
split was performed. Precision falls mechanically when K rises; it is not a
quality signal on an 11-provision corpus.

### 8.2 Verification (E5)

| Split | n | Mean accepted | Precision | Recall | MRR | nDCG | Applicability precision | Applicability recall | False acceptance | Abstentions |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| development | 8 | 3.7500 | 0.3512 | 1.0000 | 1.0000 | 0.9884 | 1.0000 | 0.7500 | 0.0000 | 0 |
| test | 8 | 4.3750 | 0.2677 | 1.0000 | 0.8073 | 0.8631 | 1.0000 | 1.0000 | 0.0000 | 0 |

The verification "precision" is computed at the number of accepted provisions,
not at a fixed K, so it is not directly comparable to P@K. Applicability
precision is 1.0 on all 16 fixture rows and test recall is 1.0, but development
recall is 0.75; this is not evidence of real-world calibration. Development
applicability recall 0.75 means at least one labelled-not-applicable case was
not detected; row-level data is in `raw_outputs/retrieval_raw.jsonl`.

### 8.3 Behaviour suite

**17/17 core cases PASS; 18/18 checks PASS** including the derived
`B09_missing_corpus` fallback.

| Check | Observed |
|---|---|
| B01 delayed refund, dates known | `formal_grievance_recommended` |
| B02 delayed refund, no contact | `informal_resolution_recommended`; support_request draft |
| B03 inside promised timeline | `no_legal_action_currently_required`; no contradictory questions |
| B04 approved, no dates/evidence | `needs_more_information`; exactly 2 questions |
| B05 approved, with document | `formal_grievance_recommended`; `refund_initiated_date` and `refund_amount` document-supported; `support_contact_date` user-reported |
| B06 refund denied | `formal_grievance_recommended` |
| B07 partial refund | `informal_resolution_recommended`; support_request draft |
| B08 responsibility ambiguity | `formal_grievance_recommended`; no blame assignment |
| B09 grievance attempted | `formal_legal_proceedings_may_be_justified`; required corpus tag satisfied |
| B09 missing corpus (derived) | `needs_more_information`; removed provision not cited |
| B10 missing key dates | `needs_more_information`; exactly 2 questions |
| B11 tenancy | `out_of_scope`; no draft, no legal sources |
| B12 salary | `out_of_scope`; no draft, no legal sources |
| B13 invented section bait | `needs_more_information`; no unsupported section numbers |
| B14 prompt injection in upload | `informal_resolution_recommended`; forbidden text absent |
| B15 two orders | `needs_more_information`; split question, no case |
| B16 contradictory documents | `needs_more_information`; 2 conflict flags; both 10 October and 20-10-2026 shown |
| B17 resolved then reopened | `formal_grievance_recommended`; status `reopened`; events include `case_created`, `case_resolved`, `case_reopened` |

Results file: `evaluation/results/behavior_summary.csv`;
manifest: `evaluation/results/behavior_manifest.json`.

The Streamlit client has 2 headless `AppTest` interactions (`2 passed in
2.06s`): one renders the fixture banner, submits a chat message, and checks the
response and editable draft; the other checks offline startup. They are not
real-browser tests.

---

## 9. Raw outputs

| Artifact | Path |
|---|---|
| Retrieval raw records (160 lines) | `ai_lawyer/evaluation/raw_outputs/retrieval_raw.jsonl` |
| Behaviour raw payloads (18 JSON files) | `ai_lawyer/evaluation/raw_outputs/behavior/<test_id>.json` |
| Retrieval summary | `ai_lawyer/evaluation/results/retrieval_summary.csv` |
| Verification summary | `ai_lawyer/evaluation/results/verification_summary.csv` |
| Behaviour summary | `ai_lawyer/evaluation/results/behavior_summary.csv` |
| Retrieval manifest | `ai_lawyer/evaluation/results/run_manifest.json` |
| Behaviour manifest | `ai_lawyer/evaluation/results/behavior_manifest.json` |
| Failure analysis | `ai_lawyer/evaluation/failure_analysis.md` |
| Index build stderr | `ai_lawyer/evaluation/raw_outputs/index_build_stderr.log` |

The raw JSON payloads are written directly from the orchestrator response and
are not edited. The only known process deviation is that the first failing
behaviour run's JSON files were overwritten by the passing rerun; the observed
failure text is preserved in `failure_analysis.md`.

---

## 10. Test results

```text
.venv\Scripts\python.exe -m pytest -q
141 passed, 1 warning in 8.60s
```

- Python: 3.12.14 on Windows.
- Warning: Starlette/httpx `TestClient` deprecation; unrelated to product logic.
- Network/model use in tests: none.
- Breakdown: 9 integration pipeline, 2 Streamlit `AppTest`, 6 API, 4 chunker,
  8 contracts, 9 corpus loader, 4 dataset loader, 5 documents, 21 draft ingest,
  27 engine, 11 English extract, 8 index manager, 7 metrics, 5 RRF,
  15 services = 141.
- Earlier in the session the suite was 105 passed before the final BM25
  tokenizer test was added, 106 before the draft-ingest tests were added, 121
  before the English-extraction and manifest tests were added, 134 before the
  reviewer-checklist tests and 139 before the Streamlit `AppTest` file. The run
  above is the authoritative final count.

---

## 11. Limitations and failures

Detailed observed failures and fixes: `evaluation/failure_analysis.md`.

1. **Real-law use is blocked.** A draft corpus exists (6 sources, 145
   provisions), but no reviewed `sources.json` / `provisions.json` exists and no
   real source is `human_verified`. Candidate titles, dates, departments and
   gazette IDs still need source-document confirmation. Real mode raises
   `CorpusValidationError`.
2. **All metrics are fixture-only.** 11 synthetic provisions, 16 retrieval rows,
   `HashEmbedder`, and a deterministic lexical `FakeLLM`.
3. **E4 reranker not run.** The wrapper exists but the optional model is not
   installed and `RERANKER_ENABLED=false`.
4. **Streamlit is tested headlessly, not in a real browser.** Two Streamlit
   `AppTest` cases drive the app script and a submitted chat message with fake
   HTTP responses. They are not browser automation and do not test real network
   behaviour.
5. **Retrieval sample is still small.** Eight development and eight test rows,
   one relevant provision each; precision@K is mechanically diluted by K.
6. **No claim-level entailment.** Guards check citations, phrases, dates, and
   draft facts, but there is no LLM entailment verifier over every sentence.
7. **No OCR.** Scanned PDFs are not supported; the Hindi text layer was dropped
   rather than repaired because its font mapping is broken. Six Devanagari
   enumeration markers remain in the ECR English extract; they are preserved and
   flagged for review, not translated or silently deleted.
8. **No auth or multi-tenancy.** `X-User-Id` is a demo header, not an
   authentication mechanism. The app is a local demo.
9. **Repository has no remote.** A local git repository exists with four
   baseline commits plus the final documentation commit; nothing was pushed,
   merged, or deployed.
10. **First failing behaviour outputs were overwritten.** See the process
    deviation in `failure_analysis.md`.

---

## 12. Security status

- **Exposed token:** the reference notebook reportedly contains a hardcoded
  Hugging Face token. I did not open, copy, print, or reuse it. **Revocation and
  Git-history cleaning are the user's responsibility and are NOT verified.**
- **This project:** `.env` is gitignored; no API key is configured; tests and
  evaluation run with `FakeLLM` and make no external calls. Provider adapters
  never log headers or keys.
- **API:** CORS is restricted to `ALLOWED_ORIGINS` (default
  `http://localhost:8501`); errors use a safe envelope without tracebacks;
  upload size and message length are capped; requests have a timeout;
  correlation ids are returned.
- **Evidence:** uploaded files are stored locally under `ai_lawyer/data/` with
  hashed names and type/size checks. This is a local demo, not a secure
  multi-user service. Do not host it publicly with private evidence.
- **No secrets in repository artifacts:** the evaluation logs contain only the
  fixture warning and run output.

---

## 13. Next steps

Only what is needed to move from this fixture prototype to a safer, real system:

1. Supply `legal_corpus/sources.json` and `provisions.json` with official URLs,
   versions, effective dates, and `review_status: unverified` initially.
2. Run `python -m ai_lawyer.legal_rag.english_extract` and
   `python -m ai_lawyer.legal_rag.draft_ingest --manifest ...`, then review
   `provisions_review.csv` / `sources_review.csv` and confirm the candidate
   titles, dates, departments and gazette IDs against official copies. Do not
   set `review_status: human_verified` until a named reviewer has checked the
   text and metadata.
3. Re-run the corpus validator and inspect every dangling reference, proviso,
   exception, and definition.
4. Replace `HashEmbedder` with a locally installed embedding model, rebuild the
   index, and record the model id and manifest hash.
5. Run E1/E2/E3/E5 on a human-labelled real development/test split; keep the
   test split untouched; report per-query results and N/A counts.
6. Install and calibrate the reranker on development data only; then run E4.
7. Add a claim-level entailment verifier and test it against supported and
   unsupported claims.
8. Add real-browser tests for the Streamlit UI in addition to the headless
   `AppTest` cases, and an end-to-end API test with uploads.
9. Add authentication, per-user isolation, retention rules, and encrypted
   evidence storage before any shared deployment.
10. Only after the baseline is stable: OCR, RAGAS, Jev, snapshots, and the
    National Consumer Helpline / Consumer Commission templates.

---

## 14. v4 coverage table (stretch items)

| v4 item | Status | Notes |
|---|---|---|
| T2-C reranker + calibration, E4/E5 | DESIGN_ONLY / NOT RUN | Wrapper exists (`legal_rag/reranker.py`); model absent; no calibration; E5 verification ran without a reranker |
| T2-B claim extractor + LLM entailment | DESIGN_ONLY | Current guards are citation/phrase/date/draft-fact checks, not sentence-level entailment |
| T2-F National Consumer Helpline and Consumer Commission drafts | DESIGN_ONLY | Only `support_request` and `formal_grievance` templates exist; both require accepted provisions |
| T2-E snapshots and archive checks | DESIGN_ONLY | `snapshot_every_n_events` setting exists; no snapshot writer/restore path |
| T2-A corpus parser (propose-only) | PARTIAL | `legal_rag/english_extract.py` extracts English parts and candidate metadata; `legal_rag/draft_ingest.py` produces review-only, unverified drafts; no review UI and no automatic promotion |
| T2-D OCR behind `OCRProvider` | DESIGN_ONLY | Text extraction only; no OCR provider |
| T2-H RAGAS adapter | DESIGN_ONLY | Not installed; no adapter |
| T3-A Jev adapter | DESIGN_ONLY | No interface or fake implemented |

No stretch item was allowed to delay evaluation, the README, or the report.

---

## 15. Merge log and cut list

### Merge log

A local git repository was initialized at the workspace root on 2026-11-08. It
has an initial commit `6355475` plus the docs refresh `6650ca8`, the local
baseline `38d71e7`, the test output fix `efd05f8`, and the final documentation
commit; run `git log --oneline` for the full local history. There is no remote,
branch, merge, push, or deployment log. `reference/` and the user's original
`ai-lawyer/` are gitignored and unmodified. The logical change set is:

| Area | Change |
|---|---|
| Reference project | Untouched |
| New package | `ai_lawyer/` added (config, contracts, corpus fixtures, RAG, engine, backend, documents, frontend, evaluation, tests, docs) |
| Draft corpus tooling | `legal_rag/english_extract.py` + `legal_rag/draft_ingest.py` and their tests; generated `legal_corpus/extracted_en/` and `legal_corpus/draft/` (draft dir gitignored); checklist and mechanical flags included |
| Evaluation | Expanded to 16 fixture retrieval rows, added E5 recomputation, and 2 Streamlit `AppTest` interactions; raw outputs regenerated |
| Corpus loader | `validate_and_build` gained `warn_unusable` (default unchanged) so draft validation stays quiet |
| Root config | `.env.example`, `.gitignore`, `requirements.txt`, `pytest.ini` |
| Requirements | Pins corrected to the installed `.venv` versions on 2026-11-08 |
| Generated artifacts | `ai_lawyer/vectorstore/`, `ai_lawyer/data/`, evaluation outputs (gitignored or evidence-only) |

### Cut list

Deliberately not built, with reasons:

| Cut item | Reason |
|---|---|
| Real corpus ingestion / source verification | No reviewed sources; fabricating them would violate the brief |
| E4 cross-encoder reranker | Optional model not installed; must not block evaluation |
| Claim extractor + LLM entailment | Time; current guards are narrower than sentence-level verification |
| National Consumer Helpline / Consumer Commission drafts | Requires accepted provisions and reviewed templates |
| Snapshots and archive checks | Optimisation, not required for the narrow MVP |
| Corpus parser (propose-only) | Draft generation is built and tested; PDF re-parsing and reviewer promotion remain unbuilt |
| OCR | Scanned PDFs out of scope for this run |
| RAGAS adapter | Stretch item; no real labelled QA set |
| Jev adapter | Stretch experiment only |
| Auth, multi-tenancy, public deployment | Local demo only; security note applies |
| Streaming, multilingual UI, voice | Out of scope |
| Full 150-question set | Only the 16 fixture retrieval rows and 17 behaviour cases exist |
| LLM-judge evaluation | Would add variability without a validated rubric |

---

**Final status:** fixture-mode MVP complete and tested; a review-only draft
corpus is generated but real-law capability remains blocked until a human
reviews and verifies it. Every cited text in the demo is synthetic and
labelled as such.
