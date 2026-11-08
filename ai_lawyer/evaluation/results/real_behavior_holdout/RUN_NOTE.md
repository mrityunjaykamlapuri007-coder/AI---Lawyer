# Held-out run (4 unseen real cases; kept unedited)

- Cases: collected after the run-2 fixes, never used to design anything, committed with expected
  outcomes before this run (commit 2d2e3e6).
- Code: commit 97610f3 (run-4 code plus the R05/EMI fixes). Note: the header line in run.log, written by
  the launch script, says "same code as run 4"; that is inaccurate, the run started after 97610f3.
- Result: 3/4 PASS. 0 section numbers outside the verified corpus.
- Failure: H03 (soap delivered instead of a phone, return refused) was refused as out of scope: the
  deterministic scope rule treats the word "police" ("I also filed a police complaint") as a criminal
  matter. The answer was safe (no law cited, lawyer referral) but unhelpful. Not fixed: a held-out set
  is used once. Proposed fix: when the story is clearly about an order/refund, keep it in scope and add
  a lawyer note for the police aspect.
