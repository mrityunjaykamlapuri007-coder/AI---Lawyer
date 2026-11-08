# RAG Parity With the Reference Project

**Goal:** use the same retrieval technique as `reference/research-rag-assistant`,
adapted where statute text makes the reference rule unsafe.

**Status:** retrieval stages complete and tested. Model-dependent stages
(BGE embeddings, cross-encoder reranker) are wired but not run, because they
need model downloads that have not been approved.

Test evidence: `167 passed` (was 141 before this work).

---

## 1. Stage-by-stage mapping

| Reference stage | Reference implementation | Legal implementation | Status |
|---|---|---|---|
| PDF extraction | PyMuPDF blocks, 0.75 font filter, tables flattened | `legal_rag/english_extract.py`, `draft_ingest.py` — English-only gazette parts, page-tracked | Already present |
| Chunking | `RecursiveCharacterTextSplitter(1024, 200)` | `legal_rag/chunker.py` — one chunk per provision, split at clause boundaries | Already present (safer) |
| Dense index | BGE-Large → FAISS | `legal_rag/index_manager.py` + `embedders.py` | Present; hash embedder active, BGE not run |
| Sparse index | BM25 over chunks | same, provision-level | Already present |
| Query expansion | 49 hardcoded `(old, new)` pairs | `legal_rag/query_planner.py` — 10 issue tags, up to 3 expansions | Already present |
| Multi-query | one variant per matched pair | `QueryPlan.variants()` | Already present |
| RRF fusion | `1/(k+rank)`, k=60 | `legal_rag/rrf.py` | Already present |
| Section boost | +0.08 … +0.20 by paper section | `legal_rag/boosting.py` — explicit reference + qualifier tie-break | **Added now** |
| Cross-encoder rerank | BGE-reranker-large, threshold −5 | `legal_rag/reranker.py`, `cross-encoder` | Present, disabled, unmeasured |
| Context compression | score sentences, splice the best | `legal_rag/compressor.py` — contiguous verbatim prefix | **Added now** |
| Grounded prompt | strict context-only | `legal_engine/reasoning.py` | Already present (stricter) |
| Serving | FastAPI + Streamlit | `backend/api/routes.py`, `frontend/app.py` | Already present |
| Evaluation | ROUGE / BERTScore / cosine | `evaluation/` — precision, recall, MRR, nDCG, applicability, abstention | Deliberately different |

---

## 2. What was added

### 2.1 Boosting (`legal_rag/boosting.py`)

The reference adds a fixed bonus for a detected paper section. A generic bonus
cannot be used for statutes: it can outrank the provision the user named.

Two mechanisms replace it:

| Mechanism | Effect | Why |
|---|---|---|
| Explicit reference (`"section 35"`, `"rule 12(1)"`, `"article 21"`) | adds `exact_reference_boost` (0.5) to the fused score | a named section must be able to override a dense/sparse disagreement |
| Qualifying material (provisos, exceptions, `hierarchy_type == "proviso"`) | **tie-break only**, never changes a score | a proviso must never be suppressed by its parent clause, and must never hijack the ranking |

### 2.2 Calibration finding

The first implementation gave every qualifying provision `+0.02`. At `k=60`
a single RRF list contributes about `0.016`, so `0.02` was larger than the
entire fusion spread. One fixture provision (the only one with a proviso)
surfaced on every query:

| Configuration | Hybrid dev MRR | Hybrid test MRR |
|---|---|---|
| No boost (baseline) | 0.8167 | 0.90625 |
| Miscalibrated `+0.02` qualifier bonus | **0.4833** | **0.4833** |
| Corrected (score bonus only for explicit references) | 0.8167 | 0.90625 |

The corrected run is identical to the baseline, which is expected because no
fixture query names a section. The reordering behaviour is proven by unit and
integration tests instead.

### 2.3 Compression (`legal_rag/compressor.py`)

The reference splices the best-scoring sentences together. That is unsafe for
statutes — dropping a proviso can invert a rule.

The legal version may only return a **contiguous prefix** of the provision:

* verbatim, never rewritten, never reordered;
* every proviso/exception sentence must fit inside the budget, otherwise the
  text is returned **unchanged**;
* the corpus keeps the full text, so citation and phrase guards still validate
  against the complete provision.

Both stages are **off by default**. The fixture evaluation is unchanged and
reproducible.

---

## 3. How to enable

```powershell
# Retrieval boosting
$env:BOOST_ENABLED = "true"

# Prompt-time verbatim compression
$env:COMPRESSION_ENABLED = "true"
$env:COMPRESSION_MAX_CHARS = "1200"

# Evaluation variants (harness-level, also recorded in run_manifest.json)
$env:RAG_BOOST = "1"
$env:RAG_COMPRESSION = "1"
```

Settings (`ai_lawyer/config/settings.py`):

```text
boost_enabled            false
exact_reference_boost    0.5
qualifier_tiebreak       true
compression_enabled      false
compression_max_chars    1200
```

---

## 4. Measurement

Both runs use the same 16-row fixture set (8 development + 8 test), K=5.

Artifacts kept side by side:

```text
evaluation/results/boost_off/   default configuration
evaluation/results/boost_on/    BOOST_ENABLED=true
```

`run_manifest.json` records `boost_enabled` and `compression_enabled`, so the
two runs cannot be confused.

---

## 5. Deliberately not copied

| Reference behaviour | Reason |
|---|---|
| Sentence-splice compression | can change the meaning of a statutory clause |
| Paper-section bonuses (abstract +0.20) | no legal analogue; a generic bonus displaces cited provisions |
| Best-of-N ROUGE/BERTScore scoring | measures surface overlap, not citation correctness or abstention |
| Same 42 questions for tuning and reporting | no held-out set; not acceptable evidence for a legal system |
| Import-time model loading | prevents testing and makes failures opaque |
| CORS `*` and raw exception text | leaks internals |

---

## 6. Remaining parity work (blocked)

| Item | Blocker |
|---|---|
| BGE-Large embeddings instead of `HashEmbedder` | `sentence-transformers` + `torch` install, ~1.3 GB model |
| BGE cross-encoder reranker (E4) | install + ~1.1 GB model |
| ROUGE / BERTScore parity metrics | `rouge-score`, `bert-score`, `torch` |

These are optional for the legal system: the evaluation that matters is
citation precision/recall, abstention, and human review, not ROUGE.
