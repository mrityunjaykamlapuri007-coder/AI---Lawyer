<!--
DRAFT for the 2-page PDF. Edit in your own words: the brief says the decisions must be yours.
[YOUR CALL] marks places to confirm or rephrase. Remove these comments before exporting.
Target: ~950 words, 2 pages at 10-11 pt. Facts and numbers are taken from SUBMISSION_NOTES.md.
-->

# AI Lawyer for refunds that never came — Kuku Problem 2

**[Name] · [Roll no.] · [Branch]** · Prototype: [GitHub link] · Raw outputs: `ai_lawyer/evaluation/results/`

## 1. Problem and why this one

A refund that never arrives after a cancelled or returned online order is one of the most common
legal problems an ordinary person in India has, and one of the least likely to reach a lawyer: the
amount is small, the process is unclear, and the platform's support loop wears people down.
[YOUR CALL: one line on why you chose this over deposits/salary — e.g. frequent, document-heavy,
and governed by one short set of rules that can be verified end to end.]

**Scope (assumption):** unresolved e-commerce refunds in India; English; text plus screenshots or
PDFs as proof. Out of scope: voice, other languages, other disputes, Consumer Commission filing.

## 2. What it does for the user

The user tells their story (and can attach a screenshot or PDF). The assistant (1) **builds the
case**: dates, amount, refund status, who was contacted, each fact tagged *user-reported* or
*document-supported* and kept only if its words appear in the source; (2) **explains where they
stand** with the relevant E-Commerce Rules 2020 provisions shown word for word as "may apply if…";
(3) **recommends one proportionate next step** — wait (still inside the seller's own promise),
contact support, formal grievance to the platform's grievance officer, or "I need one more fact";
(4) **drafts the letter** with `[TO BE FILLED BY USER]` blanks. It never files anything, never
says the seller "broke the law", and flags when a lawyer is needed.

## 3. How it works: what is AI, what is code, where the human is

```text
story (+ screenshot -> local OCR) -> scope check -> fact extraction -> retrieval (BGE dense + BM25, RRF)
 -> relevance grading + rule-based applicability -> Python outcome rules R0-R7 -> guards -> answer + draft
```

| LLM (Qwen2.5-7B, swappable in `.env`) | Code | Human |
|---|---|---|
| scope check, fact extraction, relevance grading, wording the explanation | corpus verification, retrieval, applicability, **choosing the outcome**, every guard, the draft | sends the letter, decides to escalate, sees a lawyer when flagged |

**Python owns the outcome.** In a real run the model proposed "needs more information" for a case
that clearly called for a grievance; the rules overrode it and logged the disagreement.

## 4. How it avoids invented law

- **Small verified corpus instead of model memory:** 30 provisions of the E-Commerce Rules 2020 and
  the 2021 amendment. Each source PDF is **byte-identical to the Gazette of India copy**; each
  provision's text matches an independent OCR reading word for word, numbers exact, with amendments
  applied at sub-rule level. Machine-verified — **not lawyer-reviewed**, and said so in the UI.
- **Citations by id, rendered from the corpus**, never from model text; unknown ids are blocked.
- **Any section number not in the corpus blocks the answer.** Result: **0** such numbers in 50
  real-model answers.
- **Abstention:** no applicable verified provision → it says so and asks; it never fills the gap.

## 5. How I know it's good — and where it fails

**Test cases:** 17 real disputes restated from public reports of consumer-commission orders
(anonymised, sourced, split 7 development / 10 test before any run; expected outcome = the rules
applied to the stated facts) + 17 synthetic edge cases reported separately.

| Run (real model on Kaggle) | Test (n=10) | Dev | Notes |
|---|---|---|---|
| 1 | crashed on case 5 | | 4 defects: free-text status, negation, junk ids, amount crash |
| 2 | 8/10 | 2/5 | 0 invented sections, 0 schema failures |
| 3 | 6/17 overall | | tunnel died; output cap; a regression from my own fix |
| **4** | **8/10** | **4/5** | final run |
| **Held-out** (4 unseen, pre-registered) | **3/4** | | collected after the fixes |

**Where it fails (fact extraction and scope, never invented law):** a credited refund labelled
"processed"; two events in one sentence swapping dates; "August 16th" silently given this year
(fixed); contact worded as "sent notices" missed (fixed); a fix of mine that read words *after* a
date then turned a delivery date into a purchase date (R16, reported, not hidden); a story that
mentioned a police complaint was refused as "criminal" (held-out H03: safe but unhelpful). Retrieval: the top
results are the refund-specific rules, but machine-derived labels can only score two generic
provisions (recall@10 0.57, test) — the metric is weak, and I say so.

## 6. Scale and cost

Per case: ~5 LLM calls, ~9,300 tokens, ~82 s on two free Kaggle T4s; cost at volume =
tokens × the provider's price, and the model is swapped in `.env` (any OpenAI-compatible API).
Retrieval runs locally and is cheap. Growing coverage means feeding new Gazette PDFs through the
same verification pipeline, not longer prompts. [YOUR CALL: one line on what you would do first at
real volume — e.g. lawyer review of the corpus, a hosted model, caching per platform.]

## 7. Tools, and one place the AI got it wrong

Claude Code (coding agent), [YOUR TOOLS for the specs], Kaggle, vLLM, Qwen2.5-7B, BGE, Tesseract.
**Where it got it wrong:** [YOUR CALL — pick one] the coding agent wrote a 4-bit model id from memory
that does not exist on Hugging Face; a check caught it before it broke the Kaggle run. / A verified
provision was stored with the official's signature as if it were law, caught by comparing with a
second official copy.

## 8. Limits and when to see a lawyer

Not lawyer-reviewed; no Consumer Protection Act yet, so it stops at the grievance stage; English
text only; OCR measured on clean images only; local demo (no login, files stored unencrypted).
It tells the user to see a lawyer for court or limitation deadlines, fraud, unclear liability
between seller, platform and bank, or when they want representation.
