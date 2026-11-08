# AGENT_RISK_CONTROLS.md: controls so wrong law cannot reach an answer

Read after AGENT_REAL_MODE_RUNBOOK.md. These are additional tasks and rules. AGENTS.md hard rules still apply.
Principle: an official source only guarantees the right document. Every step after it can still corrupt the law. Each risk below gets (a) an automated control you build and (b) a human step for Mri. Automated checks reduce his work; they never replace his approval and never set `reviewed_by`, `reviewed_at` or `human_verified`.
Report each control as IMPLEMENTED_AND_TESTED with a real test, or say it is not.

## Risk 1: extraction errors (dropped digits, merged lines, lost words)
Controls:
- C1.1 Independent re-extraction: extract each source page a second way (a different library, or OCR if installed) and diff against the stored text after whitespace normalisation. Report word-level and number-level differences.
- C1.2 Number inventory: for each provision, list every digit sequence, section/rule reference, date and rupee amount in the stored text, and compare against the same inventory from the second extraction. Any mismatch marks the provision `flagged`.
- C1.3 Existing `text_integrity_flags()` stays mandatory and runs before a source can be source-approved.
- C1.4 Save a PNG render of each source page next to the provision so the human can compare against the picture, not just text.
Human step: look at the rendered page for every number and date.
Tests: a fixture with a deliberately dropped digit must be flagged; a fixture with a missing "not" must be flagged by the word diff.

## Risk 2: wrong metadata (dates, gazette numbers, titles)
Controls:
- C2.1 For every date, G.S.R./gazette number and effective date in a source record, store the page number and the exact quoted text it came from. A date with no quote is `uncertain`.
- C2.2 Cross-check: the same fact must agree across `manifest.json`, the extracted text and the source record. Any disagreement is flagged.
- C2.3 An effective date that is not stated in the document is stored as `not_stated`, never inferred.
Human step: confirm each date against the rendered page header.
Tests: a source with a date that disagrees with its quote is flagged; `not_stated` is preserved.

## Risk 3: stale or incomplete official text (missing amendments)
Controls:
- C3.1 Per source, an `amendment_chain` field listing every known amending instrument, with status `checked` or `unchecked`. `source-approve` refuses a source whose chain is `unchecked`.
- C3.2 Never silently drop an amendment. If an amendment is not ingested (2026 ECR amendment, CPA corrigendum), the source carries a `known_gaps` list with the reason. This list is shown in the UI and in `SUBMISSION_NOTES.md`.
- C3.3 For the Consumer Protection Act 2019, `version_status` can only become `current_for_date` after Mri records that he checked the Jan Vishwas Act 2023 (confirmed not amending the Act) and the Jan Vishwas Act 2026 schedule (open). Until then the Act stays unverified and uncitable.
Human step: check the 2026 Jan Vishwas schedule for "Consumer Protection".
Tests: unchecked chain blocks source-approve; known_gaps appear in the assessment output.

## Risk 4: wrong version for the dispute date
Controls:
- C4.1 Validity is computed in Python from the dispute date and effective dates. Superseded, future and uncertain provisions are rejected with the reason logged.
- C4.2 Add real-corpus tests: a dispute dated before 2022-12-21 must not use the CCR 2022 amendment as current; a dispute dated in 2026 must treat the 2026 ECR amendment as `not_yet_effective`; both end to end.
- C4.3 If a case's key date is unknown, validity is `uncertain` and the answer says so; it never assumes today's law applied.
Tests: the three cases above using the real staging data (read-only).

## Risk 5: missing provisos, exceptions, explanations (selection errors)
Controls:
- C5.1 Provision boundary check: flag any stored provision whose text contains "provided that", "except", "subject to", "explanation" or "notwithstanding", or whose source passage continues past the stored text, as `needs_proviso_check`.
- C5.2 Every provision keeps its parent section/rule reference and any sibling clauses ids, so related clauses can be shown together.
- C5.3 The compressor stays verbatim-prefix only and returns the full provision if a proviso would be cut (already implemented; keep tests).
- C5.4 A provision with an unresolved `needs_proviso_check` cannot be approved with the plain `approve` command. The human must pass `--proviso-checked` after reading it.
Human step: read provisos in the PDF, not just stored text.
Tests: approve is refused without the flag when a proviso keyword is present.

## Risk 6: wrong or missing conditions (applicability)
Controls:
- C6.1 The agent may only DRAFT conditions, labelled `drafted_by: agent` and `human_review_status: unreviewed`. Unreviewed conditions are never evaluated as TRUE or FALSE; the provision's applicability is `unknown`.
- C6.2 Every drafted condition stores the exact quoted source phrase it came from. A condition with no quote is rejected by the schema validator.
- C6.3 A condition test table per provision: at least one case that should be applicable, one not applicable, one unknown. Mri reviews this table; it makes mistakes visible.
- C6.4 A provision with no conditions is background only and can never be the sole basis of an outcome.
Human step: review each drafted condition against its quote, then mark reviewed.
Tests: an unreviewed condition yields `unknown`; a condition without a quote fails validation.

## Risk 7: gate weakening or silent fallbacks
Controls:
- C7.1 Add a test that fails if any code path outside the review tool writes `human_verified`, `reviewed_by` or `reviewed_at`.
- C7.2 In real mode, an empty verified corpus, a fake LLM, a hashed embedder substituting for a failed real one, or an unreachable LLM tunnel is an error, never a fallback. Embedder choice and corpus hash are recorded in every results folder.
- C7.3 `corpus_acceptance.py` changes require Mri's explicit OK. Report any diff to it.
Tests: the C7.1 scan; real mode with fake LLM refuses.

## Risk 8: answer-time errors from the LLM
Controls (extend the existing guards; do not remove any):
- C8.1 Citation validator: every provision id, section number, rule number and date shown to the user must appear in the verified corpus or the user's own facts. A number that appears in neither is a critical defect: block the answer and log it.
- C8.2 Text shown as law is rendered from the corpus verbatim, never from LLM output.
- C8.3 Quote check: any quoted law in a draft must be an exact substring of a verified provision.
- C8.4 Prompt-injection text from uploads is treated as data only (B14 covers it).
- C8.5 Log every schema failure, guard trigger and blocked answer unedited.
Tests: a fake LLM that invents "section 99" is blocked; a fake LLM quoting altered law is blocked.

## Risk 9: evaluation dishonesty
Controls:
- C9.1 Metrics only on human-labeled rows; every table prints its labeled row count. Fixture results never appear in real tables.
- C9.2 Development and test rows never mixed; any tuning is logged with the dataset it used.
- C9.3 Raw outputs are written by code; the summary generator refuses to run if a raw file was modified after creation (store hashes).
- C9.4 Failures stay in the results; do not re-run silently until a case passes. Any re-run is logged with the reason.

## Review gate checklist (the tool prints this before every `approve`)
The human must confirm each item. The tool records the answers with the approval.
- Identity: instrument, section/rule number and title match the PDF.
- Numbers: every number, date, amount verified on the rendered page.
- Words: read start to finish; shall/may/not intact.
- Provisos/exceptions/explanations present, or `--proviso-checked` given.
- Source metadata matches the PDF.
- Version in force for the dates the product will answer.

## Order of work
1. C7 and C1 (core safety and extraction diff). 2. C2, C3, C5. 3. C4 tests, C6. 4. C8, C9.
Do these alongside R2/R3, not after them. If time is short, C1, C3, C5, C7, C8.1 are mandatory. The rest can slip, and anything not done must appear under known gaps in SUBMISSION_NOTES.md.

## Report format
Per control: id, status label, test command, real output, anything that needs Mri.
