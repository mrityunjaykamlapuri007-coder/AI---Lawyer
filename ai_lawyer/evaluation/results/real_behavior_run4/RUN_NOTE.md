# Real behaviour run 4 (final measured run on the 17 real cases; kept unedited)

- Code: commit 4f28ea5 (run-3 fixes). Kaggle session 2; embedder hash 66fb4645 (same model as runs 1-3).
- Result: 12 PASS / 3 FAIL / 2 RECORDED. Test 8/10, development 4/5 (+2 recorded).
  0 section numbers outside the verified corpus.
- Failures:
  - R05 (dev): "I complained on the National Consumer Helpline" counted as contact with the platform
    -> formal grievance instead of informal. Fixed in 97610f3 (outside bodies are not the platform);
    not re-measured on the 17 cases.
  - R12 (test): event wording "collected from my home" / "seller received it" gave no date role
    -> missing-date rule. Known limit; not fixed (test case).
  - R16 (test): REGRESSION caused by the run-3 fix "read event words after a date": "delivered on
    December 27, 2023, but it was not what I ordered" became a second purchase date; return messages
    became return dates; the dates conflicted -> clarification instead of grievance. Not fixed (found on a
    test case, no time to re-measure). Proposed fix: use words after a date only when the date opens its
    sentence, and treat "delivered/arrived on" as a delivery date.
