# AI Consumer Refund Dispute Assistant (MVP)

**Status: fixture-only demo. `FIXTURE DATA, NOT REAL LAW`. Not legal advice.**
The default corpus contains 11 synthetic provisions. The five supplied PDFs were
extracted into six English-only `.txt` parts and review-only draft JSON, but no
reviewed `sources.json` / `provisions.json` exists and no real source is
`human_verified`, so real mode fails closed.

This is the Kuku Problem 2 implementation. It asks a consumer what happened,
extracts only facts present in the user's text or uploads, retrieves provisions
from a verified corpus, applies deterministic applicability and outcome rules in
Python, and produces a plain-English assessment plus an editable draft. The LLM
cannot choose the outcome and cannot invent citations.

## Quick start (Windows PowerShell)

```powershell
# 1. Tests (offline; no model download, no network, no GPU)
.venv\Scripts\python.exe -m pytest -q

# 2. API (fixture mode is the default)
.venv\Scripts\python.exe -m uvicorn ai_lawyer.backend.main:app --host 127.0.0.1 --port 8000

# 3. UI (in a second terminal)
.venv\Scripts\python.exe -m streamlit run ai_lawyer/frontend/app.py
```

Open `http://localhost:8501`. The red banner `FIXTURE DATA, NOT REAL LAW` is
shown whenever the backend reports fixture mode. The API is at
`http://localhost:8000`; `GET /health` shows component status without secrets.

## Evaluation commands

```powershell
.venv\Scripts\python.exe -m ai_lawyer.evaluation.run_retrieval_eval
.venv\Scripts\python.exe -m ai_lawyer.evaluation.run_behavior_eval
```

Outputs:

- `evaluation/raw_outputs/retrieval_raw.jsonl`
- `evaluation/raw_outputs/behavior/<test_id>.json` (one unedited payload per case)
- `evaluation/results/retrieval_summary.csv`
- `evaluation/results/verification_summary.csv`
- `evaluation/results/behavior_summary.csv`
- `evaluation/results/run_manifest.json`
- `evaluation/results/behavior_manifest.json`

All evaluation artifacts carry `FIXTURE DATA, NOT REAL LAW`.

## Draft corpus for human review (real-mode preparation)

The five PDFs are bilingual Gazette of India notifications: the Hindi text
layer uses a legacy font with a broken `ToUnicode` map, while the English layer
is clean. The extractor keeps English-majority lines verbatim, splits the two
notifications that share one PDF, and writes review-only `.txt` parts:

```powershell
.venv\Scripts\python.exe -m ai_lawyer.legal_rag.english_extract
.venv\Scripts\python.exe -m ai_lawyer.legal_rag.draft_ingest `
  --manifest ai_lawyer\legal_corpus\extracted_en\metadata.json `
  --text-dir ai_lawyer\legal_corpus\extracted_en `
  --originals-dir ai_lawyer\legal_corpus\originals
```

The first command writes `legal_corpus/extracted_en/` (6 parts, 100% Latin) and
`metadata.json` with candidate titles, dates, departments and gazette IDs quoted
from the documents. The second writes `legal_corpus/draft/` (gitignored) and
never creates the files real mode loads:

- `draft_sources.json` / `draft_provisions.json` — schema-valid drafts.
- `sources_review.csv` / `provisions_review.csv` — review worksheets.
- `draft_manifest.json` — counts and per-document OCR quality.
- `DRAFT_REVIEW.md` — the review procedure.

Current draft totals: **6 sources, 145 provisions** — Act 107, Commission Rules
18, General Rules 5, E-Commerce Rules 8, Amendment 2, Jurisdiction Rules 5.
Every draft source is `review_status: unverified`, so all provisions are
unusable and cannot be cited. All six parts are 100% Latin and low OCR risk.
`publisher`, `official_url`, `published_date` and effective dates remain blank
until a human checks them against an official copy. Nothing is copied to
`sources.json` / `provisions.json` automatically, and the agent never sets
`review_status: human_verified`.

## What is implemented

- FastAPI service with conversations, multipart messages/uploads, cases, and
  document generation.
- SQLite persistence for users, conversations, messages, facts, evidence,
  cases, events, drafts, and retrieval logs.
- FAISS dense index + BM25 sparse index + reciprocal rank fusion, provision
  expansion, optional reranker (disabled by default).
- Deterministic verification: corpus validity, source currency, applicability,
  relevance, acceptance, retries, abstention, citation/phrase/date guards.
- Fact extraction with provenance, date normalisation, conflict flags, case
  matching, correction supersession, and resolved-case reopening.
- Assessment rules R0-R7 in Python; the LLM's proposed outcome is logged but
  never wins.
- Editable `support_request` and `formal_grievance` drafts with fact-store and
  citation validation.
- Streamlit client with escaped rendering, fixture banner, facts/sources/
  assessment/draft panels, and no send button.

## What is not implemented

- Real legal corpus ingestion, source verification, or real-law citations.
  **BLOCKED** until the user reviews the generated draft corpus and supplies
  `ai_lawyer/legal_corpus/sources.json` and `provisions.json`. Draft generation
  exists; four of five extracted texts need re-extraction first.
- Cross-encoder reranking and E4 (optional model not installed).
- Claim-level LLM entailment, National Consumer Helpline / Consumer Commission
  draft templates, corpus snapshots/archive checks, OCR, RAGAS, and Jev.
- Authentication, multi-tenant isolation, production deployment, or public
  hosting. The demo-user header is not an auth mechanism.
- Any claim of legal correctness. This is general information and a draft for
  review, not legal advice.

## Project layout

```text
ai_lawyer/
  config/            typed settings, lazy model factories
  contracts/         Pydantic models, protocols, fakes, errors, ids
  legal_corpus/      fixture corpus + supplied PDFs/originals (gitignored)
  legal_rag/         corpus loader, draft ingest, chunker, index, RRF, planner,
                     retriever
  legal_engine/      validity, applicability, relevance, acceptance, guards,
                     assessment, decision controller, reasoning
  backend/           FastAPI app/routes, services, SQLite schema/repo
  documents/         draft generator, validator, Jinja templates
  frontend/          Streamlit demo client
  evaluation/        metrics, datasets, harnesses, raw outputs, failure analysis
  tests/             134 unit/integration tests (offline)
  docs/              reuse notes and final report
```

## Honest status

| Area | Status |
|---|---|
| Fixture demo end-to-end | IMPLEMENTED_AND_TESTED |
| Draft corpus ingestion (review-only, unverified) | IMPLEMENTED_AND_TESTED |
| Real-law use | BLOCKED (drafts exist; no human-reviewed corpus) |
| Optional LLM/embedder/reranker providers | IMPLEMENTED_NOT_TESTED (no network/model) |
| Streamlit UI | IMPLEMENTED_NOT_TESTED (server boots and serves HTTP 200; no browser interaction test) |
| OCR, claim entailment, RAGAS, Jev, snapshots | DESIGN_ONLY |

See `docs/FINAL_REPORT.md` for exact test/evaluation totals and
`evaluation/failure_analysis.md` for observed failures.
