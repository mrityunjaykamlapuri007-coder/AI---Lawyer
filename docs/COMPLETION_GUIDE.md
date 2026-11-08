# Completion guide: AI Lawyer (Kuku Problem 2)

Deadline: submit by 12:00 midnight IST, 8 Nov 2026.
Owner key: **YOU** = Mri, **AGENT** = coding agent.

---

## 1. Where we stand against the brief

### On point (keep, and say so in the doc)
| Brief asks | What we have |
|---|---|
| Avoid invented laws/sections/cases | Verified corpus (30 provisions, E-Commerce Rules 2020 + 2021 amendment), each source byte-identical to the Gazette of India copy; citations rendered only from the corpus; invented section numbers blocked; forbidden-phrase guard ("violated", "guaranteed") |
| Honest about what it doesn't know | "Needs more information" with one follow-up question; abstains when no verified law applies; "may apply if..." wording |
| Say when a real lawyer is needed | `lawyer_needed` with a reason |
| Build the case | Fact extraction, timeline, user-reported vs document-supported facts |
| Explain where they stand | Python rules R0-R7 decide the recommendation; plain-English answer with verbatim law |
| Prepare documents | Support request and formal grievance drafts, `[TO BE FILLED BY USER]` blanks, nothing invented |
| Model easy to swap | One OpenAI-compatible adapter, chosen in `.env`; no code change |
| Own test cases | 17 real public consumer-commission cases (anonymised, sourced) + 17 synthetic, kept apart |
| Free tiers only | Kaggle free GPU, open models |

### Lacking (fix tonight)
| Gap | Why it matters | Step |
|---|---|---|
| No real model has ever answered | "The prototype matters"; "runs on real inputs" | 2, 4 |
| No real raw outputs | Required deliverable | 4 |
| Interview re-run depends on a Kaggle session that expires | "You'll run your solution on a new input" | 3 |
| README run steps out of date | Prototype link can be a repo "with clear run steps" | 5 |
| Repo not on GitHub | Link must open for anyone | 7 |
| Solution doc, video | Required / recommended | 6, 8 |

### Added after the first guide: image input - DONE
Screenshots/photos (PNG/JPG) and scanned PDF pages are read by local Tesseract OCR;
facts stay traceable (substring guard, page, `method: ocr`). 332 tests pass; live
Tesseract check read order id, amount and date exactly.

### Lacking (do NOT build; state as limits in the doc)
Voice input, other Indian languages, "play the other side" practice, other problem types
(deposit, salary, notices), Consumer Protection Act and Jurisdiction Rules provisions,
human/lawyer review of the corpus.

---

## 2. Steps

### Step 1. Clean state (AGENT) - DONE
315 tests pass, fixture eval 18/18, all work committed (`e4b6628`).

### Step 2. Get a real LLM and embedder running (YOU, start now)
Pick **A** for tonight's runs; add **B** if you can, for the interview.

**A. Kaggle (already built)**
1. Open `kaggle/serve_all.ipynb` on Kaggle.
2. Settings: Accelerator **GPU T4 x2**, Internet **On** (phone-verified account).
3. Accept the Llama 3.1 8B Instruct license (Hugging Face or Kaggle Models).
4. Add-ons > Secrets: `API_KEY` (any random string), `HF_TOKEN` (new read-only token).
5. Run all cells. Copy the printed lines into `.env` in the project root; replace the
   two `<...API_KEY...>` placeholders with your key.
6. Leave the last cell (heartbeat) running.

**B. Free hosted API (more reliable for the interview)**
Any free-tier provider with an OpenAI-compatible chat endpoint. Put in `.env`:
`LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL=...`, `LLM_MODEL=...`, `LLM_API_KEY=...`.
Only public or synthetic stories are sent to it.

Done when: `python -m ai_lawyer.tools.check_remote` prints PASS for both lines.

### Step 3. Make the interview re-run not depend on Kaggle (AGENT) - DONE (code)
`EMBEDDING_BACKEND=openai_compatible` uses any hosted `/embeddings` API; the client
normalises vectors and fingerprints the model from probe texts, so the index check
still works. 318 tests pass. README setup for both routes is part of Step 5.
For the interview, fully without Kaggle: hosted chat API (Step 2B) + hosted
embeddings in `.env`:
`EMBEDDING_BACKEND=openai_compatible`, `EMBEDDER_BASE_URL=...`, `EMBEDDER_API_KEY=...`,
`EMBEDDING_MODEL_ID=<provider's embedding model>`.

### Step 4. Real runs and raw outputs (AGENT, needs Step 2)
```
python -m ai_lawyer.tools.check_remote
python -m ai_lawyer.evaluation.run_behavior_eval --mode real --dataset ai_lawyer/evaluation/dataset/real_stories.jsonl --vllm-version <v> --quantization <q> --gpu-type "<gpu>"
python -m ai_lawyer.evaluation.run_behavior_eval --mode real --synthetic-table
python -m ai_lawyer.evaluation.run_real_retrieval_eval
```
Outputs: `evaluation/results/real_behavior/` (17 real), `real_behavior_synthetic/`
(17 synthetic, separate table), `real_retrieval/`, `llm_calls.jsonl`, `llm_failures.jsonl`.
Rules: never edit raw files; keep failures; log any re-run with the reason.
Then a manual UI check: `uvicorn ai_lawyer.backend.main:app` +
`streamlit run ai_lawyer/frontend/app.py`, one real story end to end, screenshot.
Done when: every story has a raw file, a summary line and a hash in the manifest.

### Step 5. README and submission notes (AGENT)
- README: what it covers / does not, exact run steps (fixture demo offline; real mode
  with Kaggle or hosted API), status labels, where raw outputs live.
- `SUBMISSION_NOTES.md`, every claim pointing to a file: tools used, where AI got it
  wrong, assumptions, scale and cost (from `llm_calls.jsonl`), results with row counts,
  failures, limits.
Done when: no number in either file lacks a source file.

### Step 6. Solution doc, 2 pages PDF (YOU; AGENT drafts facts on request)
Suggested outline (the brief's five lenses):
1. **Problem and why** - refunds that never come: frequent, small amounts, nobody
   hires a lawyer. Scope: e-commerce refund disputes in India, English text.
2. **Assumptions** - list from SUBMISSION_NOTES (R0-R7 are product rules, not legal
   truth; promised timelines are user-reported; machine-verified, not lawyer-reviewed).
3. **How it works** - one diagram: extract facts -> retrieve verified law -> verify ->
   Python decides -> guards -> answer + draft. What AI does vs code vs human.
4. **How it avoids invented law** - Gazette-matched corpus, citation-by-ID, guards.
5. **Scale and cost** - per-case tokens and seconds from `llm_calls.jsonl`; what
   changes at volume; corpus growth needs the verification pipeline, not prompts.
6. **Quality** - real-story results with counts, retrieval metrics with the label
   caveat, 2-3 specific failures.
7. **Tools and one place AI got it wrong** - pick one: OCR read "(iii)" as "(ii)";
   a provision stored with the official's signature as if it were law; real mode was
   silently falling back to a fake embedder; a build report labelled machine
   rejections "rejected by reviewer".
8. **Limits / when to see a lawyer** - from the known-gaps list.

### Step 7. Publish the repo (YOU approve, AGENT pushes)
Before pushing: secret scan, no `.env`, no downloaded PDFs or article pages (already
git-ignored / not committed). Public GitHub repo only with your explicit OK.
Prototype link = repo with run steps (the brief accepts this). A hosted demo is
optional and needs a live model, so state it plainly if not provided.

### Step 8. Video, optional (YOU)
Up to 3 minutes: one real story through the UI, show the verified citation, the
"needs more information" case, and a blocked invented section.

### Step 9. Submit (YOU)
Form: name, roll number, branch, Problem 2, doc PDF link, repo link, raw outputs
folder link (`ai_lawyer/evaluation/results/`), video link. Open every link in an
incognito window first.

---

## 3. If time runs out (cut in this order)
1. Video. 2. Hosted-embedder backend (Step 3) - say the interview needs Kaggle.
3. Synthetic real-mode table. 4. Retrieval eval (keep behaviour runs).
Never cut: real runs on the 17 stories, raw outputs, honest limits, the doc.
If no real model can run at all: submit with real-model results marked BLOCKED,
fixture raw outputs clearly labelled synthetic, and say so on page 1 of the doc.
