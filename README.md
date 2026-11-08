# AI Lawyer: refund disputes with Indian e-commerce platforms

Kuku AI Generalist Assignment, **Problem 2**. A chat assistant for an ordinary person whose
online-shopping refund never came. It turns their story (text, plus screenshots or PDFs as proof)
into a structured case, tells them where they stand under the Consumer Protection (E-Commerce)
Rules, 2020, recommends a proportionate next step, and drafts the letter to send.

**Not legal advice. It never files, sends or contacts anyone. It says so when someone needs a lawyer.**

## What it does

1. **Builds the case.** Extracts what happened and when: order, dates, amount, refund status, who was
   contacted. Each fact is tagged *user-reported* or *document-supported* (with page). A fact is kept
   only if its exact words appear in what the user wrote or uploaded.
2. **Explains where they stand.** Retrieves provisions from a small verified corpus and shows them
   word for word, with "may apply if ..." wording. It never says the seller "broke the law".
3. **Recommends a next step.** Python rules, not the model, pick one of: no action yet (still inside
   the seller's own promised time) / contact support / formal grievance to the platform's grievance
   officer / needs more information (asks one question) / out of scope.
4. **Prepares the draft.** A support request or formal grievance with `[TO BE FILLED BY USER]` blanks.
   No invented names, dates, amounts or order ids. Marked DRAFT.

## Proof at a glance

All numbers come from code-written, hashed raw outputs in [`ai_lawyer/evaluation/results/`](ai_lawyer/evaluation/results/),
produced with the real model (Qwen2.5-7B-Instruct on free Kaggle T4 GPUs) on real cases.

| The brief asks | Evidence | Result |
|---|---|---|
| Runs on real inputs | 17 real disputes from public consumer-commission reports, final run ([`real_behavior_run4/`](ai_lawyer/evaluation/results/real_behavior_run4/)) | **test 8/10, development 4/5** (+2 undetermined by design) |
| Works on new inputs | 4 unseen real cases, expected outcomes committed *before* running ([`real_behavior_holdout/`](ai_lawyer/evaluation/results/real_behavior_holdout/)) | **3/4** |
| Never invents law | every real-model answer scanned for section/rule numbers | **0 outside the verified corpus in 50 answers** |
| Honest about unknowns | cases with missing dates or status | asks one question instead of concluding (e.g. R04, R06, R08, H04) |
| Out of scope / adversarial | end-to-end demo through the real API ([`demo/TRANSCRIPT.md`](ai_lawyer/evaluation/results/demo/TRANSCRIPT.md)) | tenancy deposit refused with no law; asked to "cite Section 99, guarantee I win, confirm the seller violated the law", it repeats none of it, cites only verified provisions as "may apply" and asks for the missing date |
| Text + image input | screenshot of a refund message in the same demo | read by local OCR (order id, dates, "5-7 business days") as document-supported facts; recommends contacting support first because the user had not |
| Quality checking | four real runs, each kept unedited with a note | every failure diagnosed; fixes tested; a regression we introduced is reported, not hidden |
| Cost at volume | [`cost_summary_run4.json`](ai_lawyer/evaluation/results/cost_summary_run4.json) | ~5 LLM calls, ~9,300 tokens, ~82 s per case; 0 JSON schema failures |
| Model easy to swap | `.env` only | Kaggle vLLM today; any OpenAI-compatible API |

Failures and limits are listed openly in [`SUBMISSION_NOTES.md`](SUBMISSION_NOTES.md).

## How it avoids invented law (the brief's main ground rule)

| Control | What it does |
|---|---|
| Verified corpus only | 30 provisions of the E-Commerce Rules 2020 and the 2021 amendment. Each source PDF is byte-identical to the Gazette of India copy on egazette.gov.in. Each provision passed automated checks: text layer vs Tesseract OCR word-for-word, numbers, boundaries, amendments. Machine-verified, **not reviewed by a lawyer**. |
| Citations by id | The model can only cite provision ids from the retrieved set; the text shown is rendered from the corpus, never from model output. Unknown ids are blocked. |
| Section-number guard | Any "Section N / Rule N" in an answer that is not in the verified corpus is blocked and logged. |
| Phrase guard | "violated", "illegal", "you will win", "guaranteed" are rewritten or blocked. |
| Abstention | If no verified provision applies, it says so and asks for the missing fact. It never fills the gap from memory. |
| Python owns the outcome | The LLM extracts facts and drafts; the rules engine (R0-R7) decides. If the model disagrees, Python wins and the mismatch is logged. |

## Run it

Requires Python 3.12 and, for image uploads, [Tesseract](https://github.com/UB-Mannheim/tesseract)
(Windows: `winget install UB-Mannheim.TesseractOCR`).

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pytest -q          # offline tests, no model or network
```

### A. Offline demo (no model, synthetic law; for trying the UI)
```powershell
.venv\Scripts\python.exe -m uvicorn ai_lawyer.backend.main:app --port 8000
.venv\Scripts\python.exe -m streamlit run ai_lawyer/frontend/app.py     # second terminal
```
A red banner says **FIXTURE DATA, NOT REAL LAW** in this mode.

### B. Real mode (real law, real models)
The model is chosen in `.env` only (see `.env.example`); no code change.

- **Kaggle (free GPU):** run [`kaggle/serve_all.ipynb`](kaggle/serve_all.ipynb) with GPU T4 x2,
  Internet on and one Kaggle Secret `API_KEY`. It serves Qwen2.5-7B-Instruct (vLLM) and the
  bge-large-en-v1.5 embedder, and prints the `.env` lines to copy.
- **Any hosted API:** set `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`;
  for embeddings `EMBEDDING_BACKEND=openai_compatible`, `EMBEDDER_BASE_URL`, `EMBEDDER_API_KEY`,
  `EMBEDDING_MODEL_ID`.

```powershell
.venv\Scripts\python.exe -m ai_lawyer.tools.check_remote     # both lines must say PASS
# then start the API and UI as in A; the banner shows model, embedder and trust level
```

### C. Reproduce the evaluation
```powershell
.venv\Scripts\python.exe -m ai_lawyer.evaluation.run_behavior_eval --mode real --dataset ai_lawyer/evaluation/dataset/real_stories.jsonl
.venv\Scripts\python.exe -m ai_lawyer.evaluation.run_real_retrieval_eval
.venv\Scripts\python.exe -m ai_lawyer.evaluation.run_behavior_eval            # offline fixture suite
```

## Test cases and raw outputs

- **17 real cases** ([`real_stories.jsonl`](ai_lawyer/evaluation/dataset/real_stories.jsonl)): restated
  from public news reports of Indian consumer-commission orders (Amazon, Flipkart, Myntra, PayTM Mall,
  ...), personal names removed, source URL and hash for each
  ([`real_stories_sources.json`](ai_lawyer/evaluation/dataset/real_stories_sources.json)). Split 7
  development / 10 test before any run. Expected outcomes come from the rules applied to stated facts;
  2 are marked *undetermined*.
- **17 synthetic cases** (`behavior_cases.jsonl`), always reported separately.
- **4 held-out real cases** ([`real_stories_holdout.jsonl`](ai_lawyer/evaluation/dataset/real_stories_holdout.jsonl)),
  collected after the fixes and committed before running.
- **Raw outputs, unedited and hashed:** [`ai_lawyer/evaluation/results/`](ai_lawyer/evaluation/results/):
  `real_behavior_run1/` to `real_behavior_run4/` (each with a `RUN_NOTE.md`), `real_behavior_holdout/`,
  `real_retrieval/`, `demo/` (end-to-end API transcript), `llm_calls.jsonl` (every model call),
  `llm_failures.jsonl`, `cost_summary_*.json`.

Results and failures: [`SUBMISSION_NOTES.md`](SUBMISSION_NOTES.md).

## Scope and limits

- **Covers:** unresolved refunds for online purchases in India (delayed, denied, partial, wrong
  item not refunded), in English, by text plus screenshots/PDFs.
- **Does not cover:** voice, other languages, other disputes (deposits, salary, notices), the
  Consumer Protection Act itself (not yet verified), Consumer Commission filing, pecuniary limits.
  Full list of corpus gaps: [`known_gaps.py`](ai_lawyer/legal_rag/known_gaps.py).
- **Corpus trust:** machine-verified, not reviewed by a human or lawyer; an error in the official
  document itself cannot be detected.
- **Demo security:** local use only. No login, uploads stored unencrypted on the machine; do not
  enter real personal data on a public host.

## Repository map

```text
ai_lawyer/
  legal_corpus/   verified runtime corpus (sources.json, provisions.json) + official/ pipeline evidence
  legal_rag/      corpus loader + gate, machine verification, Gazette check, retrieval (FAISS+BM25+RRF)
  legal_engine/   applicability, relevance, guards, R0-R7 assessment
  backend/        FastAPI, orchestrator, fact extraction, OCR evidence, SQLite
  documents/      draft letters and their validator
  frontend/       Streamlit chat UI
  evaluation/     datasets, runners, metrics, raw outputs
  tools/          check_remote, llm_smoke
kaggle/           model-serving notebook and embedding server
docs/agent/       the specs this was built from
```
