# Project Status and Handoff

**Project:** AI consumer refund dispute assistant (India, e-commerce)
**Date:** 2026-11-08
**Scope of this document:** what is built and verified, what is not, and the
order in which to finish it.
**Authoritative for:** current state. `README.md` and `docs/FINAL_REPORT.md`
describe earlier checkpoints and are stale in places.

---

## 0. Verdict in one paragraph

The **product** works end to end in fixture mode: API, UI, retrieval, guards,
deterministic outcomes, drafts, persistence, and 181 offline tests. The
**legal corpus pipeline** is built and has produced a real 8-source /
149-provision staging corpus from 13 official Government of India documents.
But the **real dataset is not ready**: 0 of 149 provisions are human-verified,
0 have conditions, `sources.json` / `provisions.json` do not exist, and real
mode fails closed by design. No model, embedder, reranker, OCR engine, or GPU
has been used yet.

---

## 1. Status at a glance

Legend: **DONE** implemented and tested · **PARTIAL** built, not validated on
real inputs · **BLOCKED** needs a human artifact or decision · **NOT STARTED**

| Area | Status | Evidence |
|---|---|---|
| Fixture demo, end to end | **DONE** | 181 tests; behavior eval 18/18 PASS |
| RAG pipeline (dense + BM25 + RRF) | **DONE** | E1–E3 on fixture data |
| Reference-stack parity (boost, compression) | **DONE** | `docs/RAG_PARITY.md`, calibration tests |
| Deterministic R0–R7 outcomes | **DONE** | behavior cases B01–B17 |
| Guards (citation, phrase, date, validity, acceptance) | **DONE** | unit + behavior tests |
| Official documents downloaded | **DONE** | 13 PDFs, hashes verified |
| Provenance manifest | **DONE** | `official/manifest.json` |
| English extraction + integrity guard | **DONE** | 17 extraction tests |
| Curated staging corpus | **DONE** | 8 sources / 149 provisions |
| Provenance fields + real-mode gate | **DONE** | 8 acceptance tests + 7-scenario E2E check |
| Human review of provisions | **BLOCKED** | 0 / 149 verified |
| Structured conditions / provisos | **BLOCKED** | 0 / 149 |
| Runtime `sources.json` / `provisions.json` | **BLOCKED** | files absent |
| 2026 E-Commerce amendment ingestion | **BLOCKED** | text layer loses all digits |
| CPA 2020 corrigendum ingestion | **BLOCKED** | scanned, empty text layer |
| Post-2021 CPA amendment check | **BLOCKED** | India Code text stops 2021-09-17 |
| Real embeddings (BGE) | **PARTIAL** | backend exists, model not installed |
| Reranker / E4 | **NOT STARTED** | model not installed, never run |
| Real open-weight LLM | **NOT STARTED** | no Ollama, no model |
| Real-corpus evaluation dataset | **NOT STARTED** | only fixture cases exist |
| Kaggle 7B batch evaluation | **NOT STARTED** | depends on real E2E |
| Auth / encryption / DPDP / deployment | **NOT STARTED** | deliberately deferred |

---

## 2. What is done

### 2.1 Runtime product

- **FastAPI service**: conversations, multipart messages and uploads, cases,
  retrieval logging, document generation.
- **SQLite persistence** for users, conversations, messages, facts, evidence,
  cases, events, drafts, retrieval logs.
- **Streamlit client**: fixture banner, facts/sources/assessment/draft panels,
  escaped rendering, no send button.
- **Fixture mode is the default** and visibly labelled `FIXTURE DATA, NOT REAL
  LAW`. Fixture corpus: 4 sources, 11 provisions, 10 usable.

### 2.2 Retrieval and RAG parity

Stages match the reference stack: chunking, dense index, BM25, RRF, optional
boost, optional rerank, prompt assembly.

- `legal_rag/boosting.py` — explicit-reference boost (`+0.5`) and qualifier
  **tie-break only**. An additive qualifier bonus was tested and rejected: it
  was larger than the RRF spread and cut hybrid MRR 0.8167 → 0.4833.
- `legal_rag/compressor.py` — contiguous **verbatim prefix** only. If a
  proviso or exception would not fit, the provision is returned unchanged.
- `legal_rag/retriever.py` — dense + sparse + RRF (+ boost) (+ rerank),
  provision consolidation.
- `legal_engine/reasoning.py`, `backend/services/orchestrator.py`,
  `evaluation/run_retrieval_eval.py` wired to the same stages.

Both boost and compression are **off by default** so fixture results stay
reproducible.

### 2.3 Legal reasoning and safety

- Deterministic **R0–R7** assessment in Python. The LLM may propose an outcome
  but never wins; `Assessment.llm_proposed_outcome` records it.
- Relevance is graded by the LLM; **outcome is never**.
- Guards: source validity (current/superseded/future/uncertain), applicability,
  acceptance policy, citation validator, phrase guard, date guard, retry policy,
  abstention.
- If relevance grading fails schema twice, the request is rejected — the system
  never guesses.
- Future and superseded instruments are rejected for the wrong as-of date.

### 2.4 Official corpus: retrieval and provenance

Downloaded from the Department of Consumer Affairs
(`consumeraffairs.gov.in/pages/consumer-protection-acts`) plus one India Code
bitstream. Source files are in `legal_corpus/official/originals/`.

| ID | Instrument | Dated | In force | Status |
|---|---|---|---|---|
| CPA_2019 | Act 35/2019 | 2019-08-09 | 2020-07-20 | current |
| CPA_2019_CONSOLIDATED | India Code text | 2019-08-09 | — | current |
| CPA_2019_CORRIGENDUM | Gazette No. 27 | 2020-04-24 | 2020-04-24 | current, scanned |
| CPA_2019_COMMENCEMENT_1 | S.O. 2351(E) | 2020-07-15 | 2020-07-20 | current |
| CPA_2019_COMMENCEMENT_2 | S.O. 2421(E) | 2020-07-23 | 2020-07-24 | current |
| CCR_2020 + General Rules 2020 | G.S.R. 448(E), 449(E) | 2020-07-15 | 2020-07-20 | current |
| CCR_2022_AMENDMENT | G.S.R. 892(E) | 2022-12-20 | 2022-12-21 | superseded |
| CCR_2023_AMENDMENT | G.S.R. 606(E) | 2023-08-17 | 2023-08-17 | current |
| ECR_2020 | G.S.R. 462(E) | 2020-07-23 | 2020-07-23 | current |
| ECR_2020_CORRIGENDUM | G.S.R. 488(E) | 2020-08-04 | not stated | current |
| ECR_2021_AMENDMENT | G.S.R. 328(E) | 2021-05-17 | 2021-05-17 | current |
| ECR_2026_AMENDMENT | G.S.R. 789(E) | 2026-09-09 | 2027-01-01 | **future** |
| JUR_2021 | G.S.R. 912(E) | 2021-12-30 | 2021-12-30 | current |

All **13 hashes and byte counts verified** against the files. A duplicate PDF
link for JUR_2021 is recorded and ingested once. The five pre-existing
originals are byte-identical to their DCA downloads.

### 2.5 Extraction and ingestion

- `english_extract.py` keeps English-majority pages, drops non-Latin lines
  verbatim, splits multi-instrument PDFs, and writes a metadata manifest.
- `text_integrity_flags()` detects silent number loss: missing G.S.R. number,
  gazette number, dated day, effective date, commencement date, or any digits.
  Covered by 17 tests.
- `draft_ingest.py` builds schema-valid drafts, review CSVs, a per-source
  checklist, and a manifest. Nothing it writes is citation-ready.
- **Curated staging output**: `official/draft_curated/` — 8 sources,
  149 provisions, all `review_status: unverified`, `citation_ready: false`.
- An uncurated run (`official/draft/`, 14 sources / 266 provisions) is kept for
  comparison only and must not be reviewed.

Excluded from ingestion, with reasons in `official/ingestion_plan.json`:
commencement notifications (metadata, not provisions), the ECR 2020
corrigendum (Devanagari labels only), the 2026 amendment (blocked text layer),
the India Code alternate text (cross-check only), and the duplicate JUR PDF.

### 2.6 Review safety

- `Source` and `Provision` carry `reviewed_by` and `reviewed_at`.
- `legal_rag/corpus_acceptance.py` runs from `load_corpus()` only for
  `CORPUS_MODE=real`. It refuses to start unless:
  - at least one source is `human_verified`;
  - every verified source has publisher, official URL, publication date,
    document hash, reviewer, review date, and a non-`uncertain` version status;
  - every provision under a verified source has its own reviewer and review
    date;
  - every condition under a verified provision is human-reviewed.
- A partially reviewed corpus is allowed: unverified entries load but stay
  uncitable.
- Verified end to end on the real staging files (7 scenarios: reject, reject,
  reject, accept, reject, accept, fixture unaffected).

### 2.7 Evaluation

| Experiment | State | Result (fixture, dev / test) |
|---|---|---|
| E1 dense FAISS | RUN | MRR 0.806 / 0.900 |
| E2 sparse BM25 | RUN | MRR 0.838 / 0.906 |
| E3 hybrid RRF | RUN | MRR 0.817 / 0.906 |
| E4 reranker | **NOT RUN** | model not installed |
| E5 verification | RUN | 0 false acceptances; behaviour 18/18 PASS |

Results in `evaluation/results/boost_off/` and `boost_on/`.

### 2.8 Tests and docs

- **181 tests pass** offline: no model download, no network, no GPU.
- 19 test files; 64 non-test Python modules.
- Docs: `docs/PHASE0_DECISIONS.md`, `docs/RAG_PARITY.md`,
  `legal_corpus/official/RETRIEVAL_NOTES.md`, `docs/FINAL_REPORT.md`,
  `docs/reuse_notes.md`, this file.

---

## 3. What is still to do

### Phase A — Make the real dataset (user-owned, highest priority)

1. **Confirm post-2021 CPA amendments.** India Code stops at 2021-09-17.
   Check the Jan Vishwas Act, 2023 and later Acts. If any apply, obtain the
   gazette copy. Without this the Act cannot be `human_verified`.
2. **OCR or transcribe two blocked documents**:
   - ECR 2026 amendment (G.S.R. 789(E)): recover G.S.R. number, dates, rule
     numbers, thresholds.
   - CPA 2020 corrigendum: transcribe the single page, or apply the correction
     by hand and record where.
3. **Review the 149 provisions** in this order:
   - `ECR_2020` + `ECR_2021_AMENDMENT` (10 provisions) — the refund law;
   - `CPA_2019` §2 definitions, §2(11) unfair trade practice, §35, §38–39;
   - `CC_RULES_2023_AMENDMENT` (current fee table; skip 2022);
   - `JUR_2021` (5);
   - `CC_RULES_2020` (23 across two parts) — only what the flow cites.
4. **Author structured conditions/provisos/exceptions** for the core refund
   provisions, then mark each `human_review_status: reviewed`.
5. **Fill source metadata**: publisher, official URL, publication date,
   effective dates, document hash, reviewer, review date.
6. **Write `legal_corpus/sources.json` and `provisions.json`** from approved
   entries only; set `review_status: human_verified` on what you personally
   checked.
7. **Pass the accept gate**: `CORPUS_MODE=real` must load with the expected
   usable count and no acceptance errors.

**Definition of done for Phase A:** real mode starts, every citable provision
has text + provenance + reviewer, every condition is reviewed, and retrieval
returns only verified provisions.

### Phase B — Real-retrieval validation

8. Rebuild the index with `CORPUS_MODE=real`.
9. Replace fixture evaluation cases with real labelled cases (development and
   held-out test).
10. Re-run E1–E3 and behaviour evaluation; record results under a new
    `evaluation/results/real_*` folder.
11. Add a future-law case that pairs a pre-2027 dispute with the 2026
    amendment and proves `not_yet_effective` end to end.

### Phase C — Real models

12. Install Ollama and a 3B GGUF model; run the local CPU spike using the
    OpenAI-compatible provider (no new adapter).
13. Optionally install `torch` + `sentence-transformers` (~2.5 GB) and
    `BAAI/bge-large-en-v1.5`; re-run retrieval with real embeddings.
14. Optionally install the BGE reranker (~1.1 GB); run E4 for the first time.
15. Build the Kaggle 7B–8B 4-bit batch-evaluation notebook after real E2E.

### Phase D — Deferred until explicitly requested

16. Authentication, multi-tenant isolation, encryption at rest, DPDP
    compliance, public deployment, monitoring, backups.
17. Claim-level entailment, NCH/Commission draft templates, corpus snapshots,
    RAGAS/Jev.

---

## 4. Hard blockers (real law cannot ship until these clear)

| Blocker | Why it stops real law |
|---|---|
| 0 / 149 provisions verified | Nothing is citable; engine would answer "no law" |
| 0 structured conditions | R0–R7 cannot evaluate real applicability |
| No `sources.json` / `provisions.json` | Real mode has nothing to load |
| Missing source metadata (8/8) | Provenance gate rejects the corpus |
| 2026 amendment unreadable | Future refund/return disclosures missing |
| CPA post-2021 status unknown | Possible stale Act text |
| No real evaluation cases | Metrics would still be fixture-only |
| No real model installed | Only `FakeLLM` has run |

---

## 5. Honest limitations

- **All metrics are fixture-only.** Recall 1.0 is an artefact of an 11-provision
  corpus, not evidence of retrieval quality.
- **The 2026 amendment's numbers are visual-only.** The text layer drops every
  operative digit; the manifest values were read from the rendered page and
  remain unverified until OCR/hand transcription.
- **No OCR engine is installed.** Both blocked documents stay blocked.
- **E4 has never run.** The reranker is disabled and the model is absent.
- **Embeddings are hashed by default**, not BGE. The real embedder was never
  benchmarked here.
- **No model has run.** All LLM behaviour so far is `FakeLLM`.
- **No authentication.** The demo-user header is not auth.
- **All new work is uncommitted.** Latest commit is `11f5bd9`; every file added
  this session is untracked or modified.
- **`corpus_manifest.json` regenerates `generated_at` on each load**, so its
  timestamp is not stable evidence.

---

## 6. Where things live

| Path | Purpose |
|---|---|
| `ai_lawyer/legal_corpus/official/RETRIEVAL_NOTES.md` | Source provenance, amendment chains, blockers |
| `ai_lawyer/legal_corpus/official/manifest.json` | 13 documents, hashes, URLs, dates, flags |
| `ai_lawyer/legal_corpus/official/ingestion_plan.json` | Included / excluded documents |
| `ai_lawyer/legal_corpus/official/draft_curated/` | Review queue (149 provisions) |
| `ai_lawyer/legal_corpus/official/draft_curated/provisions_review.csv` | Row-by-row review worksheet |
| `ai_lawyer/legal_corpus/official/draft_curated/REVIEWER_CHECKLIST.md` | Per-source checklist |
| `ai_lawyer/legal_rag/corpus_acceptance.py` | Real-mode fail-closed gate |
| `ai_lawyer/legal_corpus/draft/` | Earlier supplied-corpus draft (6 / 145), superseded |
| `ai_lawyer/docs/RAG_PARITY.md` | Stage-by-stage reference mapping + calibration |
| `ai_lawyer/docs/PHASE0_DECISIONS.md` | Fixed decisions |
| `ai_lawyer/evaluation/results/` | E1–E5 outputs (fixture) |

---

## 7. Reproduce

```powershell
# tests (offline)
.\.venv\Scripts\python.exe -m pytest ai_lawyer\tests -q

# rebuild provenance manifest
.\.venv\Scripts\python.exe ai_lawyer\legal_corpus\official\build_manifest.py

# re-extract English text + integrity flags
.\.venv\Scripts\python.exe -m ai_lawyer.legal_rag.english_extract `
  --corpus-dir ai_lawyer\legal_corpus\official

# rebuild the curated staging corpus
.\.venv\Scripts\python.exe -m ai_lawyer.legal_rag.draft_ingest `
  --corpus-dir ai_lawyer\legal_corpus\official `
  --out ai_lawyer\legal_corpus\official\draft_curated `
  --text-dir ai_lawyer\legal_corpus\official\extracted_en `
  --originals-dir ai_lawyer\legal_corpus\official\originals `
  --manifest ai_lawyer\legal_corpus\official\extracted_en\_ingest_manifest.json `
  --as-of 2026-11-08

# fixture demo
.\.venv\Scripts\uvicorn ai_lawyer.backend.main:app --reload
.\.venv\Scripts\streamlit run ai_lawyer/frontend/app.py

# real mode (expected to fail closed today)
$env:CORPUS_MODE="real"
```

---

## 8. Session change log (uncommitted)

- Added official-source retrieval, provenance manifest, and curated ingestion.
- Added `text_integrity_flags()` and 17 extraction tests.
- Added reference-parity boosting and verbatim-prefix compression.
- Added `reviewed_by` / `reviewed_at` to sources and provisions.
- Added `corpus_acceptance.py` and 8 gate tests.
- Corrected two date errors: CCR 2022 effective 2022-12-21; ECR 2020
  corrigendum effective date removed (not stated).
- Verified 13 document hashes, printed facts, and the gate end to end.
- Test total: **181 passed, 1 warning**.
