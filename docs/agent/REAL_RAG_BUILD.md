# REAL_RAG_BUILD.md: replace everything synthetic with real data and real models

Context: the prototype was built and tested on SYNTHETIC data (a fake "TEST_ACT" fixture corpus, invented stories such as FakeMart/ShopEasy Demo, a fake LLM, a hashed embedder). That proves the plumbing only. This file defines the build of the REAL system: real law, real retrieval, real models, real evaluation data. Where this file conflicts with an older spec, this file wins. AGENTS.md hard rules still apply. Read AGENT_MACHINE_VERIFICATION.md, AGENT_GPU_ON_KAGGLE.md and AGENT_RISK_CONTROLS.md for the detailed mechanisms this file points to.
Deadline: submittable by 12:00 midnight IST, 8 Nov 2026. Code freeze 21:30 IST.

## Definition of "real" (every item must be true, or reported as not true)
R-1 Law: provisions come only from the downloaded official Government of India documents (13 PDFs in `legal_corpus/official/originals/`, hashes verified) through the corpus pipeline. No law from memory, no fixture text.
R-2 Models: real open-weight LLM (Llama 8B Instruct on Kaggle GPU) and a real embedder (BGE on Kaggle). No FakeLLM, no hashed embedder, in real mode.
R-3 Retrieval: dense + BM25 + RRF over the real corpus only. Index built from `provisions.json`; integrity-checked against corpus and embedder hashes.
R-4 Evaluation data: real consumer-dispute narratives, not invented ones (see Data section). Gold labels derived from real provision text, never from the retriever or the answering LLM.
R-5 Outputs: raw outputs written by code, hashed, failures kept.
R-6 Isolation: real mode contains no fixture data anywhere (see Purge rules).

## Hard rules
1. Never write legal text, section numbers, deadlines, fees, case names, quotes or URLs from memory. If a fact is not in an official document or a recorded source, it does not exist for this system.
2. Never label anything `human_verified`; no code path may write `reviewed_by`/`reviewed_at`. Automated verification earns `machine_verified` with evidence (AGENT_MACHINE_VERIFICATION.md). Add the protecting test.
3. No claim without a run. After each task: run its test, paste real output, label status IMPLEMENTED_AND_TESTED / IMPLEMENTED_NOT_TESTED / BLOCKED. BLOCKED is never a pass. Update PROGRESS.md.
4. One task at a time, in order. Two failures on a task means stop and report. Never loosen a gate, threshold or check to pass.
5. Do not modify the original research-RAG files. Commit after each task. No push, history rewrite or public deploy without asking.
6. Secrets only in `.env` or Kaggle Secrets. Never print or reuse tokens found in old files.
7. No torch/vLLM/sentence-transformers/model weights locally; GPU work on Kaggle over HTTP. Unit tests offline with fakes; fakes live only under `tests/`.
8. Python owns gates and outcomes; the LLM extracts, grades and drafts.
9. Real mode fails closed with a clear BLOCKED message and exit code 2. No silent fallback.
10. Privacy: no personal data of private individuals in the repo, results or logs.

## Purge rules (synthetic data must not leak into real mode)
- Move fixtures to `tests/fixtures/` and `ai_lawyer/legal_corpus/fixture/`. The runtime loader in real mode never reads them.
- Real mode refuses to start if the loaded corpus contains any provision or source id from the fixture, the text "TEST_ACT", or the banner "FIXTURE DATA".
- Evaluation in real mode refuses datasets whose rows have `data_origin: synthetic` unless they are reported in a separate, clearly labeled table. Existing `behavior_cases.jsonl` and `retrieval_stories_to_label.jsonl` are synthetic stories: tag each row `data_origin: synthetic_written` and never present their metrics as results on real data.
- Add a test that real-mode startup fails when a fixture id is injected.

## Stage 1: real corpus (17:00–19:00)
1. Verify state: `pytest -q`; confirm the 13 hashes against `manifest.json`; commit pending work.
2. Run the machine verification pipeline from AGENT_MACHINE_VERIFICATION.md on the staging corpus (`official/draft_curated/`): independent OCR vs text-layer extraction, number inventory, hash and integrity checks, quoted date evidence, proviso boundary, amendment chain. OCR is CPU work: install Tesseract locally; if it cannot be installed, report BLOCKED and stop this stage (do not fall back to a single extraction).
3. Verify in this order: `ECR_2020` and `ECR_2021_AMENDMENT` (the refund-relevant rules), then CPA provisions on definitions, unfair trade practice and complaint forum only when the CPA amendment chain allows (the 2026 Jan Vishwas Act schedule has not been checked; until recorded the Act stays unverified and uncitable), then `CC_RULES_2023_AMENDMENT`, `JUR_2021` if time remains.
4. Known gaps stay recorded and visible: 2026 E-Commerce amendment (effective 2027-01-01, unreadable text layer), CPA 2020 corrigendum (scanned). A dispute dated before the effective date must yield `not_yet_effective` for the 2026 amendment.
5. Write `legal_corpus/sources.json` and `provisions.json` from `machine_verified` rows only. Print counts per source and rejection reasons. Refuse to write if zero qualify. Run the acceptance gate.
6. Conditions: agent-drafted only, each with the exact quoted source phrase; accepted only after the machine test table. Otherwise applicability is `unknown` and the provision is background only.
Done when: real mode loads with a non-zero usable count, tests prove the gate refuses missing evidence and that code cannot write human fields.

## Stage 2: real models on Kaggle (18:00–19:30, parallel)
- `kaggle/serve_all.ipynb`: Llama 8B Instruct via vLLM (gated: `HF_TOKEN` from Kaggle Secrets, or the model attached from Kaggle Models; two T4 tensor-parallel fp16, or 4-bit on one GPU; max length 8192; constrained JSON output), a BGE embedding service, optional reranker, one tunnel per port, only public URLs printed, heartbeat. IMPLEMENTED_NOT_TESTED until the user runs it.
- App side: `openai_compatible` LLM provider and `remote_http` embedder, timeouts, clear errors, `check_remote` health command, latency/token logging to `evaluation/results/llm_calls.jsonl`.
- Index build writes `index_meta.json` (embedder id and hash, corpus hash, provision count); load refuses on mismatch.
Needs the user: Kaggle Internet on with phone verification, GPU selected, Secrets set, Llama license accepted, notebook running, public URLs in `.env`.

## Stage 3: real evaluation data (19:00–20:30)
Real data means real dispute narratives and real provision text. Sources, in order of preference:
1. Narratives the user supplies himself or with consent from people he knows, with names, phone numbers, addresses, order and account numbers removed.
2. Publicly available consumer-commission orders or public complaint write-ups about e-commerce refunds, found through web search. For each, record exact URL, retrieval date, file hash and the passage used. Do not invent URLs. Do not use private individuals' identifying details; strip or generalize them. Use the facts described, not the judgment's reasoning, as the input story.
3. If neither can be obtained in time, say so and keep the synthetic stories in their own separately labeled table. Do not present synthetic stories as real data.
Rules:
- Each real story row records `data_origin` (`user_supplied` / `public_commission_order`), `source_record_id`, `retrieved_at`, and `anonymised: true`.
- Target 20 real stories if possible, split 8 development / 12 test before any tuning; report whatever number exists. Never expand a split after seeing results.
- Gold labels: `machine_derived` only, by rule from verified provision text and conditions plus the story's quoted facts (a provision is gold-relevant only if the story contains the facts the provision's machine-verified conditions require). Never derive from the retriever or LLM. Rows that cannot be derived are excluded; print counts.
- Real behaviour cases: for each real story, record the expected outcome only where rules R0–R7 determine it from stated facts; otherwise mark `expected: undetermined` and record the raw output without pass/fail.

## Stage 4: product on real data (19:30–21:00)
Pipeline: scope gate (R0, out-of-scope gets a short refusal, no retrieval, no draft) -> fact extraction with evidence status (user_reported / document_supported) -> query planning -> dense + BM25 + RRF (k=60) over verified provisions -> source validity from the dispute date (unknown date -> `uncertain`) -> LLM relevance grading with JSON schema (retry twice then reject) -> three-valued applicability -> acceptance policy with bounded retry -> deterministic R0–R7 outcome in Python -> answer rendered with verbatim provision text.
Guards that must block an answer: citation validator (any provision id, section/rule number or date not in the verified corpus or the user's facts is a critical defect), quote check (quoted law must be an exact substring), phrase guard (no "violated / illegal / you will win / guaranteed"), date guard (Python-computed days), prompt-injection handling (uploads are data). UI banner shows LLM id, embedder id, corpus trust level ("machine-verified, not reviewed by a human or lawyer"), verified count and known gaps.

## Stage 5: run and record (20:30–21:30)
- E1 dense, E2 BM25, E3 hybrid on real labeled rows; E4 only if the reranker ran on Kaggle, else NOT RUN. Report P@K, R@K, MRR@K, nDCG@K, false acceptance rate, essential-context completeness, with the row count and split in every table, development and test separately, and the synthetic-story table separate.
- Run real behaviour cases with raw unedited outputs written by code to `evaluation/results/real_behavior/raw/<id>.json` with hashes, plus a summary listing failing assertions verbatim.
- Report any answer containing a section number absent from the verified corpus, the count of schema failures, and every guard trigger. Keep failures; any re-run is logged with the reason.
- Every results folder records: LLM id and quantization, embedder id/hash, GPU type, corpus hash, trust level, labeled row counts.

## Stage 6: submission pack (21:30–23:00)
`SUBMISSION_NOTES.md` from real files only: tools used, where the AI got it wrong (from `llm_failures.jsonl`, the two date errors already caught in CCR 2022 and the ECR 2020 corrigendum, guard triggers), assumptions (R0–R7 are product rules not legal truth; promised timelines are user-reported), scale and cost (from `llm_calls.jsonl`), honest limits (2026 amendment and corrigendum not ingested, CPA chain status, E4 status, machine-derived labels and row counts, real-story count, no human or lawyer review, errors in an official document are undetectable). Every claim points to a results file. Prototype link: ask the user which option; do not publish publicly without explicit OK.

## Cut order
1. Reranker/E4. 2. Query cache. 3. `CC_RULES` and `JUR_2021`. 4. CPA sections (stay uncitable, listed as a gap). 5. Number of real stories (report what exists). 6. Video.
Never cut: the machine verification core (V1–V5), the gate and human-field protection test, citation blocking, purge rules, raw outputs, separation of synthetic vs real results, and the honest disclosures.

## Report format (after every task)
Task id, status label, command run, real output (trimmed), blockers, and anything not run on real hardware. End with what the user must still do himself: Kaggle setup, the 2026 Jan Vishwas schedule check, supplying or approving real stories, the demo link choice, the 2-page doc.
