# Real behaviour run 3 (kept unedited)

- Code: commit 3e99a11 (run-2 extraction fixes, designed from development cases).
- Result: 6/17 PASS. Worse than run 2, for three reasons found in the raw files:
  1. **Infrastructure:** R15-R17 crashed with HTTP 530: the Kaggle tunnel died mid-run.
  2. **Output cap:** R02, R03 drafting answers were cut off at LLM_MAX_TOKENS=1500 (invalid JSON,
     `llm_failures.jsonl`); the system refused to show a half-answer, as designed.
  3. **Regression from the run-2 fix:** an LLM date was kept only if an event word came *before*
     it. "On 14 March 2024 I bought..." and "collected on 24/07/2023" lost their dates, so the
     missing-date rule fired (R05, R07, R11).
- Fixed for run 4: LLM_MAX_TOKENS=3000; event words after the date count; "collected" is a pickup
  word; an LLM date is dropped only when the text marks it as a delivery date.
