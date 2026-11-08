# Phase 0 — Decision Record

**Date:** 2026-11-08
**Status:** Accepted
**Scope:** First real system — India e-commerce refund disputes

This record fixes the decisions that all later phases depend on. Changing a
decision here invalidates the phases below it, so changes must be recorded as
amendments, not edits.

---

## 1. Decisions

| # | Decision | Value |
|---|----------|-------|
| D1 | Model path | Cloud GPU, open-weight model |
| D2 | Compute budget | Kaggle / Hugging Face free tiers; no paid API |
| D3 | Corpus reviewer | The project owner, reviewing personally |
| D4 | Deployment target | Local only (single machine, single user) |
| D5 | Legal scope | India e-commerce refunds; the 5 supplied PDFs / 6 draft sources |

### Rejected options

| Option | Why rejected |
|--------|--------------|
| Hosted paid API | Budget is free tiers only |
| Local GPU inference | No NVIDIA GPU on this machine |
| Full-precision local `transformers` | 7B fp32 needs ~28 GB RAM; machine has 13.8 GB |
| Outsourced legal review | Owner will review personally |
| Public web deployment | Not planned; auth and DPDP obligations deferred |
| Broader consumer law / case law | Scope creep before one corpus is verified |

---

## 2. Consequence: what "cloud GPU" can and cannot mean

Kaggle and Hugging Face free compute are **ephemeral and batch-oriented**. They
are not a server.

| Use | Platform | Feasible |
|-----|----------|----------|
| Batch evaluation (50–200 cases) | Kaggle GPU notebook | Yes |
| Prompt / parameter comparison | Kaggle GPU notebook | Yes |
| Optional QLoRA experiment | Kaggle GPU notebook | Yes, if throttled |
| Always-on inference API | Kaggle / HF free | **No** — sessions end, no stable endpoint |
| Interactive local demo | This machine (CPU) | Yes, with a small quantized model |

Therefore the system uses **two model tiers**, not one.

### Tier A — Local demo (this machine, CPU)

- Runtime: Ollama (or llama.cpp), GGUF `Q4_K_M` weights
- Model: a 3B-class instruct model (e.g. `qwen2.5:3b-instruct`)
- Connection: Ollama exposes an OpenAI-compatible API, so the existing
  `OpenAICompatibleLLM` adapter is used unchanged:
  `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL=http://localhost:11434/v1`
- Expected speed on Ryzen 7 5700U (8C/16T): roughly 8–15 tokens/s, i.e.
  1–3 minutes for a full assessment plus draft. Acceptable for a
  non-interactive case workflow, not for chat.

### Tier B — Batch evaluation (Kaggle GPU)

- 7B–8B instruct model, 4-bit NF4, same prompts and same schemas
- Runs offline over the evaluation set; outputs are downloaded and compared
- Because the GPU is ephemeral, evaluation is a **reproducible notebook**,
  not a service

### Consequence for `HFLocalLLM`

The current adapter loads `transformers.pipeline(..., device=-1)` with no
quantization. On this machine that permits roughly a 1B model at best. It stays
in the codebase for small CPU models and for parity, but it is **not** the
primary path. No new adapter is required for Tier A because Ollama speaks the
OpenAI-compatible protocol.

---

## 3. Consequence: model quality risk and its mitigation

A 3B-class model is weak at strict JSON, long instructions, and citation
discipline. The architecture already limits the damage:

| LLM job | Mitigation already present |
|---------|---------------------------|
| Relevance grading (0–3) | threshold, retry-once repair, then abstain (`retry_policy.py`) |
| Prose explanation | citation guard strips unknown references (`citation_validator.py`) |
| Document drafting | fact whitelist + validator (`documents/validator.py`) |
| Outcome selection | **not done by the LLM** — Python rules R0–R7 |

Additional rule for real mode: if relevance grading fails schema validation
twice, the candidate is rejected rather than guessed. The system must prefer
abstention to a 3B model's confident error.

---

## 4. Consequence: local-only deployment

Deferred, explicitly:

- user authentication (the `X-User-Id` header remains caller-supplied)
- per-user isolation beyond the existing user_id foreign keys
- encryption at rest
- retention and deletion policy
- rate limiting

Still required even locally, because uploads contain personal data:

- the 5 MB upload limit and text-only extraction stay
- evidence files remain content-addressed by SHA-256
- no message content is logged; only counts and identifiers

Revisit D4 before any second user or any network exposure.

---

## 5. Consequence: the corpus review is now the critical path

The owner reviews 6 sources / 145 provisions. The review must produce:

- `legal_corpus/sources.json` and `legal_corpus/provisions.json`
- `review_status: human_verified` per source, with reviewer name and review date
- `official_url`, `publisher`, `published_date`, effective dates filled from an
  official copy — never invented
- every provision traceable to a page in the supplied PDF

Current draft state (for reference):

```text
6 sources · 145 provisions · 0 usable · all review_status: unverified
CPA_2019 107 · CCR_2020 18 · CCR_2020_2 5 · ECR_2020 8 · ECR_AMEND_2021 2 · JUR_2021 5
```

Mechanical flags that need a decision per item: `short_text`,
`replacement_char`, `devanagari` (6 enumeration markers), `starts_lowercase`,
`long_page_span`, plus the section-gap report.

**Review tooling is therefore the next engineering task**, because a 145-item
CSV is not a workable review surface.

---

## 6. Phase 1 acceptance criteria

Phase 1 is complete when all of these hold:

1. `CORPUS_MODE=real` starts without error
2. `GET /health` reports `mode: real`, `usable_count > 0`, and no
   "unusable because not human_verified" warning
3. Every cited provision resolves to a source with `official_url` and a
   reviewer name
4. One real case runs end to end and returns a `formal_grievance` draft whose
   citations all resolve
5. The review record lists which provisions were verified, by whom, and when

---

## 7. Ordered work after this record

| Order | Task | Depends on | Owner |
|-------|------|-----------|-------|
| 1 | Review CLI/UI for the 6 sources | this record | engineering |
| 2 | Real-mode acceptance check (fails if any source unverified) | task 1 | engineering |
| 3 | Owner reviews corpus → `sources.json` / `provisions.json` | task 1 | owner |
| 4 | Local CPU model spike (Ollama + 3B, fixture corpus) | this record | engineering |
| 5 | Real-mode end-to-end on verified corpus | tasks 2, 3, 4 | engineering |
| 6 | Kaggle batch evaluation notebook (7B, 4-bit) | task 5 | engineering |
| 7 | Labelled evaluation set (100–200 cases) | task 3 | owner + engineering |

Tasks 1–4 can proceed in parallel. Task 3 is the only one that cannot be
compressed by engineering effort.

---

## 8. Definition of done for "real"

1. `CORPUS_MODE=real` boots with at least one `human_verified` source
2. Every citation resolves to a provision with an official URL and a reviewer
3. A real model answers 50 held-out cases with zero fabricated citations
4. Zero false acceptances on the safety set
5. A named reviewer signs the evaluation report

Test count is not part of this definition.
