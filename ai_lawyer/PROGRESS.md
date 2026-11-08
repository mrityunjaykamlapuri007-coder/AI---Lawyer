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

### R2 - review worksheet tooling

| Field | Value |
|---|---|
| Status | IMPLEMENTED_AND_TESTED |
| Test command | `pytest -q` |
| Result | 197 passed, 1 warning in 13.90s |
| Test command (focused) | `pytest ai_lawyer/tests/unit/test_review_tool.py -q` |
| Result | 12 passed |
| Dry run | temp copy of `official/draft_curated` |

What changed:
- `Provision.review_status` (`human_verified` / `unverified` / `rejected`),
  `review_note`; `Provision.reviewed_at` is now a full timestamp.
- Usability now needs BOTH a `human_verified` source and a `human_verified`
  provision with a named reviewer. A verified source no longer makes every
  provision in it citable.
- The real-mode gate rejects a `human_verified` provision whose source is not
  approved, a verified provision with no reviewer/date, an unreviewed
  condition, and any `rejected` provision present in a runtime corpus.
- `python -m ai_lawyer.legal_rag.review_tool` with `list`, `show`, `approve`,
  `reject`, `source-approve`. `approve` takes exactly one provision id and
  requires the id to be typed again (`--confirm` in non-interactive use).
  There is no batch mode. `source-approve` prints every missing provenance
  field and writes nothing until they are complete.
- Writes go only to the staging directory. The CSV worksheets are refreshed
  from the JSON after each write.
- Fixture provisions carry `review_status`/reviewer so the fixture corpus keeps
  10 usable / 1 unusable.

Dry-run evidence (temp copy, not the real staging files):
- `show ECR_2020_P001` printed the verbatim text, page 7, text file
  `ecr_2020_1.txt`, original PDF path, and SHA-256.
- wrong `--confirm` -> exit 2, row unchanged.
- correct `--confirm` -> exit 0, row `human_verified by=DryRun`, warning that the
  source is not approved.
- `reject ECR_2020_P002 --note ...` -> exit 0, row `rejected`.
- `source-approve ECR_2020` -> exit 2, listed `publisher`, `official_url`,
  `published_date`, `version_status`.

Blockers: the real staging corpus is still 0/149 approved. Only Mri can approve;
the tooling does not write legal text, conditions, or metadata from memory.

### R3 - build runtime corpus from approved rows

| Field | Value |
|---|---|
| Status | IMPLEMENTED_AND_TESTED |
| Test command | `pytest -q` |
| Result | 206 passed, 1 warning in 15.35s |
| Focused tests | `pytest ai_lawyer/tests/unit/test_build_runtime_corpus.py -q` |
| Result | 5 passed |
| Dry run | temp copy of `official/draft_curated` |

What changed:
- `python -m ai_lawyer.legal_rag.build_runtime_corpus` reads the staging
  corpus, includes only `human_verified` provisions with a reviewer whose
  source is approved with complete provenance, writes `legal_corpus/sources.json`
  and `provisions.json`, and prints per-source counts plus every exclusion
  reason.
- Refuses to write when zero provisions qualify or when the acceptance gate
  fails. The gate runs before writing.
- `review_tool` gained `condition-add` (operators `exists`, `equals`, `in`,
  `date_before`, `date_after`, `manual`; values validated and stored as typed,
  condition starts `unreviewed`) and `condition-review` (marks one condition
  reviewed). Conditions live in staging and flow into the runtime build.
- Provisions with no conditions already evaluate to `unknown` applicability
  (`evaluate_provision` returns `None`); covered by
  `tests/unit/test_engine.py::test_applicability_is_three_valued`.

Dry-run evidence (temp copy, fake test metadata, not real law):
- 0 approved -> `acceptance gate: FAIL`, `nothing written`, exit 2, no files.
- source-approve one source + approve 2 provisions -> `included 2`,
  `acceptance gate: PASS (usable total: 2)`, files written, exit 0.
- `load_corpus("real")` on the built files:
  `CORPUS_MODE=real version=b89a1fcfee9921b2 sources=1 provisions=2 usable=2 unusable=0`.

Blockers: the real runtime files are still absent because 0/149 real
provisions are approved. Only Mri can approve.

### K1 - Kaggle LLM server notebook

| Field | Value |
|---|---|
| Status | IMPLEMENTED_NOT_TESTED (no Kaggle GPU session run here) |
| Artifact | `kaggle/serve_llm.ipynb`, `kaggle/README.md` |
| Local check | `pytest ai_lawyer/tests/unit/test_kaggle_notebook.py -q` -> 4 passed |

- Starts vLLM with an OpenAI-compatible server for Llama 3.1 8B Instruct.
- Two-T4 route: fp16, `--tensor-parallel-size 2`, `--dtype half`,
  `--max-model-len 8192`.
- One-T4 route: 4-bit AWQ. The notebook refuses to start fp16 8B on one 16 GB
  GPU with an explicit message.
- Reads `API_KEY` and `HF_TOKEN` from Kaggle Secrets; the HF token is passed to
  the child process through the environment, never on the command line, and
  nothing secret is printed.
- Waits for `/v1/models` (10 min cold start), proves JSON-schema decoding, opens
  a cloudflared quick tunnel and prints only the public URL, then heartbeats.
- 401/403 guidance: "license not accepted or token wrong"; no silent fallback.
- The notebook has not been executed on Kaggle. Model id, vLLM version, GPU
  type and quantization must be recorded from the real session.

Blockers for Mri: GPU/Internet toggles, phone verification, accepting the Meta
license, a NEW `HF_TOKEN` (revoke the old exposed one), choosing the HF or
Kaggle-Models route, and the random `API_KEY`.

### K2 - app-side LLM wiring and smoke

| Field | Value |
|---|---|
| Status | IMPLEMENTED_AND_TESTED (wiring); real-model smoke BLOCKED |
| Test command | `pytest -q` |
| Result | 222 passed, 1 warning in 15.00s |
| Focused tests | `pytest ai_lawyer/tests/unit/test_llm_provider_config.py -q` -> 12 passed |
| Smoke (fake, plumbing) | `python -m ai_lawyer.tools.llm_smoke --allow-fake` -> 3/3 steps passed, exit 0 |
| Smoke (default) | `python -m ai_lawyer.tools.llm_smoke` -> REFUSED (fake provider), exit 2 |

Changes:
- Settings: `LLM_MODEL` (wins), legacy `LLM_MODEL_ID`, `LLM_JSON_SCHEMA_MODE`
  (default true), `LLM_TIMEOUT_S` (120), `LLM_MAX_RETRIES_HTTP` (2),
  `LLM_CALL_LOG`, `LLM_FAILURE_LOG`. `.env.example` updated with placeholders.
- `openai_compatible` now sends JSON-schema constrained output when schema mode
  is on; keeps the retry/repair path and the reject-on-schema-failure rule.
- Clear typed failures: 401/403 -> bad `LLM_API_KEY` (no retry); connection
  error -> tunnel/session message; timeout -> cold-GPU/`LLM_TIMEOUT_S` message;
  no silent fallback to the fake model.
- `CORPUS_MODE=real` + `LLM_PROVIDER=fake` is refused at startup before the
  corpus is loaded.
- Every call appends latency + prompt/completion tokens to
  `evaluation/results/llm_calls.jsonl`. Every schema failure appends the raw
  output verbatim to `evaluation/results/llm_failures.jsonl`.
- `python -m ai_lawyer.tools.llm_smoke` tests fact extraction, relevance
  grading and drafting against the same pydantic schemas.

Blockers: a real smoke needs the Kaggle tunnel URL, the served model name and
`LLM_API_KEY` in `.env`. None exist yet, so no real-model call has been made.

### R6 - behaviour harness: fixture/real modes, retrieval candidates, leakage check

| Field | Value |
|---|---|
| Status | IMPLEMENTED_AND_TESTED (fixture mode); real mode BLOCKED (no approved corpus) |
| Test command | `pytest -q` |
| Result | 226 passed, 1 warning in 17.84s |
| Fixture run | `python -m ai_lawyer.evaluation.run_behavior_eval` -> `FIXTURE: 18/18 checks PASS`, exit 0 |
| Real run | `python -m ai_lawyer.evaluation.run_behavior_eval --mode real` -> `BLOCKED: the real corpus is not loadable`, exit 2 |
| Focused tests | `pytest ai_lawyer/tests/unit/test_behavior_eval_harness.py -q` -> 4 passed |

Changes:
- The runner takes `--mode fixture|real`. Fixture mode is unchanged (fake corpus,
  HashEmbedder, FakeLLM, 18/18 including the derived B09 fallback).
- Real mode loads the runtime corpus, uses the configured embedder and LLM, and
  writes to `evaluation/results/real_behavior/` with `raw/`, `summary.md` and
  `manifest.json`.
- Every response now carries `retrieval_candidates`, so diagnostics keep the
  three independent labels (`relevance_grade`, `applicability`,
  `source_validity`) rather than only the accepted sources.
- Real mode scans every assistant message for `Section N` / `Rule N` patterns
  that do not occur in a usable provision, and fails the case if one is found.
- The manifest records model, provider, embedder, vLLM version, quantization,
  GPU type and corpus usable count; values not supplied stay empty rather than
  guessed.
- Real mode reports B09 as it actually behaved, without editing the case.

Blockers: real mode needs an approved runtime corpus, and the manifest fields
for vLLM/quantization/GPU need a real Kaggle session.

### Official Gazette copy check + V5 non-law text (machine-verify-1.2)

| Field | Value |
|---|---|
| Status | IMPLEMENTED_AND_TESTED |
| Test command | `pytest -q` |
| Result | 250 passed, 1 warning in 17.21s (13 new tests) |
| Fixture eval | `python -m ai_lawyer.evaluation.run_behavior_eval` -> `FIXTURE: 18/18 checks PASS` |
| Real check | `python -m ai_lawyer.legal_rag.official_copy --source <id> --url <egazette url>` -> `byte_identical` for ECR_2020, ECR_2021_AMENDMENT, JURISDICTION_RULES_2021_CANDIDATE_A |
| Rebuild | `python -m ai_lawyer.legal_rag.build_runtime_corpus` -> 7 included, 8 rejected by machine verification, gate PASS |

Why: V1-V6 compare a PDF with itself, so they cannot catch a file that is not
the authoritative publication. All three runtime source PDFs (downloaded from
consumeraffairs.gov.in) are byte-identical to the Gazette of India copies on
egazette.gov.in. Evidence: `legal_corpus/official/verification/official_copy_crosscheck.json`
and `verification/<source>/official_copy.json`.

Changes:
- New `legal_rag/official_copy.py`: https + `egazette.gov.in` only (refused
  before any request otherwise), redirects off that host rejected, SHA-256 must
  equal the local file and `document_sha256`. TLS verification stays on; the
  site's incomplete chain is completed by the OS trust store (`truststore`,
  added to `requirements.txt`).
- `Source.official_copy` field. `machine_verify` passes a source only with a
  matching official copy; `corpus_acceptance` enforces the same for every
  `machine_verified` source.
- V5 now rejects non-law text inside the stored span (signatory line, file
  number, gazette footer, digital-signature name lines, next chapter heading).
  Rejected, never trimmed. Scan of the 149 staged rows flagged 14: 7 with
  signature blocks, 7 CPA rows with the next chapter heading attached.
- Defect found and removed: `JURISDICTION_RULES_2021_CANDIDATE_A_P005` (National
  Commission pecuniary limit) was in the runtime corpus with the signatory and
  signature stamp in its text. It is now rejected, so the runtime corpus has
  no provision for the National Commission limit.
- The build report says "rejected by machine verification" instead of
  "rejected by reviewer" for machine rejections.

Limits: amendment completeness after the recorded chain rests on web search of
secondary sources (no queryable e-Gazette index). Not reviewed by a human or a
lawyer.

---

## REAL_RAG_BUILD.md (governing spec from 2026-11-08 ~17:00 IST)

### Stage 1.1 - verify state, commit

| Field | Value |
|---|---|
| Status | IMPLEMENTED_AND_TESTED |
| Commands | hash check vs `manifest.json`; `pytest -q`; commits e754130, fcef166, 15c91c2 |
| Result | 14/14 files match (13 documents + duplicate link); 250 passed |

### Stage 1.2/1.3 - machine verification on Tesseract, corpus expansion (machine-verify-1.3)

| Field | Value |
|---|---|
| Status | IMPLEMENTED_AND_TESTED |
| Test command | `pytest -q` -> 266 passed |
| OCR | Tesseract v5.4.0.20240606 (`winget install UB-Mannheim.TesseractOCR`), eng, psm 4, 300 dpi; engine recorded in every report and provision evidence |
| Rebuild | `build_runtime_corpus` -> 18 included (ECR_2020 16, ECR_2021_AMENDMENT 2), gate PASS |

What changed and why:
- RapidOCR silently dropped whole lines and misread "(iii)" as "(ii)", which
  rejected provisions for OCR reasons. The spec requires Tesseract; it is now
  the V1 engine. The check itself is unchanged (every stored word in order,
  zero tolerance on numbers). OCR cache files are keyed by engine.
- `legal_rag/boundary_fix.py`: ends a staged provision before a trailing
  non-law block only when every removed line is itself non-law (file number,
  signatory, stamp name, timestamp, chapter heading). Kept text is an exact
  prefix; removed text stored verbatim in `boundary_adjustment`; the row is reset
  to unverified. Applied to 11 rows; 3 rows with mixed content were left alone.
- `legal_rag/subrule_split.py`: splits ECR rule 4 into 11 sub-rules (exact
  contiguous slices, recorded offsets, parent kept). V6 now reads the
  amendment's sub-rule scope ("in rule 4, for sub-rule (1)"): only sub-rule (1)
  and the whole-rule row are blocked; unknown scope still blocks the whole rule.

Result per source:
- ECR_2020: 16 pass. Rejected: P003 definitions (text layer "(l)" vs OCR "(1)";
  not equated, spec allows whitespace/ligature differences only), P004 whole
  rule and P004_SR01 (substituted by G.S.R. 328(E)).
- ECR_2021_AMENDMENT: 2/2 pass (includes the substituted rule 4(1)).
- JURISDICTION_RULES_2021: 0/5. V4 fails: Tesseract reads the gazette number as
  "7647 GV/2021" where the text layer reads "GI". Fails closed; not loosened.
  These 3 provisions were in the previous runtime corpus and are now out.
- CPA_2019: not attempted; stays uncitable until the 2026 Jan Vishwas schedule
  check is recorded (user).

### Stage 1.6 - conditions, trust level, rules 5-7 split

| Field | Value |
|---|---|
| Status | IMPLEMENTED_AND_TESTED |
| Test command | `pytest -q` -> 277 passed |
| Conditions | `python -m ai_lawyer.legal_rag.machine_conditions --apply` -> 13/13 machine_verified |
| Rebuild | 30 included (ECR_2020 28, ECR_2021_AMENDMENT 2), gate PASS |

- `legal_corpus/official/conditions/agent_conditions.json`: agent-drafted
  conditions on 7 provisions (scope 2, rule 4(4), 4(5), 4(8), 4(10), 6(3),
  7(4)). Each quotes the exact provision phrase. Facts no extractor produces
  (marketplace vs inventory model, defective goods, charges imposed) are
  `manual` and always UNKNOWN, so those provisions can be "may apply if" but
  never TRUE.
- `machine_conditions`: quote must be in the provision text, fact type and
  values must be in the extractor's vocabulary, 3-case test table (applicable /
  not applicable / unknown) derived from the operator rule.
- `CORPUS_TRUST_LEVEL` enforced: `human` makes machine rows uncitable (gate
  refuses with zero) and machine conditions UNKNOWN. Gate also rejects a machine
  condition whose quote is not in the provision.
- Spot check (real corpus): "refund initiated, not received" -> 4(10)
  applicable, 6(3)/7(4) not_applicable (delay is not refusal); "refund denied"
  -> 6(3)/7(4) unknown; "grievance officer contacted" -> 4(5) applicable.

### Purge rules

| Field | Value |
|---|---|
| Status | IMPLEMENTED_AND_TESTED |
| Test command | `pytest -q` -> 287 passed (`test_purge_rules.py`: 10) |
| Fixture eval | `run_behavior_eval` -> FIXTURE 18/18 PASS (rerun after the move) |
| Real load | `load_corpus('real')` -> usable 30 |

- Fixture corpus moved to `legal_corpus/fixture/`; fakes moved to
  `tests/fakes.py`; runtime factories import them lazily in fake/fixture mode
  only (test enforces no module-level import from runtime packages).
- Real mode refuses a corpus containing any fixture id or the markers
  `TEST_ACT`, `FIXTURE DATA`, `FAKE TEST TEXT`.
- Defect fixed: real mode silently fell back to the hashed embedder. It now
  raises `BLOCKED` (R-2 / C7.2). Real-mode runs are blocked until the remote
  embedder (Stage 2) exists.
- Every dataset row tagged: `behavior_cases.jsonl` and
  `retrieval_stories_to_label.jsonl` = `synthetic_written`;
  `development.jsonl`/`test.jsonl` = `synthetic_fixture`. Real-mode behaviour
  runs refuse untagged or mixed rows; synthetic stories need
  `--synthetic-table` and go to `results/real_behavior_synthetic/` with a
  "SYNTHETIC STORIES, NOT REAL DATA" banner.

### Stage 3 - real evaluation data

| Field | Value |
|---|---|
| Status | IMPLEMENTED_AND_TESTED (dataset + labels); not yet run through real models |
| Test command | `pytest -q` -> 292 passed (`test_real_stories.py`: 6) |
| Stories | `evaluation/dataset/real_stories.jsonl`: 17 (7 development / 10 test) |
| Labels | `python -m ai_lawyer.evaluation.derive_labels` -> 17 machine_derived, 0 excluded |

- Source: 20 public news reports (LiveLaw, Business Today, Outlook Money,
  Storyboard18, a law-firm blog) of Indian district consumer-commission orders
  on e-commerce refunds, found by web search on 2026-11-08. 1 page was an empty
  stub (dropped); 3 reports covered the same Delhi case (one story, two kept as
  corroborating sources) -> 17 unique cases.
- Each story restates only the facts the report describes, first person, up to
  the point before the commission; no outcome or reasoning. Personal names
  removed; company names kept. URL, SHA-256, retrieval date and the redacted
  fact passage are in `real_stories_sources.json`. Pages themselves are not
  committed.
- Builder (`dataset/real_stories_build/`) aborts unless every number in a story
  appears in its source text, no redacted name appears, and hashes match.
  First build passed all checks.
- Split fixed before any run: sorted by SHA-256 of the primary URL, first 7 =
  development.
- Expected outcomes assigned by applying R0-R7 to stated facts: 7
  formal_grievance, 7 needs_more_information (5 R2 missing date/status, 1 R7
  refund already credited, 1 R7 grievance attempted but no verified Consumer
  Commission route provision), 1 informal_resolution, 2 undetermined. These
  assume retrieval accepts at least one provision (otherwise R1).
- Gold labels are machine-derived from conditions. Limitation: every story is
  labelled with the same two provisions (rule 2 scope, rule 4(4) grievance
  mechanism; R15 also 4(5)), because only those have fully extractable
  conditions met by the stated facts. Unlabelled provisions are not known to
  be irrelevant, so precision on these labels is a lower bound.

### Stage 2 - real models on Kaggle (app side + notebook)

| Field | Value |
|---|---|
| Status (app side) | IMPLEMENTED_AND_TESTED with fake HTTP transports (no network in tests) |
| Status (Kaggle notebook + embed server) | IMPLEMENTED_NOT_TESTED: syntax-checked and unit-tested with a fake model; never run on Kaggle |
| Test command | `pytest -q` -> 308 passed (`test_remote_services.py`: 16) |
| Health check | `python -m ai_lawyer.tools.check_remote` -> both FAIL "not configured", exit 2 (no `.env` yet) |

- `kaggle/embed_server.py`: FastAPI, Bearer key required (refuses to start
  without one), `/info` and `/embed`, L2-normalised vectors, BGE query
  instruction only for `kind=query`, size limits, `model_hash` fingerprint from
  embeddings of fixed probe texts.
- `kaggle/serve_all.ipynb` (generated by `kaggle/build_serve_all.py`, server
  source inlined): vLLM Llama 3.1 8B (T4x2 fp16 TP=2, or 4-bit AWQ on one GPU),
  embedder on CPU (bge-large, fallback bge-small, logged), JSON-schema and
  normalisation smoke tests, one cloudflared tunnel per port, only URLs and
  `.env` lines printed, provenance JSON, heartbeat. A test parses every cell
  and asserts no print outputs `API_KEY`/`HF_TOKEN`.
- `legal_rag/remote_embedder.py` (`EMBEDDING_BACKEND=remote_http`): batching,
  2 retries on timeout/connection error then a clear error, 401 not retried,
  shape/normalisation/model-hash-change checks. No fallback.
- Index build writes `index_meta.json` with `embedder_model_hash`; load refuses
  on corpus change, embedder id change or model hash change. A real-mode build
  refuses an embedder without a model hash.
- `tools/check_remote.py`: pings LLM `/models` and the embedder, prints host
  only (never keys or paths), model ids, hash, latency; exit 2 unless all pass.

Needs the user: run `serve_all.ipynb` on Kaggle (Internet on, GPU T4x2, Llama
license, Secrets `API_KEY` and `HF_TOKEN`), paste the printed lines into `.env`,
then `python -m ai_lawyer.tools.check_remote`.
