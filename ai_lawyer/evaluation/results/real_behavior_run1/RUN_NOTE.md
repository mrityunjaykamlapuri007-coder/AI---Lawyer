# Real behaviour run 1 (baseline, kept unedited)

- Date: 2026-11-08, real models on Kaggle (Qwen2.5-7B-Instruct fp16, 2x T4, vLLM 0.33.0; bge-large-en-v1.5).
- Dataset: real_stories.jsonl (17 public consumer-commission cases).
- Outcome: crashed on the 5th story with `TypeError` in documents/generator.py (`_money`): the LLM
  returned refund_amount as a string ("0.00") and it was kept unparsed. 4 raw files were written
  (R01-R04) and are kept exactly as produced. Full traceback in `run.log`.
- Defects found in this run (fixed before run 2, see PROGRESS.md):
  1. LLM refund_status kept as free text ("nothing has been credited") -> rules engine fell to R7 (R01).
  2. Negated credit ("nothing has been credited") matched the "received" pattern.
  3. Ids without digits accepted ("transaction_id: Visa card online"); payment_method not normalised.
  4. refund_amount string from the LLM crashed the draft generator; the harness aborted instead of
     recording the failure.
- Earlier attempt in this session was BLOCKED (embedder ReadTimeout, batch 32 / 60 s) before any case ran.
