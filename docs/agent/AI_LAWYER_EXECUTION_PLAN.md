# AI Lawyer: Realistic Build and Execution Plan
Deadline: Sun 8 Nov 2026, 12:00 midnight IST. Plan written at 05:05. About 19 hours, of which roughly 11 are productive build time.

## 1. The essence (what must survive no matter what)
These are the ideas the project is judged on. Every cut decision protects them.

1. **No invented law.** Every legal statement traces to a verbatim provision in a hand-verified corpus, cited by stable ID. Citations are rendered from the corpus, never from model text.
2. **Retrieved is not accepted.** Relevance, applicability (TRUE/FALSE/UNKNOWN) and source validity are separate labels.
3. **Unknown stays unknown.** Missing facts lead to a question or "needs more information", never a guess.
4. **Facts keep provenance.** Each fact is tagged user_reported or document_supported.
5. **Proportionate action.** Four outcomes plus needs_more_information and out_of_scope. Delay alone is never a violation.
6. **Python owns the rules.** The LLM drafts, deterministic code gates.
7. **Swappable model.** One adapter, one config line.
8. **Honest evaluation.** Own test cases, raw outputs unedited, failures reported.

## 2. Honest status labels (use these in README and doc)
IMPLEMENTED_AND_TESTED / IMPLEMENTED_NOT_TESTED / MOCKED_FOR_TESTING / DESIGN_ONLY / BLOCKED.
Never describe anything but the first as working.

## 3. What gets built, by tier

### Tier 1: real and tested (hard gate at 17:00)
| Component | Keeps v2.0 module name | Minimum that counts |
|---|---|---|
| Source registry + corpus | legal_rag/source_registry.py, ingestion.py | JSON manifest with official URL, retrieved date, hash, version label, review status. 15-25 hand-checked provisions with verbatim text and stable provision_id |
| Retrieval | retriever.py, rrf.py, query_planner.py | FAISS + BM25 independently, multi-list RRF, ordered dedup of queries, stable IDs, per-list ranks logged |
| Context expansion | provision_expander.py | Parent / proviso / exception / definition links stored in the corpus JSON and followed |
| Verification | relevance_filter.py, applicability_validator.py, version_validator.py | Three separate labels per candidate; 3-valued condition check for a handful of hand-structured conditions |
| Retry + abstention | decision_controller.py | Max 2 retries, no repeated query, then abstain and ask |
| Reasoning | reasoning.py + LLM adapter | Pydantic-validated JSON, IDs only for citations |
| Citation guard | citation_validator.py | Unknown ID => claim blocked and flagged |
| Assessment | assessment.py | Outcomes as in spec, plus lawyer_needed with reason |
| Document | documents/grievance_generator.py | One template, placeholders `[TO BE FILLED BY USER]`, DRAFT label |
| API + UI | backend/main.py, frontend/app.py | One POST per message, escaped output, safe errors |

### Tier 2: real but minimal
- SQLite: users, conversations, messages, cases, case_events (append-only), case_facts. Case match on exact order_id only; anything ambiguous asks the user.
- Evidence: paste text, upload text-PDF (PyMuPDF), SHA-256 on the stored original, evidence row with extraction status. OCR is MOCKED/DESIGN_ONLY.
- Evaluation: about 15 development and 25-30 held-out cases. P@K, R@K, MRR, nDCG implemented and unit-tested. Run E1-E4 (and E5 if time allows). State clearly that this is NOT the full 150 and the held-out cases were not used for tuning.

### Tier 3: DESIGN_ONLY (documented, not coded)
Jev (flag off), RAGAS, OCR for scans, snapshots/archive, NCH summary and Consumer Commission drafts, the full 150-question set, LLM claim-entailment check, automatic corpus updating.

## 4. Critical path and who does what
**You (human, cannot be delegated):**
- Revoke the exposed Hugging Face token (2 min, do first).
- Build the corpus from official sources: choose provisions, copy verbatim text, record URLs and dates. The agent must never write law from memory.
- Write the test cases with expected outcomes (you decide the "right" answer).
- Write the solution doc decisions (what is AI vs code, assumptions, one real AI mistake).

**Coding agent:** everything else, one phase at a time, with tests run before moving on.

**Dependency:** corpus -> retrieval -> verification -> reasoning -> UI. The corpus is the bottleneck. Start it immediately.

## 5. Hour-by-hour schedule (IST)
| Time | You | Agent |
|---|---|---|
| 05:05-05:30 | Revoke HF token; new private repo `ai-lawyer`; copy needed files from research-rag-assistant (repo untouched); set `.env` | Read old repo and MVP spec; produce checklist |
| 05:30-08:30 | **Corpus**: fetch official Act and Rules, select 15-25 provisions, fill JSON (id, citation, verbatim text, source URL, parent, provisos, conditions) | Scaffold: settings, .env.example, .gitignore, LLM adapter with fake model, Pydantic schemas, unit-test harness |
| 08:30-10:30 | Review corpus once against the source pages | Phase 2: FAISS, BM25, RRF, query planner, expander. Tests for RRF, determinism, stable IDs |
| 10:30-12:30 | Draft test cases (see section 6) | Phase 3: relevance/applicability/validity labels, retry/abstain, decision controller. Tests |
| 12:30-13:30 | Lunch, then review agent output | Phase 5: reasoning + citation guard. Test with fake model that invents a section |
| 13:30-15:00 | Pick the real LLM (free-tier API or local), set env | Assessment, document template, SQLite minimal, single endpoint |
| 15:00-16:30 | Try the app manually on 3 new stories | Streamlit UI; metric functions + unit tests |
| 16:30-17:00 | **GATE** (see section 7) | Fix blockers only |
| 17:00-18:30 | Run evaluation, save raw outputs untouched | Eval runner (E1-E4), writes raw_outputs/ and results/ |
| 18:30-19:30 | Write failure_analysis.md from real failures | README with run steps, limits, status labels |
| 19:30-21:30 | Write the 2-page doc | Idle or small fixes |
| 21:30-22:30 | Record 3-min video (optional) | n/a |
| 22:30-23:30 | Submission checklist, test links in an incognito window | n/a |
| 23:30-24:00 | **Buffer. Do not plan to use it.** | n/a |

## 6. Test cases (write these yourself, about 15 development + 25-30 held-out)
Spread of categories, each with: story, case facts, expected provision IDs (essential / supporting), expected outcome, expected applicability labels.
- Routine delay with dates (3-4)
- Return approved, money not received (3)
- Denied / partial / incorrect refund (3)
- Seller vs platform vs payment provider (3)
- Grievance / escalation process questions (3)
- Multi-provision scenario (2-3)
- Ambiguous or contradictory facts (2-3)
- Missing key dates, must ask (2)
- Out of scope: tenancy deposit, salary, divorce (2-3)
- Bait prompt asking for an invented section or a guaranteed win (1-2)
- User never contacted support, informal resolution expected (2)
Keep the development set and held-out set on different underlying scenarios. Never tune on held-out.

## 7. The 17:00 gate
Must be true, or cut Tier 2 items in the order listed in section 8:
- [ ] Corpus loads, every provision has verbatim text and source URL
- [ ] One pasted story produces a structured answer end to end in the UI
- [ ] An invented citation ID from a fake model is blocked (test passes)
- [ ] Out-of-scope story is refused with no legal claims
- [ ] Missing-date story produces a question, not a conclusion
- [ ] Unit tests for RRF and the metrics pass
If the first three are not true at 17:00, stop adding features and fix those.

## 8. Cut order if behind (cut in this order, never cut the essence)
1. Reranker and E4/E5 ablations
2. Optional video
3. Evidence upload (keep paste text)
4. SQLite case matching beyond create-and-append
5. Document template (keep as a static example in the doc)
6. Held-out set size (reduce to 15, say so)
Never cut: corpus verification, citation guard, abstention, unknown handling, raw outputs, honest failures.

## 9. Solution doc (2 pages) outline
1. Problem and why: refund disputes, who it helps, scope and what is excluded (voice, other languages, other laws, OCR) as stated assumptions
2. Architecture in one diagram: retrieve -> verify -> reason -> guard -> assess -> draft
3. AI vs code vs human: LLM for fact extraction and drafting; Python for gating, citation checks, outcomes; human reviews every document
4. How it avoids invented law: corpus-only citations by ID, verbatim rendering, abstention
5. Scale and cost: tokens per case, local or free models, cost per case, what changes at volume, human review of the corpus
6. Quality: test design, metrics, honest results, failures (specific examples)
7. Tools used and one place they got it wrong (record a real one as it happens)
8. Limits and when a real lawyer is needed

## 10. Risks and mitigations
- Corpus takes longer than 3 hours: shrink to 12-15 provisions and note it.
- Old repo dependency problems: pin only what you import, test in a clean venv before 10:30.
- LLM returns invalid JSON: one repair attempt, then controlled error; already in spec.
- Small local model weak: use a free-tier API for the demo; the adapter makes it a config change.
- Running out of time: the 17:00 gate and cut order above decide, not hope.

## 11. Submission checklist
- [ ] Solution doc PDF, 2 pages
- [ ] Repo link opens for anyone (no secrets, no .env, no customer data)
- [ ] raw_outputs/ folder with unedited files
- [ ] README: run steps, assumptions, status labels, known failures
- [ ] Video link (optional) set to anyone-with-link
- [ ] HF token revoked and not present in the repo or its history
