# Walkthrough video script (max 3 minutes)

Record the screen with your own voice (Loom, or OBS + unlisted YouTube/Drive). Before recording:
Kaggle notebook running, `check_remote` = PASS, API and UI started in real mode, a refund screenshot
ready, the files below open in tabs. Do not show your `.env` or API key.

| Time | Show | Say (in your own words) |
|---|---|---|
| 0:00-0:20 | README top | "Problem 2. People whose online-shopping refund never came rarely get legal help. This assistant turns their story into a case, explains where they stand under the E-Commerce Rules 2020, recommends a next step and drafts the letter. It never invents law." |
| 0:20-1:10 | UI: paste real story R01 (mattress, cancelled 7 Oct 2024, ₹0 refunded, emailed support) | Point at: banner (model, embedder, "machine-verified, not reviewed by a lawyer"); facts tagged user-reported; provisions shown word for word with "may apply if"; outcome "formal grievance"; the draft letter with `[TO BE FILLED BY USER]` blanks. |
| 1:10-1:40 | UI: new chat, "The seller says my refund is processed but the money is not in my account." | It asks one question instead of guessing ("needs more information"). Say why: no dates, so it will not conclude. |
| 1:40-2:00 | UI: upload a refund screenshot | Facts marked document-supported, page 1, "read by OCR, check amounts". |
| 2:00-2:30 | `official_copy_crosscheck.json` and a test name, or the gate refusing fixture data | "How it avoids invented law: every source PDF is byte-identical to the Gazette of India copy, every provision checked word-for-word against OCR, citations rendered from the corpus by id, unknown section numbers blocked. Python rules pick the outcome; here the model proposed 'needs more information' and the rules overrode it." |
| 2:30-2:55 | `SUBMISSION_NOTES.md` sections 5-6 | Results with counts; one honest failure from run 1 and how it was fixed; limits (no voice, no Hindi, not lawyer-reviewed). |
| 2:55-3:00 | README | "The model is swapped in .env; it runs on a free Kaggle GPU or any OpenAI-compatible API." |

Tips: one take is fine; do not read the table aloud; keep the mouse on what you are describing.
