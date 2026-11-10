# AI Lawyer: Refund Disputes with Indian E-Commerce Platforms

Submission for the Kuku AI Generalist Assignment, Problem 2.

A chat assistant for people in India whose online-shopping refund has not arrived. It converts the
user's account (text, plus screenshots or PDFs as supporting evidence) into a structured case,
explains where the user stands under the Consumer Protection (E-Commerce) Rules, 2020, recommends
a proportionate next step, and prepares a draft letter.

**This is not legal advice.** The assistant never files, sends or contacts anyone on the user's
behalf, and it tells the user when a lawyer is needed.

## Contents

1. [Capabilities](#capabilities)
2. [Evaluation summary](#evaluation-summary)
3. [Safeguards against invented law](#safeguards-against-invented-law)
4. [Setup and usage](#setup-and-usage)
5. [Test cases and raw outputs](#test-cases-and-raw-outputs)
6. [Scope and limitations](#scope-and-limitations)
7. [Repository structure](#repository-structure)

## Capabilities

1. **Case construction.** Extracts the order, dates, amount, refund status and who has been
   contacted. Each fact is labelled *user-reported* or *document-supported* (with page reference).
   A fact is retained only if its exact words appear in the user's message or uploaded document.
2. **Explanation of the user's position.** Retrieves provisions from a small, verified corpus and
   displays them verbatim, using conditional wording ("may apply if ..."). It does not state that a
   seller has broken the law.
3. **Next-step recommendation.** A deterministic rules engine, not the language model, selects one
   of the following outcomes:
   - no action yet (still within the seller's own promised timeline);
   - contact customer support;
   - escalate to the platform's grievance officer;
   - more information needed (the assistant asks one question);
   - out of scope.
4. **Draft preparation.** Produces a support request or formal grievance marked DRAFT, with
   `[TO BE FILLED BY USER]` placeholders. It does not invent names, dates, amounts or order IDs.

## Evaluation summary

All figures come from code-written, hashed raw outputs in
[`ai_lawyer/evaluation/results/`](ai_lawyer/evaluation/results/). They were produced with a real
model (Qwen2.5-7B-Instruct on free Kaggle T4 GPUs) on real cases.

| Requirement | Evidence | Result |
|---|---|---|
| Works on real inputs | 17 real disputes taken from public consumer-commission reports; final run in [`real_behavior_run4/`](ai_lawyer/evaluation/results/real_behavior_run4/) | Test set 8/10, development set 4/5; 2 cases undetermined by design |
| Generalises to unseen inputs | 4 held-out real cases, with expected outcomes committed before the run ([`real_behavior_holdout/`](ai_lawyer/evaluation/results/real_behavior_holdout/)) | 3/4 |
| Does not invent law | Every real-model answer scanned for section and rule numbers | 0 numbers outside the verified corpus across 50 answers |
| Handles missing information | Cases with missing dates or status | Asks one question rather than concluding (for example R04, R06, R08, H04) |
| Handles out-of-scope and adversarial input | End-to-end demo through the real API ([`demo/TRANSCRIPT.md`](ai_lawyer/evaluation/results/demo/TRANSCRIPT.md)) | A tenancy-deposit request is refused without citing law. When asked to cite "Section 99", guarantee a win and confirm that the seller violated the law, the assistant repeats none of it, cites only verified provisions as "may apply", and asks for the missing date |
| Accepts text and image input | Screenshot of a refund message in the same demo | Read by local OCR (order ID, dates, "5-7 business days") as document-supported facts; recommends contacting support first because the user had not |
| Quality checking | Four real runs, each retained unedited with a run note | Every failure was diagnosed and fixes were tested; a regression introduced during fixing is reported |
| Cost | [`cost_summary_run4.json`](ai_lawyer/evaluation/results/cost_summary_run4.json) | About 5 LLM calls, 9,300 tokens and 82 seconds per case; 0 JSON schema failures |
| Model portability | Configured through `.env` only | Kaggle-hosted vLLM today; any OpenAI-compatible API is supported |

### Changes made after the final measured run

The scores above were measured before the final round of chat changes on 9 November:

- a message router that reads each message in context (greeting, off-topic, needs details, refund
  case, follow-up);
- answers grounded in the extracted facts, with the law shown as its verbatim key clause;
- multi-message intake;
- a per-file document verdict (read, not an order or refund record, or unreadable).

These changes pass 381 offline tests and 18 of 18 fixture checks, and were tried manually on about a
dozen conversations. They were not re-scored on the real-case set before the deadline. After the
changes, a refund case takes about 45 seconds; greetings, off-topic messages and unusable files take
2 to 4 seconds.

Failures and limitations are documented in [`SUBMISSION_NOTES.md`](SUBMISSION_NOTES.md).

## Safeguards against invented law

| Control | Behaviour |
|---|---|
| Verified corpus only | 30 provisions from the E-Commerce Rules 2020 and the 2021 amendment. Each source PDF is byte-identical to the Gazette of India copy on egazette.gov.in. Each provision passed automated checks: text layer compared with Tesseract OCR word for word, numbers, boundaries and amendments. The corpus is machine-verified and has **not been reviewed by a lawyer**. |
| Citations by identifier | The model may cite only provision IDs from the retrieved set. The displayed text is rendered from the corpus, never from model output. Unknown IDs are blocked. |
| Section-number guard | Any "Section N" or "Rule N" in an answer that is absent from the verified corpus is blocked and logged. |
| Phrase guard | Phrases such as "violated", "illegal", "you will win" and "guaranteed" are rewritten or blocked. |
| Abstention | If no verified provision applies, the assistant says so and asks for the missing fact. It does not fill the gap from model memory. |
| Deterministic outcome | The LLM extracts facts and drafts text; the rules engine (R0 to R7) decides the outcome. If the model disagrees, the rules engine prevails and the mismatch is logged. |

## Setup and usage

Requirements: Python 3.12. For image uploads, install
[Tesseract](https://github.com/UB-Mannheim/tesseract) (Windows: `winget install UB-Mannheim.TesseractOCR`).

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pytest -q          # offline tests; no model or network
```

### A. Offline demo (no model, synthetic law)

Intended for exploring the interface only.

```powershell
.venv\Scripts\python.exe -m uvicorn ai_lawyer.backend.main:app --port 8000
.venv\Scripts\python.exe -m streamlit run ai_lawyer/frontend/app.py     # second terminal
```

A banner reading **FIXTURE DATA, NOT REAL LAW** is displayed in this mode.

### B. Real mode (real law, real models)

The model is selected in `.env` only (see `.env.example`); no code change is needed.

- **Kaggle (free GPU).** Run [`kaggle/serve_all.ipynb`](kaggle/serve_all.ipynb) with a T4 x2
  accelerator, Internet enabled and one Kaggle Secret named `API_KEY`. The notebook serves
  Qwen2.5-7B-Instruct through vLLM and the bge-large-en-v1.5 embedder, and prints the `.env` lines
  to copy.
- **Any hosted API.** Set `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL`, `LLM_MODEL` and
  `LLM_API_KEY`. For embeddings, set `EMBEDDING_BACKEND=openai_compatible`, `EMBEDDER_BASE_URL`,
  `EMBEDDER_API_KEY` and `EMBEDDING_MODEL_ID`.

```powershell
.venv\Scripts\python.exe -m ai_lawyer.tools.check_remote     # both checks must report PASS
# Then start the API and UI as in A. The banner shows the model, embedder and trust level.
```

### C. Reproducing the evaluation

```powershell
.venv\Scripts\python.exe -m ai_lawyer.evaluation.run_behavior_eval --mode real --dataset ai_lawyer/evaluation/dataset/real_stories.jsonl
.venv\Scripts\python.exe -m ai_lawyer.evaluation.run_real_retrieval_eval
.venv\Scripts\python.exe -m ai_lawyer.evaluation.run_behavior_eval            # offline fixture suite
```

## Test cases and raw outputs

- **17 real cases** ([`real_stories.jsonl`](ai_lawyer/evaluation/dataset/real_stories.jsonl)).
  Restated from public news reports of Indian consumer-commission orders (Amazon, Flipkart, Myntra,
  PayTM Mall and others), with personal names removed. Each case records its source URL and hash
  ([`real_stories_sources.json`](ai_lawyer/evaluation/dataset/real_stories_sources.json)). The split
  into 7 development and 10 test cases was fixed before any run. Expected outcomes come from applying
  the rules to the stated facts; 2 cases are marked *undetermined*.
- **17 synthetic cases** (`behavior_cases.jsonl`), always reported separately from real cases.
- **4 held-out real cases** ([`real_stories_holdout.jsonl`](ai_lawyer/evaluation/dataset/real_stories_holdout.jsonl)),
  collected after the fixes and committed before they were run.
- **Raw outputs**, unedited and hashed, in [`ai_lawyer/evaluation/results/`](ai_lawyer/evaluation/results/):
  `real_behavior_run1/` to `real_behavior_run4/` (each with a `RUN_NOTE.md`),
  `real_behavior_holdout/`, `real_retrieval/`, `demo/` (end-to-end API transcript),
  `llm_calls.jsonl` (every model call), `llm_failures.jsonl` and `cost_summary_*.json`.

Results and failures are discussed in [`SUBMISSION_NOTES.md`](SUBMISSION_NOTES.md).

## Scope and limitations

**In scope.** Unresolved refunds for online purchases in India (delayed, denied, partial, or a wrong
item that was not refunded), in English, through text plus screenshots or PDFs.

**Out of scope.** Voice input, other languages, other disputes (deposits, salary, legal notices),
the Consumer Protection Act itself (not yet verified), filing with a Consumer Commission, and
pecuniary limits. The full list of corpus gaps is in
[`known_gaps.py`](ai_lawyer/legal_rag/known_gaps.py).

**Corpus trust.** The corpus is machine-verified and has not been reviewed by a human or a lawyer.
An error in an official document itself cannot be detected by these checks.

**Evaluation limits.** The evaluation set is small (17 real cases plus 4 held-out). Retrieval gold
labels are machine-derived and cover only provisions whose conditions could be extracted, so
retrieval precision is a lower bound. The reranker experiment was not run.

**Security.** Intended for local use only. There is no authentication, and uploads are stored
unencrypted on the host machine. Do not enter real personal data on a publicly hosted instance.

## Repository structure

```text
ai_lawyer/
  legal_corpus/   verified runtime corpus (sources.json, provisions.json) and official/ pipeline evidence
  legal_rag/      corpus loader and gate, machine verification, Gazette check, retrieval (FAISS + BM25 + RRF)
  legal_engine/   applicability, relevance, guards, R0-R7 assessment
  backend/        FastAPI, orchestrator, fact extraction, OCR evidence, SQLite
  documents/      draft letters and their validator
  frontend/       Streamlit chat interface
  evaluation/     datasets, runners, metrics, raw outputs
  tools/          check_remote, llm_smoke
kaggle/           model-serving notebook and embedding server
docs/agent/       specifications this project was built from
```
