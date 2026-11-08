# Draft corpus review guide

These files are **drafts generated mechanically from extracted text**.
Nothing here is legal advice and nothing here may be cited until a human
reviews it. Every source is written with `review_status: unverified`, so
the engine treats every provision as unusable.

## Files

- `draft_sources.json` / `draft_provisions.json` - schema-valid drafts.
- `sources_review.csv` - source metadata worksheet (URLs and dates are blank).
- `provisions_review.csv` - one row per provision, with a text preview.
- `REVIEWER_CHECKLIST.md` - per-source checklist with mechanical quality
  flags and the metadata fields a human must fill.
- `draft_manifest.json` - counts and per-document OCR quality.

## Review steps

1. Check the empty `publisher`, `official_url`, `published_date`,
   `effective_from` and `effective_to` fields against an official copy.
2. Fix the extracted title if `title_status` is `placeholder`; if it is
   `candidate`, confirm the title quoted from the document's own
   'may be called' sentence.
3. The `candidate_dates`, `candidate_departments` and
   `candidate_gazette_ids` columns are quotations from the document, not
   decisions. Confirm or replace them before setting any Source field.
4. Read each provision in `provisions_review.csv`. Mark `approve`, `edit`
   or `reject`; split or merge sections in the JSON if the mechanical
   segmentation is wrong.
5. Re-extract any document whose `ocr_risk` is `high`. Garbled text must
   not be approved as-is.
6. Only after review, copy the approved entries to `legal_corpus/sources.json`
   and `legal_corpus/provisions.json` and set `review_status` to
   `human_verified` for sources you personally checked. Set
   `human_review_status` to `reviewed` on any condition you verified.
7. Set `reviewed_by` and `reviewed_at` on every source and provision you
   verified. Real mode refuses to start without them: a verified flag with
   no named reviewer is treated as no evidence at all.
8. Rebuild the index with `CORPUS_MODE=real` and rerun the evaluation.

## Documents in this draft

| source_id | file | sections | pages | OCR risk | notes |
| --- | --- | --- | --- | --- | --- |
| CC_RULES_2020_AND_GENERAL_RULES_2020 | cc_rules_2020_and_general_rules_2020_1.txt | 18 | 16 | low | title taken from the document's 'may be called' sentence; confirm it |
| CC_RULES_2020_AND_GENERAL_RULES_2020_2 | cc_rules_2020_and_general_rules_2020_2.txt | 5 | 18 | low | title taken from the document's 'may be called' sentence; confirm it |
| CC_RULES_2022_AMENDMENT | cc_rules_2022_amendment_1.txt | 2 | 3 | low | title taken from the document's 'may be called' sentence; confirm it |
| CC_RULES_2023_AMENDMENT | cc_rules_2023_amendment_1.txt | 2 | 3 | low | title taken from the document's 'may be called' sentence; confirm it |
| CPA_2019 | cpa_2019_1.txt | 107 | 40 | low | - |
| ECR_2020 | ecr_2020_1.txt | 8 | 11 | low | title taken from the document's 'may be called' sentence; confirm it |
| ECR_2021_AMENDMENT | ecr_2021_amendment_1.txt | 2 | 2 | low | title taken from the document's 'may be called' sentence; confirm it |
| JURISDICTION_RULES_2021_CANDIDATE_A | jurisdiction_rules_2021_candidate_a_1.txt | 5 | 2 | low | title taken from the document's 'may be called' sentence; confirm it |

Generated: 2026-11-08
