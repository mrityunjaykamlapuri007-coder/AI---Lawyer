# Progress log

Date: 2026-11-08
Workspace: `C:\Users\Lenovo\OneDrive\Documents\Default Project`
Package: `ai_lawyer/`
Mode: fixture demo (`FIXTURE DATA, NOT REAL LAW`)

This log records what exists and the evidence for it. It does not claim that a
phase was green if the exact historical count was not retained; the final
verification section is the authoritative run.

## Milestones

| Phase | Deliverable | Status | Evidence |
|---|---|---|---|
| T0 | Settings, `.env.example`, `.gitignore`, contracts, fakes, fixture corpus | Done | `tests/unit/test_contracts.py`, `test_corpus_loader.py` |
| T1 | Corpus loader/validator, real-mode fail-closed path, chunker | Done | `test_corpus_loader.py`, `test_chunker.py`; real mode raises `CorpusValidationError` |
| T2 | FAISS + BM25 indexes, RRF, query planner, retriever, expander, optional reranker | Done, reranker optional | `test_index_manager.py`, `test_rrf.py`, retrieval harness E1/E2/E3 |
| T3 | Source validity, applicability, relevance filter, acceptance, retry/abstention | Done | `test_engine.py` |
| T4 | LLM adapters, reasoning prompt, citation/phrase/date guards, decision controller | Done | `test_engine.py`; provider adapters are lazy |
| T5 | SQLite schema/repo, fact extraction, case manager, evidence store, assessment, documents, orchestrator, response generator | Done | `test_services.py`, `test_documents.py`, `test_pipeline.py` |
| T6 | FastAPI endpoints + Streamlit client | API done; UI headless-tested | `test_api.py`; `test_streamlit_app.py` (2 `AppTest` interactions, not a real browser) |
| T7 | Retrieval dataset, behaviour dataset, metrics, harnesses, failure analysis | Done | 16 retrieval rows; `raw_outputs/`, `results/`, `failure_analysis.md` |
| T8 | README, reuse notes, progress log, final report | Done | `README.md`, `docs/`, this file |
| T9 | English extraction + review-only draft corpus builder (sources, provisions, worksheets, checklist, quality flags) | Done | `legal_rag/english_extract.py`, `legal_rag/draft_ingest.py`; 11 + 21 tests; output in `legal_corpus/extracted_en/` and `legal_corpus/draft/` |
| T10 | Local git baseline, documentation refresh, final test run | Done | `git init` + local commits; 141 tests pass |

## Final verification

Run from the project root:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ai_lawyer.evaluation.run_retrieval_eval
.venv\Scripts\python.exe -m ai_lawyer.evaluation.run_behavior_eval
```

Observed results:

- `pytest -q`: **141 passed, 1 warning in 8.60s**. The warning is the
  Starlette/httpx `TestClient` deprecation, not a product failure.
- Retrieval harness exit code 0; 16 fixture rows (8 development, 8 test), K in
  {5,10,20}; E1/E2/E3/E5 run; E4 marked `NOT RUN`; 160 raw records.
- Behaviour harness exit code 0; **17/17 core cases PASS** plus the derived
  **B09_missing_corpus PASS** = **18/18 checks PASS**.
- Streamlit `AppTest`: **2 passed in 2.06s** (fixture banner + response render,
  and offline startup). These are headless script tests, not browser automation.

## Product decisions recorded during implementation

- Python owns the outcome (`R0`-`R7`). The LLM's proposed outcome is persisted
  in `rule_trace` but cannot override it.
- Follow-up questions are emitted only when the outcome is
  `needs_more_information`. A decided outcome does not include a contradictory
  `## Missing information` section.
- The refund timeline rule R4 uses calendar days, excludes the trigger date,
  and only applies to pending-style statuses inside the merchant's own
  user-reported promise.
- Date extraction infers yearless dates only from explicit years in the same
  message, and classifies dates by the nearest event keyword in the sentence.
  Repeatable support/grievance contact dates are excluded from conflict flags.
- A resolved case reopens on new evidence and keeps the same `case_id`; B17
  verifies `case_created`, `case_resolved`, `case_reopened`.
- Fixture mode is the default and is visible in the API health payload, every
  assistant response, the Streamlit banner, and every evaluation artifact.
- Real corpus mode fails closed. No real legal text, citation, date, fee, or URL
  was written from memory, and no `review_status: human_verified` was fabricated.

## Deviations and open issues

1. **Local VCS only.** A local git repository exists with four baseline commits
   plus the final documentation commit. No remote, push, branch, merge, or
   deploy was made.
2. **Real corpus blocked.** `ai_lawyer/legal_corpus/sources.json` and
   `provisions.json` are absent. English-only extracts exist in
   `legal_corpus/extracted_en/` (6 parts; ECR is 0.99957 Latin because of 6
   Devanagari enumeration markers), and `legal_rag/draft_ingest.py` generates
   review-only drafts: 6 sources and 145 provisions, all `unverified`, 0 usable,
   with `REVIEWER_CHECKLIST.md`. Candidate metadata is quoted from the
   documents; publisher, URL, publication date and effective dates remain blank
   for human review. Real mode still raises `CorpusValidationError`; this is
   expected, not a crash.
3. **E4 not run.** `RERANKER_ENABLED=false` and the optional cross-encoder model
   is not installed. The wrapper is `IMPLEMENTED_NOT_TESTED`.
4. **First behaviour failures were overwritten.** The harness writes one file
   per case; the first 13/17 run was replaced by the passing rerun. The exact
   observed failure lines and fixes are preserved in
   `evaluation/failure_analysis.md`.
5. **Streamlit is headless-tested, not browser-tested.** Two `AppTest` cases
   execute the real app script and submit a chat message with fake HTTP
   responses. They do not cover a real browser or a live backend.
6. **Fixture metrics are not real-law metrics.** The corpus is synthetic, the
   retrieval dataset is 16 rows, and `FakeLLM` is a deterministic lexical
   grader with a small documented synonym map. The map exists because the
   expanded rows exposed misses for "definition"/"means" and "sent"/"returned";
   it is not a semantic model.
7. **Devanagari markers preserved.** The ECR English extract contains six
   Devanagari enumeration labels. They are counted as non-Latin, flagged
   `devanagari`, and left verbatim; repairing or removing them needs a human
   decision or proper OCR.
8. **Installed versions.** `requirements.txt` is pinned to the versions found in
   `.venv` on 2026-11-08 (`pandas==3.1.1`, `pymupdf==2.1`,
   `pydantic-settings==2.16.2`, `python-multipart==0.0.33`, `pytest==9.2.0`).

## Final test count (after the last code/test change)

```text
.venv\Scripts\python.exe -m pytest -q
141 passed, 1 warning in 8.60s
```

If the count differs, rerun the command and trust the terminal output over this
log.

---

## Real-mode runbook (2026-11-08, evening)

| Task | Status | Command | Result |
|---|---|---|---|
| R1 | IMPLEMENTED_AND_TESTED | `pytest -q` | 181 passed, 1 warning in 12.73s |
| R1 | commit | `git status --porcelain` | clean on branch `ai-lawyer-mvp` |

R1 notes:
- Branch `ai-lawyer-mvp` created from `11f5bd9`.
- Work committed in four groups: repo baseline, official corpus pipeline,
  acceptance gate, RAG parity + docs.
- `corpus_manifest.json` is generated on every load and is now git-ignored, so
  test runs no longer dirty the tree.
- `AGENTS.md` copied into the repo root; `IMPLEMENTATION_PLAN.md` into
  `docs/agent/`. `AGENT_EXECUTION_SPEC.md` and the v4 spec were not present on
  disk and were not used for this runbook.
- PDFs under `legal_corpus/official/originals/` and scratch `_search/` are
  git-ignored (17.8 MB / 5.3 MB); the provenance manifest and hashes are
  committed instead.
