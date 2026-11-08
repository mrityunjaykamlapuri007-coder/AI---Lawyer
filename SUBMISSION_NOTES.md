# Submission notes: AI Lawyer (Kuku Problem 2)

Evidence file behind the 2-page solution doc. Every claim points to a file in this repo.
Status labels: IMPLEMENTED_AND_TESTED / IMPLEMENTED_NOT_TESTED / DESIGN_ONLY / BLOCKED.

## 1. Problem and scope

- **Problem:** refunds for online purchases in India that never arrive, are denied, or are short.
  Frequent, small amounts, so people rarely hire a lawyer and often give up.
- **Covers:** unresolved e-commerce refund disputes in India; English; text plus screenshots/PDFs.
- **Does not cover:** voice; other languages; other disputes (deposit, salary, notices); filing at a
  Consumer Commission; pecuniary limits. Corpus gaps: `ai_lawyer/legal_rag/known_gaps.py`.

## 2. Assumptions (made where the brief was silent)

1. One problem in depth beats many shallowly (brief allows it).
2. The outcome rules R0-R7 (`ai_lawyer/legal_engine/assessment.py`) are **product rules**, not legal
   truth. Example: contact support first; escalate to the grievance officer only after that.
3. A seller's promised refund timeline is used only when the user reports it, and only as the
   seller's own promise, never as a legal deadline.
4. A delay alone is never described as a violation.
5. Machine verification against the official Gazette is acceptable for a prototype; a production
   corpus would add lawyer review.
6. Uploads are proof, not instructions: text from files is treated as data (prompt-injection safe).

## 3. How it works

```text
message (+ screenshot/PDF -> local OCR)
  -> scope gate (out of scope: short refusal, no law)
  -> fact extraction (LLM + rules; fact kept only if its words are in the source; user_reported vs document_supported)
  -> query planning -> dense (BGE) + BM25 retrieval -> RRF fusion over 30 verified provisions
  -> LLM relevance grading (JSON schema) + 3-valued applicability from machine-verified conditions
  -> Python rules R0-R7 choose the outcome (LLM proposal logged, never wins)
  -> LLM drafts the explanation -> guards (citation ids, section numbers, phrases, dates)
  -> answer with verbatim law + DRAFT support request / grievance letter
```

| Done by | What |
|---|---|
| LLM (Qwen2.5-7B-Instruct) | scope check, fact extraction, relevance grading, drafting the explanation |
| Code | corpus verification, retrieval, applicability, outcome rules, every guard, draft letter, OCR |
| Human | sends the letter, decides to escalate; a lawyer for anything the tool flags |

Model swap: `.env` only (`LLM_PROVIDER/LLM_BASE_URL/LLM_MODEL`), one OpenAI-compatible adapter
(`ai_lawyer/backend/services/llm_providers.py`).

## 4. How it avoids invented law

| Control | Evidence |
|---|---|
| Source PDFs byte-identical to the Gazette of India copies | `legal_corpus/official/verification/official_copy_crosscheck.json` |
| Provision text = Tesseract OCR word-for-word; numbers exact; no signature/footer text; amendment-aware | `legal_corpus/official/verification/*/report.json`, `legal_rag/machine_verify.py` |
| Acceptance gate refuses unverified rows, fixture data, missing Gazette match | `legal_rag/corpus_acceptance.py`, tests in `tests/unit/test_machine_verification.py`, `test_purge_rules.py` |
| Citations by id, rendered from corpus; unknown ids and unknown section numbers blocked | `legal_engine/citation_validator.py`, runner check in `evaluation/run_behavior_eval.py` |
| No code path can mark anything human-verified | `test_no_code_path_outside_the_review_tool_writes_human_fields` |

Result on real runs (17 real-case answers in run 2 with the real model; RUN3_SECTIONS_TBD): **0 section or rule numbers outside the verified corpus** (`results/real_behavior_run2/summary.md`). 0 JSON schema failures in every real call (`results/llm_calls.jsonl`; no `llm_failures.jsonl` written).

## 5. Quality: test design and results

**Test cases.**
- 17 real cases from public news reports of consumer-commission orders, anonymised, sourced, split
  7 dev / 10 test before any run (`evaluation/dataset/real_stories*.json*`). Expected outcome = rules
  applied to the stated facts; 2 undetermined.
- 17 synthetic cases, reported separately (`behavior_cases.jsonl`).

**Behaviour, real models** (Qwen2.5-7B-Instruct fp16 on 2x T4, vLLM 0.33.0; bge-large-en-v1.5).
Each run is kept unedited with hashes (`results/real_behavior_run*/`).

| Run | What changed before it | Test split (n=10) | Dev split (n=7) | Notes |
|---|---|---|---|---|
| 1 | first real run | crashed on case 5 | | R01 wrong outcome; 4 defects (section 6) |
| 2 | run-1 defects fixed (`284171a`) | **8/10 pass** | 2/5 pass, 2 recorded | 0 invented section numbers |
| 3 | run-2 extraction defects fixed from dev cases (`3e99a11`) | RUN3_TEST_TBD | RUN3_DEV_TBD | RUN3_NOTES_TBD |

"Recorded" = expected outcome undetermined by the rules, so no pass/fail.
In R01 (run 2) the LLM proposed "needs more information" and the Python rules overrode it with the
correct "formal grievance": the rules own the outcome. In R02 the same override went the wrong way
because the extracted fact was wrong (see section 6).

**Retrieval, real corpus** (`results/real_retrieval/`; E3 hybrid RRF, test split, n=10):
recall@10 0.57, precision@10 0.12, recall@20 0.95, MRR@20 0.15. Caveat: gold labels are
machine-derived and cover only the two generic provisions whose conditions are fully extractable
(scope, grievance mechanism); the top results are refund-specific rules that cannot be labelled.
Precision is a lower bound. E4 (reranker) not run.

**Offline suite:** 353 tests pass (`pytest -q`); fixture behaviour suite 18/18.

## 6. Failures (real runs, kept)

Run 1 (`results/real_behavior_run1/`, kept unedited, crashed on case 5):
1. **R01 wrong outcome.** The LLM returned refund status as free text ("nothing has been credited");
   the rules engine did not recognise it and fell to "needs more information" instead of "formal
   grievance".
2. **Negation.** The rule pattern read "nothing has been credited" as *received*.
3. **Junk facts.** `transaction_id: "Visa card online"`; payment method not normalised.
4. **Crash.** The LLM returned the amount as the string "0.00"; the draft generator crashed and the
   runner aborted the whole run.
All four were fixed as general defects (commit `284171a`), with tests in
`tests/unit/test_fact_normalisation.py`; run 2 re-ran all 17 cases.

Run 2 (`results/real_behavior_run2/`): 5 failures, all in **fact extraction**, none from law:
| Case | Expected -> got | Cause |
|---|---|---|
| R02 (dev) | needs info -> formal grievance | refund *had* reached the account; LLM labelled it "processed" (pending) |
| R03 (dev) | formal grievance -> needs info | return date also tagged as cancellation date (two events, one sentence) -> false conflict; "sent notices" not seen as contact |
| R04 (test) | needs info -> informal | "August 16th" given the current year (a guess); "kept calling customer care" not seen as contact |
| R09 (dev) | needs info -> informal | delivery date tagged as purchase date; "reported it in the app" not seen as contact |
| R12 (test) | formal grievance -> needs info | events worded "collected from my home" / "seller received it": no date got a role |
Fixes for run 3 were designed from the development cases and generic phrasing only (commit
`3e99a11`, tests in `tests/unit/test_run2_extraction_fixes.py`); R04/R12 (test) were not used to
design fixes. R12's wording gap is left as a known limit. RUN3_FAILURES_TBD

Reliability: one model call stalled 743 s through the free tunnel and failed; the automatic retry
succeeded and the run continued (`results/llm_calls.jsonl`). The 120 s timeout did not cut it off.

## 7. Tools used and where AI got it wrong

Tools: Claude Code (agent: code, tests, corpus pipeline), [YOU: tools you used to write the specs], Kaggle (free GPU),
vLLM, Qwen2.5-7B-Instruct, BGE embeddings, Tesseract OCR, FAISS, rank-bm25, FastAPI, Streamlit.

Where it got it wrong (pick one for the doc):
- **Invented model id.** The coding agent wrote a 4-bit model id from memory
  (`casperhansen/llama-3.1-8b-instruct-awq`); a Hugging Face API check showed it does not exist.
  The single-GPU route would have failed on Kaggle. Fixed in commit `67f1c5a`.
- **OCR misread.** The first OCR engine read "(iii)" as "(ii)" and silently dropped lines; switched to
  Tesseract (`PROGRESS.md`, Stage 1.2).
- **Law stored with a signature.** A verified provision included the signatory's name and the digital
  signature stamp as if it were law; caught by a cross-check against a second official copy.
- **Silent fake embedder.** Real mode quietly fell back to a test embedder; now refused.
- **Real model, run 1:** see section 6.

## 8. Scale and cost

Measured on run 2 (`results/cost_summary_run2.json`, 86 calls, 85 ok):
| Per case | Value |
|---|---|
| LLM calls | ~5 (scope, facts, 2x relevance, reasoning) |
| Tokens | ~7,300 prompt + ~2,100 completion (~9,400) |
| LLM time on 2x T4 | ~2.6 min mean (one 743 s tunnel stall inflates it); reasoning ~40 s, relevance ~20 s, facts ~25-70 s, scope ~5 s |
Money: tokens x the chosen provider's own per-token price (not estimated here). Embedding is local
to the embedder service and small (30 provisions, one query per case).
- Kaggle free GPU: marginal cost zero; a session is temporary.
- At volume: per-case tokens x provider price; the corpus grows through the verification pipeline
  (new Gazette PDF -> official-copy check -> OCR checks -> gate), not through prompts.
- Retrieval is local (FAISS/BM25) and cheap; the LLM calls dominate.

## 9. Limits and when to see a lawyer

- Corpus is machine-verified, not lawyer-reviewed; an error in the official document is undetectable.
- No Consumer Protection Act provisions, so it never recommends Consumer Commission proceedings.
- OCR measured only on clean images; phone photos will be worse (unmeasured).
- Uploaded files stay on the machine, unencrypted, no retention policy; no login (local demo).
- It flags a lawyer when the user mentions court or limitation deadlines, fraud, unclear liability
  between seller/platform/bank, or asks for representation.
