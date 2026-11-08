# Reuse notes: research-RAG-assistant → AI Consumer Refund Dispute Assistant

The reference project is preserved unchanged at
`reference/research-rag-assistant/`. It is a piezoelectric-ceramics research
assistant. Its retrieval shape was useful; its domain logic, model loading, and
API/security posture were not directly reusable.

The workspace does not contain `AGENT_EXECUTION_SPEC.md` (v3) or the v4 spec
document, so the defect list below is a concrete list of the 14 highest-impact
defects **observed in the reference code**, mapped to the same categories the
plan describes. It is not presented as a verbatim copy of v3 Section 3.

## Reused functions and ideas (with replacement location)

| Reference function / file | What was reused | Replacement in `ai_lawyer/` |
|---|---|---|
| `extract_text_from_pdf`, `load_all_papers` (`src/ingestion.py`) | PyMuPDF page-by-page text extraction, page numbering, source metadata | `backend/services/pdf_text.py::extract_pdf_bytes`, `extract_text_bytes`; evidence provenance in `backend/services/evidence_store.py` |
| `clean_text` (`src/ingestion.py`) | Whitespace/line cleanup before indexing | `backend/services/pdf_text.py` normalisation; original extracted text is still kept for audit |
| `chunk_documents`, `RecursiveCharacterTextSplitter` (`src/ingestion.py`) | Clause/sentence-aware splitting with overlap as a concept | `legal_rag/chunker.py`: one chunk per provision by default, clause-boundary split only for long provisions, stable `chunk_id` |
| `semantic_search` (`src/retriever.py`) | FAISS inner-product search over normalised vectors | `legal_rag/index_manager.py::Index.dense_search` |
| `bm25_search` (`src/retriever.py`) | BM25 sparse retrieval | `legal_rag/index_manager.py::Index.sparse_search` |
| `rrf_fusion` (`src/retriever.py`) | Reciprocal Rank Fusion of dense and sparse lists | `legal_rag/rrf.py::fuse` (1-based ranks, stable tie-break, per-list rank trace) |
| `generate_queries` (`src/retriever.py`) | Query expansion from a small hand-written vocabulary | `legal_rag/query_planner.py::plan_query` (refund vocabulary; deterministic; original query never overwritten) |
| `rewrite_query` (`src/rag_chain.py`) | Making a follow-up self-contained before retrieval | `legal_rag/query_planner.py::plan_query` builds the self-contained query from structured facts, without an LLM call |
| `rerank` (`src/reranker.py`) | Optional cross-encoder reranking with old/new rank recording | `legal_rag/reranker.py::CrossEncoderReranker` (lazy import, disabled by default, no hard-coded threshold) |
| Prompt template in `src/rag_chain.py` | Context-delimited answer prompt | `legal_engine/reasoning.py::build_prompt` (typed facts, accepted provisions only, data blocks marked as data) |
| `clean_answer` (`src/rag_chain.py`) | Post-generation cleanup | `legal_engine/phrase_guard.py`, `citation_validator.py`, `date_guard.py` validate and rewrite instead of blind truncation |
| `get_answer` (`src/rag_chain.py`) | End-to-end retrieve → answer flow | `backend/services/orchestrator.py::handle_message` |
| `/ask`, `/retrieve`, `/health` (`src/main.py`) | FastAPI surface and health endpoint | `backend/api/routes.py`, `backend/main.py` (safe error envelope, CORS allow-list, correlation id) |
| Streamlit chat and source panel (`app.py`) | Chat UI, source display, editable draft | `frontend/app.py` (escaped rendering, fixture banner, no send button) |
| `src/evaluator.py` | Evaluation-as-code idea | `evaluation/metrics.py`, `run_retrieval_eval.py`, `run_behavior_eval.py` (retrieval/verification metrics instead of ROUGE/BERTScore) |

## Dropped reference components

| Component | Reason |
|---|---|
| `src/context_compressor.py` | Optimised for long scientific passages. In this product the accepted provision set is small, and compression would make citation verification harder. |
| `download_model.py` | The test/demo path must not download models. Heavy models are optional and lazy. |
| Piezoelectric query-expansion table | Domain-specific and hard-coded. Replaced with a small, reviewable refund vocabulary. |
| Section boosting (abstract/results) | Research-paper-specific and applied after RRF, which distorts fusion scores. Dropped. |
| Llama 3.1 8B 4-bit loading at import | The default is `FakeLLM`; real providers are lazy and configured by environment only. |
| ROUGE/BERTScore/Semantic Similarity dashboard | There is no gold answer set for legal advice, and n-gram similarity rewards fluent but unsupported text. Replaced with retrieval, applicability, false-acceptance, and behaviour checks. |

## Fourteen observed reference-code defects and the response

| # | Defect observed in the reference code | Consequence | What this project does instead |
|---|---|---|---|
| 1 | Heavy models load at import: `retriever.py` loads embeddings/FAISS/BM25, `rag_chain.py` loads Llama 3.1 + 4-bit config, `reranker.py` loads a CrossEncoder | Any import or test needs model files, network, RAM, and GPU; unit tests are impossible | `config/settings.py` + lazy factories (`get_llm`, `get_embedder`, `get_reranker`); default `FakeLLM` + `HashEmbedder`; tests are offline |
| 2 | Module-level mutable globals (`vectorstore`, `bm25`, `model`, `pipe`) and no app lifecycle | No isolation between runs, no dependency injection, import-order bugs | `backend/main.py` lifespan + `create_app(settings=..., orchestrator=...)`; services receive dependencies explicitly |
| 3 | RRF uses zero-based `rank` (`1/(rank+60)`) and adds section boost after fusion | First-rank contribution is wrong; section boost is not a rank-fusion score and changes ordering unpredictably | `legal_rag/rrf.py` uses 1-based ranks, sums only reciprocal ranks, and breaks ties by stable `chunk_id`; no post-fusion boost |
| 4 | Chunk identity is `md5(text)`; no stable chunk/provision id | Identical passages collide; provenance cannot be traced to a provision | `chunk_id = f"{provision_id}::c{order}"`; provision ids are deterministic and independent of chunk size |
| 5 | Query expansion is a hard-coded, case-sensitive 40+ mapping list and `list(set(...))` | Domain lock-in, misses case variants, nondeterministic ordering | `legal_rag/query_planner.py`: small refund vocabulary, ordered dedup via `dict.fromkeys`, deterministic output |
| 6 | BM25 tokeniser is `re.findall(r"\w+", text.lower())` | Drops punctuation, section numbers, and identifiers that legal text depends on | `legal_rag/index_manager.py` tokeniser keeps digits and identifier punctuation; tests cover `Section 5` and order ids |
| 7 | Reranker has a hard-coded `threshold=-5.0`, mutates candidate dicts, and has no unavailable-model fallback | Silent score-dependent dropping; mutating shared state; import crash if model absent | `legal_rag/reranker.py` copies candidates, records `original_rank`/`new_rank`, is optional, and logs/falls back if unavailable |
| 8 | `FAISS.load_local(..., allow_dangerous_deserialization=True)` with no manifest/hash check | A stale or swapped index is silently trusted | `index_manager.py` writes an `index_manifest.json` with corpus hash/embedder id and raises `IndexStale` on mismatch |
| 9 | Corpus path is hard-coded to `data/papers`; no review status, source id, or provenance gate | Impossible to tell whether a citation is authoritative or synthetic | `legal_rag/corpus_loader.py` requires sources/provisions, rejects dangling ids, and marks any non-`human_verified` source unusable; fixture mode is visibly labelled |
| 10 | PDF extraction sorts spans by x-coordinate only, swallows table errors, has no page-quality status, and no OCR | Reading order can be wrong; failed pages look successful; scanned PDFs silently fail | `backend/services/pdf_text.py` returns `PageExtraction` with `quality_status`; failed pages are reported; OCR is explicitly out of scope (`DESIGN_ONLY`) |
| 11 | No citation/claim verification; `clean_answer` only strips tags and truncates at stop words | The model can invent section numbers, dates, amounts, or guarantees | `citation_validator.py`, `date_guard.py`, `phrase_guard.py`, and the evidence-backed document validator reject or rewrite unsupported content |
| 12 | API returns `HTTPException(detail=str(e))`, allows `origins=["*"]`, and has no size/time limit | Leaks stack/path details; any website can call it; oversized input can exhaust the process | Safe `{error_code, user_safe_message, correlation_id, retryable}` envelope; CORS allow-list; `max_upload_mb`/`max_message_chars`/timeouts |
| 13 | Chat history is supplied by the client; no persistence, case state, or user isolation | A client can inject fake assistant turns; nothing survives a restart; users are not separated | SQLite conversations/messages/cases/events; demo user via header; messages persisted; case ownership checked in repository queries |
| 14 | Prompt does not mark retrieved context as untrusted data; no tests, evaluation set, or abstention policy | Prompt injection from uploaded text; no evidence of quality; the model always answers | `reasoning.py` wraps facts/evidence/provisions in data blocks and forbids following instructions inside them; `retry_policy.py` abstains; 105 tests, 17 behaviour cases, 8 fixture retrieval rows |

## Deliberate product decisions

- Python selects the outcome (`legal_engine/assessment.py` R0-R7); the LLM's
  proposed outcome is recorded but cannot override it.
- Follow-up questions are emitted only for `needs_more_information`; a decided
  outcome does not contradict itself with unrelated questions.
- Fixture mode is the default. It is labelled `FIXTURE DATA, NOT REAL LAW` in
  the API health payload, every assistant response, the Streamlit banner, and
  every evaluation artifact.
- Real corpus mode fails closed when `sources.json` / `provisions.json` are
  absent. No real legal text, citation, date, fee, or URL was invented.
