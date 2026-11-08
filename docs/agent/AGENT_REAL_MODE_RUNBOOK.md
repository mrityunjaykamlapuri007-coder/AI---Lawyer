# AGENT_REAL_MODE_RUNBOOK.md: get the real-corpus RAG running tonight

Read AGENTS.md first. Its hard rules apply here. This file is your task list for the remaining hours.
Deadline: submittable by 12:00 midnight IST tonight. Hard cut for code work: 20:30 IST. Stop adding features after that.
Current state: fixture mode works (181 tests, behaviour eval 18/18). Real mode fails closed because 0/149 provisions are human-verified and `legal_corpus/sources.json` / `provisions.json` do not exist.

## The one rule that cannot bend
You must NOT mark anything `human_verified`, fill `reviewed_by` / `reviewed_at`, write legal text, or write conditions from your own knowledge. Only the user (Mri) verifies provisions. Your job is to build tooling that makes his review fast, then load what he approved and make the pipeline run on it. If the gate rejects a corpus, report why. Never loosen the gate to make it pass.

## Working rules for this runbook
- One task at a time, in order. Run the task's test command, paste the real output, label status (IMPLEMENTED_AND_TESTED, IMPLEMENTED_NOT_TESTED, BLOCKED).
- If a task fails twice, stop and report. Do not work around.
- Do not touch original research-RAG files. Commit after each task on branch `ai-lawyer-mvp` with a clear message. No push, no force-push without asking.
- Never print tokens or secrets. Keys only in `.env`.
- No model download or network call inside unit tests.
- Update PROGRESS.md after each task.

## Task R1: commit the current work (10 min)
Everything since commit 11f5bd9 is untracked. Run `pytest -q` (expect 181 pass), then commit in logical groups: corpus pipeline, acceptance gate, RAG parity, docs.
Done when: `git status` is clean and tests still pass.

## Task R2: review worksheet tooling (45 min)
Goal: make Mri's verification fast and safe.
Build `python -m ai_lawyer.legal_rag.review_tool`:
1. `list --source ECR_2020`: prints provision ids, short title, and review state.
2. `show <provision_id>`: prints the stored verbatim text, the source file name, the page number, and the document hash. Also prints the path of the original PDF so he can open it beside the text.
3. `approve <provision_id> --reviewer "<name>"`: sets `review_status: human_verified`, `reviewed_by`, `reviewed_at` (current time) on that provision only. It must refuse to run unless the user types the provision id again to confirm. It must never run in batch or with `--all`.
4. `reject <provision_id> --note "..."`: records the reason, keeps it unusable.
5. `source-approve <source_id> --reviewer ...`: only succeeds if the source has publisher, official URL, publication date, document hash, and a non-`uncertain` version status. Otherwise print exactly which fields are missing.
Write approvals into the staging files in `official/draft_curated/`, not into the runtime files.
Tests: approval needs confirmation; batch approve is impossible; source-approve fails with missing fields; unreviewed rows stay unusable.
Done when: tests pass and a dry run on one fixture-style row works.

## Task R3: build runtime files from approved rows only (30 min)
Build `python -m ai_lawyer.legal_rag.build_runtime_corpus`:
- Reads the staging corpus, takes ONLY provisions with `human_verified` and a reviewer, and only from sources that passed source-approve.
- Writes `legal_corpus/sources.json` and `provisions.json`.
- Prints a summary: counts per source, excluded count with reasons, and the usable total.
- Refuses to write if zero provisions qualify.
- Runs the existing acceptance gate and prints its verdict.
Condition authoring: add a small helper so Mri can add structured conditions to a provision (operators exist/equals/in/date_before/date_after/manual), validated against the schema, then mark the conditions `reviewed`. Provisions without conditions are still allowed as background and must evaluate to `unknown` applicability, never `applicable`.
Done when: with 2 hand-approved test rows in a temp copy of the corpus, real mode loads and reports usable=2, and with 0 approved it refuses.

## Task R4: real LLM wiring (45 min)
Use the existing `openai_compatible` provider. Do not add a new adapter.
- Settings read `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` from `.env`. Update `.env.example` with placeholders only.
- Add `python -m ai_lawyer.tools.llm_smoke` that sends one tiny prompt for each structured step (fact extraction, relevance grading, answer drafting) and checks the JSON against the pydantic schemas. Print pass or fail per step and the raw output.
- Keep the schema-retry-twice-then-reject rule. Log every failure verbatim to `evaluation/results/llm_failures.jsonl`. These failures are material for the submission doc, so do not hide them.
- Add per-call latency and token counts to the log for the cost section.
Done when: smoke passes for all three steps with the real model, or the exact failing step and raw output is reported.

## Task R5: real embeddings (30 min, skip if install fails once)
- Try `sentence-transformers` with `BAAI/bge-large-en-v1.5`. If the machine cannot run it in reasonable time, try `bge-small-en-v1.5`. If that also fails, keep the hashed embedder and state that plainly in PROGRESS.md.
- Rebuild the index with `CORPUS_MODE=real`. Record embedder name, dimension, index size and build time.
- Reranker stays OFF unless R7 time allows.
Done when: `python -m ai_lawyer.legal_rag.index_manager build` succeeds in real mode and a test query returns verified provisions only.

## Task R6: end-to-end real run (45 min)
- Run all behaviour cases (`evaluation/dataset/behavior_cases.jsonl`, B01–B17) in real mode with the real LLM.
- Write raw, unedited outputs by code only to `evaluation/results/real_behavior/raw/<test_id>.json` (full request, retrieved candidates with the three labels, LLM proposal, final outcome, guard events, response text). No hand editing, no rewriting failures.
- Write `evaluation/results/real_behavior/summary.md`: pass/fail per case with the failing assertion quoted.
- B09 passes only if the corpus holds a verified Consumer Commission route provision. Otherwise the correct result is `needs_more_information`. Report which it is. Do not change the case to make it pass.
- Also report any answer containing a section number that is not in the verified corpus. That is a critical defect.
Done when: all 17 cases have a raw file and a summary line.

## Task R7: retrieval evaluation on real labels (45 min)
Dataset: `evaluation/dataset/retrieval_stories_to_label.jsonl` (14 development, 26 test).
- Add `python -m ai_lawyer.evaluation.label_helper` that, for a development or test story, prints the story and the full verified provision list (id, title, text) so Mri can fill gold labels by hand. It must never auto-fill labels from the retriever or an LLM. It writes only what he enters, keeps `labeling_status: "TODO_human"` until he sets it to `labeled`, and skips unlabeled rows in metrics.
- `run_retrieval_eval` computes P@K, R@K, MRR@K, nDCG@K, false acceptance rate on labeled rows only, reported separately for development and test, for E1 (dense), E2 (BM25), E3 (hybrid RRF). E4 only if the reranker model is installed.
- Never tune any parameter on test rows. If a parameter changes, it is chosen on development rows only and the change is logged.
- Results go to `evaluation/results/real_retrieval/`. State the labeled row count in every table.
Done when: the eval runs on whichever rows are labeled and prints counts. A small honest number of labeled rows is acceptable.

## Task R8: prototype link (45 min)
The assignment needs a prototype link. Choose the simplest option that works for the user and say which:
- Option A: tunnel the local Streamlit app (for example cloudflared) and keep the machine awake during evaluation.
- Option B: a Hugging Face Space or Streamlit Cloud app that calls the FastAPI backend.
Rules: demo-user header is not auth, so label the demo plainly and do not accept real personal data. Show a visible banner stating whether it is running on the verified corpus subset. No secrets in the repo. Public deploy needs the user's explicit OK first, so ask before running anything that publishes.
Done when: the user can open the URL, run B01 end to end and see sources, assessment and a draft.

## Task R9: submission pack (30 min)
Produce `SUBMISSION_NOTES.md` from real files, no invented numbers:
- Tools used, with model and embedder names.
- Cases where the AI got it wrong, taken from `llm_failures.jsonl`, the two corrected date errors (CCR 2022 effective date, ECR 2020 corrigendum effective date) and any guard that fired.
- Assumptions: R0–R7 outcome rules are product decisions, not legal truth; promised-timeline rule uses the user-reported promise; verified subset scope.
- Scale and cost: per-call latency and token counts from R4, extrapolated plainly.
- Honest failures and limits: 2026 E-Commerce amendment (effective 2027-01-01) not ingested and its text layer unreadable; CPA corrigendum scanned and not ingested; E4 status; metric row counts; fixture-only metrics must not be quoted as real results.
Done when: every claim in the file points to a results file.

## Cut order if time is short
1. R7 reduces to labeled development rows only.
2. R5 stays hashed embedder.
3. R8 uses a tunnel.
4. Never cut: R1, R3, R4, R6, R9.

## When you finish, report in this format
Per task: id, status label, command run, real output (trimmed), blockers. Then list anything you could not verify and anything the user must still do himself (provision review, gold labels, 2026 Jan Vishwas schedule check for the Consumer Protection Act, the doc, the video).
