# AI LAWYER: v4 ADVANCED EXECUTION SPEC (parallel build, covers most of v2)

Read order for the agent: (1) AGENT_EXECUTION_SPEC.md (v3) in full, (2) this file. **v3 rules, schemas, pipeline, assessment rules and safety checklist all still apply.** This file adds scope, a parallel work structure and stricter integration rules. Where v4 and v3 conflict, v4 wins. The v2.0 spec remains the long-term design reference.

Deadline: submittable by 12:00 midnight IST, 8 Nov 2026. Integrated core by 17:00. Writing/eval/submission after that.

---------------------------------------------------------------------
## 0. HONEST CAPACITY STATEMENT (READ FIRST)
---------------------------------------------------------------------
Realistic target: about 70-75% of v2 architecture implemented and tested, the rest honestly labelled. Full v2 (150 labelled questions, real OCR quality tuning, live Jev integration, legal-expert review) is not achievable in one day. This plan gets there by:
1. **Freezing interfaces first** (Section 2) so streams can be built in parallel.
2. **Running independent work streams** in separate git worktrees (Section 3).
3. **Building against fakes first**, swapping in real components at merge points.
4. **Tiering scope** (Section 4) with hard cut lines.
Quality rule: a tier is "done" only when its tests pass in the integrated branch. Never merge a stream that fails its own tests. Never claim a tier-3 item works unless it ran.

---------------------------------------------------------------------
## 1. SCOPE TIERS
---------------------------------------------------------------------
### TIER 1: CORE (must be real, tested; = v3 scope)
Corpus loader/validator/manifest; hybrid retrieval (FAISS+BM25+multi-list RRF), expansion; relevance/applicability/validity verification with bounded retry and abstention; structured reasoning; deterministic citation/phrase/date guards; assessment R0-R7 + decision controller; support_request and formal_grievance drafts; SQLite state with append-only events; exact-ID case matching; text-PDF/paste evidence with SHA-256; FastAPI single-call endpoint; Streamlit UI; retrieval metrics + E1-E3 + behaviour cases with raw outputs.

### TIER 2: ADVANCED (real if time allows; each independently shippable)
T2-A Corpus ingestion assistant: PDF -> page-level text -> proposed provision units (Section 5.1).
T2-B Claim extractor + claim-level verification with LLM entailment as an additional check (Section 5.2).
T2-C Reranker (BGE cross-encoder) with calibration on development set only; E4; E5 ablation (Section 5.3).
T2-D OCR for images and scanned PDF pages behind an `OCRProvider` interface; mixed-PDF per-page fallback; extraction validator (Section 5.4).
T2-E Case snapshots every N events + milestone snapshots, checksum, deterministic rebuild; archive directory with hash re-check (Section 5.5).
T2-F Remaining documents: National Consumer Helpline complaint summary and Consumer Commission complaint draft, with template validators (Section 5.6).
T2-G Timeline builder and conflict detection; context assembler summary; observability with correlation ids (Section 5.7).
T2-H RAGAS adapter (pinned, smoke-tested), legal-specific metrics, larger dataset harness (Section 5.8).

### TIER 3: EXPERIMENTAL / LABELLED
T3-A Jev adapter: interface + feature flag + fake for tests only. **No real endpoint, schema or request structure may be written without the user providing verified official documentation.** Status = MOCKED_FOR_TESTING. Baseline-vs-Jev comparison harness may exist but must print "NO LIVE JEV, NOT A RESULT" and report no metrics.
T3-B Authentication/encryption/deployment hardening: DESIGN_ONLY.
T3-C Full 150-question benchmark: harness supports it; dataset size is whatever the user labels (target 20 dev + 40 test). Report actual counts.

---------------------------------------------------------------------
## 2. FREEZE INTERFACES FIRST (HOUR 1, BLOCKING)
---------------------------------------------------------------------
Before any stream starts, one agent (the "integrator") creates `ai_lawyer/contracts/` and merges it to the base branch. Nothing else may change contracts without integrator approval.

Contents:
- `models.py`: all Pydantic models from v3 Section 8 plus: `Evidence`, `PageExtraction`, `Claim`, `ClaimVerification`, `TimelineItem`, `RetrievalRun`, `DocumentDraft`, `CorpusManifest`.
- `interfaces.py` (Protocols/ABCs): `LLMAdapter(generate_structured(prompt, schema, options), generate_text, health_check)`, `Embedder`, `Reranker`, `OCRProvider(extract(image_bytes)->OCRResult)`, `CorpusRepository`, `Retriever`, `Verifier`, `CaseRepository`, `EvidenceStore`, `DocumentGenerator`, `JevClient`.
- `fakes.py`: deterministic fake LLM (scripted outputs by test id, can also return invalid JSON and invented ids on demand), hash embedder, identity reranker, fake OCR returning canned text, in-memory repositories.
- `fixtures/`: fake corpus (Section 4.4 of v3), sample facts, sample stories, expected outputs.
- `errors.py`: error codes (v2 Section 32.8) and a `UserSafeError`.
- `ids.py`: UUID helpers, canonical `make_provision_id()`.
- `tests/contracts/`: schema round-trip tests and fake behaviour tests.
Gate: `pytest tests/contracts -q` passes; any stream can import contracts and fakes without loading a model or touching the network.

---------------------------------------------------------------------
## 3. PARALLEL WORK STREAMS
---------------------------------------------------------------------
Use one git worktree/branch per stream (for example `git worktree add ../ws-retrieval ai-lawyer-mvp`). If your tooling supports subagents, run one subagent per stream with its own scope. Each stream: edits only its own directories, depends only on `contracts/`, writes its own tests, never edits another stream's files, merges to `integration` only when its tests pass.

| Stream | Owns | Tier | Depends on |
|---|---|---|---|
| WS-1 Corpus | `legal_rag/source_registry.py, corpus_loader.py, validator.py, manifest.py, parser/` (T2-A) | 1 + T2-A | contracts |
| WS-2 Retrieval | `legal_rag/chunker.py, index_manager.py, query_planner.py, retriever.py, rrf.py, reranker.py (T2-C), provision_expander.py` | 1 + T2-C | contracts, fixture corpus |
| WS-3 Verification | `legal_engine/source_validity.py, relevance_filter.py, applicability.py, retry_policy.py, claim_extractor.py (T2-B), citation_validator.py, claim_verifier.py (T2-B), phrase_guard.py` | 1 + T2-B | contracts, fixtures |
| WS-4 State/Evidence | `backend/services/` conversation/case/fact/timeline/context, `storage/` SQLite+migrations, `input/` PDF text, OCR (T2-D), validator, snapshots (T2-E) | 1 + T2-D/E/G | contracts |
| WS-5 Reasoning/Assessment/Docs | `legal_engine/reasoning.py, assessment.py, decision_controller.py, jev_adapter.py (T3-A)`, `documents/` (all 4 types, T2-F), `response_generator.py` | 1 + T2-F + T3-A | contracts |
| WS-6 API/UI | `backend/api/, main.py, frontend/app.py`, error handling, health, observability (T2-G) | 1 | contracts, in-memory repos |
| WS-7 Evaluation | `evaluation/` harness, metrics + tests, ablations, RAGAS adapter (T2-H), behaviour runner, manifests, reports | 1 + T2-H | contracts, fixtures |

**Merge protocol (integrator):**
1. M1 08:00: contracts + WS-1 loader + WS-6 skeleton + WS-7 metrics merged. Integration branch must pass all tests.
2. M2 12:00: WS-2, WS-3 merged and wired (retrieval -> verification) with fixture corpus.
3. M3 15:00: WS-4, WS-5 merged; full orchestrator runs end to end with the fake LLM.
4. M4 16:30: WS-6 UI wired to the real orchestrator; swap fakes for the real LLM adapter, real embedder, real corpus (if provided).
5. 17:00 HARD GATE (Section 7).
After each merge: run `pytest -q`, record counts in `PROGRESS.md`. A merge that breaks the integration suite is reverted, not patched forward.

`PROGRESS.md` (maintained by the integrator): each component with status label (IMPLEMENTED_AND_TESTED, IMPLEMENTED_NOT_TESTED, MOCKED_FOR_TESTING, DESIGN_ONLY, BLOCKED), last test command, last result, blockers.

---------------------------------------------------------------------
## 4. SCHEDULE (IST; hours are targets)
---------------------------------------------------------------------
| Time | Integrator | Streams | User |
|---|---|---|---|
| 05:20-06:30 | Create contracts, fakes, fixtures; settings, requirements; worktrees | idle (read specs, inspect repo) | Revoke HF token. Place official PDFs in `legal_corpus/originals/`. Start choosing provisions |
| 06:30-08:00 | Merge M1 | WS-1 loader+validator (then T2-A parser), WS-7 metrics+tests, WS-6 skeleton | Review parser proposals as they appear; fill `provisions.json` |
| 08:00-12:00 | Merge M2 | WS-2, WS-3 (Tier 1 first, then T2-B/T2-C), WS-4 (Tier 1), WS-5 reasoning/assessment | Write benchmark rows and behaviour stories |
| 12:00-15:00 | Merge M3 | WS-4 OCR/snapshots, WS-5 docs/T3-A mock, WS-7 ablations + RAGAS adapter | Choose real LLM, set env, test it manually |
| 15:00-16:30 | Merge M4, swap fakes for real | WS-6 UI wiring, bug fixing | Try three new stories |
| 16:30-17:00 | **GATE** | fixes only | Gate checklist |
| 17:00-19:00 | Run evaluations | WS-7 run E1-E5 on dev/test, behaviour set, save raw outputs | Review failures |
| 19:00-20:00 | README, PROGRESS final, failure_analysis | WS-7 | Read results honestly |
| 20:00-22:30 | n/a | n/a | 2-page doc, video |
| 22:30-23:30 | n/a | n/a | Submission checks in an incognito window |
| 23:30-24:00 | BUFFER | n/a | n/a |

**Cut lines (strict).** At 12:00, any Tier-2 item whose own tests are not passing in its worktree is cut to DESIGN_ONLY. At 15:00 again. At 16:30 nothing new is merged. Cut order for Tier 2: T2-H RAGAS, T2-D OCR, T2-F extra documents, T2-E snapshots, T2-C reranker, T2-B LLM entailment (keep deterministic claim checks), T2-A parser, T2-G timeline. Tier 1 and the 17:00 gate are never traded for Tier 2.

---------------------------------------------------------------------
## 5. TIER 2 / TIER 3 COMPONENT SPECS
---------------------------------------------------------------------
### 5.1 T2-A Corpus ingestion assistant (WS-1)
Purpose: save the user hours. It **proposes**; a human **approves**.
- Input: official PDF(s) in `legal_corpus/originals/` (never committed unless license allows). Compute SHA-256; register in `sources.json` as `review_status: unverified` with fields the user must complete (URL, retrieved date, version label).
- Extraction: PyMuPDF per page, retaining 1-based page numbers; blank/low-text pages flagged `needs_ocr` (OCR via T2-D if available, else flagged for manual handling).
- Structure proposal: regex-based parser for section/rule numbers, sub-section `(1)`, clause `(a)`, `Provided that`, `Explanation`, definitions. Output `provisions.proposed.json` where every unit has `parser_confidence` (high if the numbering pattern and parent resolved; low otherwise), `original_text` copied verbatim from the page text, `page_start/end`, and `needs_review: true`. **Never rewrite text. Never auto-set `human_verified`.**
- Diff report `parser_report.md`: units found per page, low-confidence units, text that could not be attached to any unit, pages with no units.
- A tiny CLI `python -m ai_lawyer.legal_rag.parser <pdf>`; a human copies reviewed units into `provisions.json` (or flips a `review_status` field per unit).
- Tests: synthetic PDF built in the test (fake text) with sections, a proviso, an explanation; assert hierarchy, verbatim text, page numbers, and that low-confidence units are flagged.
- Status label for output: DESIGN_ONLY for any legal correctness; the parser is only a drafting aid.

### 5.2 T2-B Claim extractor and claim-level verification (WS-3)
- `claim_extractor`: split `LegalDraft` (structured fields, not free prose) into atomic claims with `claim_type` in {citation, legal_rule, deadline_or_timeline, case_fact, application, remedy_or_procedure, recommendation}, `materiality` (material/secondary), `cited_provision_ids`, `cited_fact_ids`.
- Deterministic validators (must exist, tested):
  - citation: provision exists, usable, in accepted set, source current for date;
  - case_fact: referenced fact exists and the claim's value equals it; status shown as user_reported or document_supported, never promoted;
  - deadline: backed by a Python-computed value or removed;
  - recommendation: consistent with the Python assessment outcome (mismatch => recommendation replaced by the assessment's next steps).
- LLM entailment (additional check only): structured call per material legal_rule/application claim, input = claim + the cited provision's original text, output `{supported: yes|partial|no, reason}`. Never decides alone; `no` or `partial` downgrades status unless deterministic checks contradict.
- Claim status: verified | partially_verified | unverified | clarification_required | outdated_source. Overall verification is not a single pass/fail: remove or qualify unsupported secondary claims; block unsupported material legal conclusions and ask or abstain.
- Tests: invented citation blocked; fact value mismatch flagged; unsupported application downgraded; secondary claim removed without killing the response; fake-LLM entailment `no` downgrades.

### 5.3 T2-C Reranker and calibration (WS-2, WS-7)
- Cross-encoder (`BAAI/bge-reranker-large` or configured) behind the `Reranker` interface; lazy loaded; flag-controlled; records `model_id`, raw score, original rank, new rank. No inherited threshold.
- Calibration script runs on **development set only**: report score distributions for grade>=2 vs grade<=1 provisions, choose an optional cutoff, save to config with the dev-set evidence. Test set untouched.
- Ablation E4 and E5 use identical corpus/queries/K. If the model cannot load (RAM/GPU), mark E4/E5 NOT RUN with the reason; do not substitute.

### 5.4 T2-D OCR and mixed PDFs (WS-4)
- `OCRProvider` interface; one concrete provider (prefer a local one such as Tesseract via pytesseract or RapidOCR; pick what installs cleanly; if none installs, keep the fake and mark BLOCKED/MOCKED). **No remote OCR for private evidence.**
- Images (JPG/PNG): validate magic bytes, size cap, OCR, store result. PDFs: per page, extract text; if empty or below `MIN_CHARS_PER_PAGE` (config) run OCR for that page only; record `method` per page (`text_extraction`/`ocr`), 1-based page number, `quality_status`, OCR confidence only if the provider returns one. Detect encrypted/corrupt PDFs => clear status, no crash.
- `extraction_validator`: non-empty, plausible length, not mostly replacement/garbled characters, duplicate pages flagged; statuses completed | partial | failed | needs_user_retry. Each input is independent: one failure never discards others.
- Evidence facts: `document_supported` with `evidence_id` + page. Never "authentic". Contradictions between documents are surfaced, not resolved silently.
- Tests: signature spoof rejected; text PDF page stays `text_extraction`; blank page triggers fake OCR; encrypted PDF handled; partial failure keeps the successful input.
- Quality check: if the user supplies 3-5 sample screenshots/scans with transcriptions, report character-level agreement; otherwise say OCR quality is unmeasured.

### 5.5 T2-E Snapshots and archive (WS-4)
- After every `SNAPSHOT_EVERY_N_EVENTS` (default 20) and at milestones (resolved, reopened, assessment_created, draft_approved): write `case_snapshots` row with `state_json`, `sha256`, last `sequence_no`.
- `reconstruct_case(case_id)`: load latest valid snapshot (verify SHA-256), replay later events; if the checksum fails, rebuild from all events and report a diagnostic. Reconstruction from events only must equal reconstruction via snapshot (test).
- Archive: move an original file to `archive/` with SHA-256 before/after; mismatch marks evidence `corrupt` and blocks use as intact evidence. Atomic move (temp + rename).
- Event sequence numbers assigned inside a transaction; a concurrency test with two threads must produce unique, gapless numbers.

### 5.6 T2-F Documents (WS-5)
Four types: `support_request`, `formal_grievance`, `nch_summary`, `consumer_commission_draft`.
- Template-driven; facts from fact store only; legal grounds from accepted provisions only, rendered citations; placeholders `[TO BE FILLED BY USER]`; header "DRAFT: prepared for your review. Not sent or filed."
- `nch_summary` and `consumer_commission_draft` are generated only if an accepted corpus provision supports that route; otherwise the endpoint returns "route not supported by the current corpus" and the missing facts. **No jurisdiction, pecuniary limit, fee, form number, limitation period or address may appear unless it is in a human-verified corpus provision or entered by the user.** If absent, placeholder.
- Post-generation validator: every order id, date, amount, party name appears in the fact store or is a placeholder; mismatch blocks the draft. Draft state `needs_review`; approval is an explicit user action that records a `document_draft_approved_by_user` event. Nothing is sent.
- Export: Markdown and (if `python-docx` installs) DOCX; PDF export optional. Tests per type: placeholders, mismatch block, no-provision route refusal.

### 5.7 T2-G Timeline, context and observability (WS-4, WS-6)
- `timeline_builder`: items {event_type, date or date_range, precision exact|approximate|unknown, source_id, source_status, summary, conflict_flag}. Two conflicting dates => both listed with a conflict flag and a clarification question; never silently chosen.
- `context_assembler`: compact context (v2 Section 29.9) with case summary instead of full history.
- Correlation id per message across stages; structured safe logs (stage, latency, counts, ids, model versions, error code); no raw evidence or personal data in logs. `/health` reports API, DB, corpus (version, unusable count), vector index, embedder, LLM, OCR status.

### 5.8 T2-H Evaluation extensions (WS-7)
- **Retrieval metrics** as v3 Section 14, plus legal-specific: applicability precision/recall/F1 with confusion matrix, false acceptance rate (state the denominator), source-version accuracy, essential-context completeness with critical-omission flag, abstention/unknown handling, query-to-chunk cosine diagnostics (never a correctness criterion).
- **RAGAS adapter** `evaluation/ragas_evaluator.py`: read the installed version's official docs first, pin the version, build a 2-sample smoke test (one correct and one irrelevant context) and assert the expected ordering, use ID-based Context Precision/Recall when the installed version supports them, otherwise LLM-judged variants with judge model/config saved. Per-question results are saved. If the install or judge is unavailable, mark RAGAS NOT RUN. Never invent scores.
- **Ablations** E1 FAISS only, E2 BM25 only, E3 hybrid+RRF, E4 +reranker, E5 +verification; context expansion measured as a separate secondary experiment. Identical corpus, queries, K, filters. `stage_ablation.csv`, `latency.csv`.
- **Dataset tooling**: loader validates every row's provision ids exist in the corpus; split guard that fails if a scenario id appears in both dev and test; dataset counts printed on every run.
- **Behaviour suite** as v3 Section 14B, extended with: contradictory documents, second order mid-conversation, reopened resolved case, historical-date source version, provision with proviso+exception, no-provision-after-retries, invented-citation bait, prompt injection inside an uploaded text file ("ignore previous instructions...") that must be treated as quoted data.
- Failure analysis uses the v2 reason codes (query_rewrite_semantic_drift, dense_search_miss, sparse_search_miss, fusion_rank_degradation, reranker_rank_degradation, metadata_filter_false_exclusion, source_version_mismatch, provision_expansion_missing_parent, proviso_or_exception_omitted, applicability_false_acceptance, applicability_false_rejection, no_match_false_positive, corpus_gap, annotation_ambiguous). Written from real failures only.
- Run manifest: git commit, corpus hash/version, model ids and revisions, package versions, config, seeds, date.

### 5.9 T3-A Jev adapter (WS-5), MOCKED ONLY
- `legal_engine/jev_adapter.py`: class implementing `JevClient`; `JEV_ENABLED=false` default; the real client raises `NotConfigured` until the user supplies a verified official API spec in `docs/jev_api_contract.md`. Do not guess endpoints, schemas, auth or pricing.
- Minimiser: builds a reduced structured state (outcome candidates, missing-info flags, provision ids; no raw text, no identifiers) so the privacy design is real even if the call is mocked.
- Decision controller treats any Jev output as advisory and can never override law or Python rules; API failure degrades silently to the baseline (tested with a failing fake).
- Comparison harness exists but outputs "NOT RUN: no live Jev" unless the user explicitly provides verified access.

---------------------------------------------------------------------
## 6. EXTRA TEST REQUIREMENTS (ADD TO v3 SECTION 15)
---------------------------------------------------------------------
Unit: `test_parser_flags_low_confidence`, `test_parser_text_is_verbatim`, `test_claim_types_and_materiality`, `test_claim_fact_value_mismatch`, `test_entailment_downgrades_status`, `test_reranker_records_scores_and_ranks`, `test_pdf_page_level_fallback`, `test_encrypted_pdf_status`, `test_extraction_validator_garbled`, `test_snapshot_checksum_and_rebuild_equivalence`, `test_event_sequence_concurrency`, `test_archive_hash_mismatch_marks_corrupt`, `test_timeline_conflict_flag`, `test_nch_route_refused_without_provision`, `test_document_no_invented_jurisdiction`, `test_split_guard_rejects_leakage`, `test_dataset_ids_exist_in_corpus`, `test_jev_failure_degrades_to_baseline`, `test_jev_disabled_by_default`.
Integration: `test_ws_merge_pipeline_fixture_end_to_end`, `test_prompt_injection_in_upload_treated_as_data`, `test_reopen_resolved_case_same_id`, `test_historical_version_selection`, `test_contradictory_documents_ask_user`, `test_health_endpoint_no_secrets`.
Every stream reports its own `pytest` command and totals. The integrator reports the combined run.

---------------------------------------------------------------------
## 7. 17:00 HARD GATE (v4)
---------------------------------------------------------------------
All of the following in the integration branch, run live:
- [ ] `pytest -q` fully green or each failure documented
- [ ] full pipeline answers a new pasted story through the UI (real or fixture corpus, banner shown if fixture)
- [ ] invented citation blocked; forbidden phrases blocked
- [ ] out-of-scope refused; missing dates asks a question; all-rejected abstains after exactly 2 distinct retries
- [ ] a PDF upload (text) is stored, hashed, extracted, and facts show `document_supported` with page
- [ ] LLM provider can be swapped by env var with no code change
- [ ] each Tier-2 item has a status label that matches reality (anything not tested is relabelled)
If anything above fails, stop merging Tier 2 and fix it. Then proceed to evaluation.

---------------------------------------------------------------------
## 8. USER-SIDE DEPENDENCIES (THE AGENT CANNOT DO THESE)
---------------------------------------------------------------------
1. Revoke the exposed Hugging Face token (before anything else).
2. Official PDFs into `legal_corpus/originals/` by 06:30; review parser proposals and flip units to human_verified; complete source metadata (URL, retrieved date, effective dates).
3. Benchmark rows with expected provision ids and relevance/applicability labels (target 20 dev + 40 test; the agent may draft candidate user stories, but gold labels come from you against the official text; never generated by the retriever or the same LLM being evaluated).
4. Behaviour stories' expected outcomes.
5. Choice and credentials of the real LLM (`LLM_PROVIDER`, `LLM_MODEL_ID`, `LLM_BASE_URL`, `LLM_API_KEY`).
6. Any Jev documentation, only if you want a live Jev experiment.
7. Optional: 3-5 sample invoice/return screenshots with transcriptions for OCR quality measurement.
If any item is late, the agent continues in fixture mode and labels every output accordingly.

---------------------------------------------------------------------
## 9. FINAL REPORT (INTEGRATOR RETURNS)
---------------------------------------------------------------------
Use v3 Section 18, plus: a v2-coverage table (each v2 phase 0-9: IMPLEMENTED_AND_TESTED / IMPLEMENTED_NOT_TESTED / MOCKED_FOR_TESTING / DESIGN_ONLY / BLOCKED with evidence path), per-stream test totals, merge log with reverts, the cut list with reasons, and the real metric values with sample counts. No metric may be reported without a raw output file behind it.

END.
