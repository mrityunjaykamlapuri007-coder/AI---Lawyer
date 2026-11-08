# Official Source Retrieval and Ingestion Notes

**Date:** 2026-11-08
**Status:** Staging only. Nothing in this folder is citation-ready.
**Scope:** The documents behind the India e-commerce refund corpus.

This file records where each official document came from, what state it is in,
what ingested cleanly, what is blocked, and what a human still has to decide.
It is not legal advice, and it does not mark anything as verified.

---

## 1. What exists

| Path | Contents |
| --- | --- |
| `manifest.json` | 13 documents with URL, SHA-256, bytes, pages, dates, amendment chains, integrity flags, `review_status: unverified` |
| `ingestion_plan.json` | Which documents were fed to ingestion and why the others were excluded |
| `originals/` | The downloaded PDFs, byte-for-byte |
| `extracted_en/` | English-only text extracted per document, plus `metadata.json` |
| `draft/` | Uncurated ingest: 14 sources / 266 provisions (kept for comparison, superseded) |
| `draft_curated/` | Curated staging corpus: **8 sources / 149 provisions**, all `unverified` |
| `build_manifest.py` | Reproducible manifest builder |
| `_search/`, `_download_log.json`, `_inventory.json` | Scratch artifacts from source discovery; not corpus |

The runtime does **not** read any of this. It reads
`legal_corpus/sources.json` and `legal_corpus/provisions.json`, which do not
exist yet in real mode. Until a human copies reviewed entries there, the
engine stays in fixture mode and every real-mode request fails closed.

---

## 2. Where the documents came from

- **Landing page:** <https://consumeraffairs.gov.in/pages/consumer-protection-acts>
- **Publisher:** Department of Consumer Affairs (DCA), Ministry of Consumer
  Affairs, Food and Public Distribution, Government of India.
- **File host:** `https://consumeraffairs.gov.in/public/upload/files/`
- **Consolidated Act copy:** India Code,
  `https://www.indiacode.nic.in/indiacode/bitstream/123456789/15256/1/eng201935.pdf`

Every document below is a Government of India gazette publication or an India
Code reproduction. No third-party site, blog, commentary or bare-acts
aggregator was used.

`consumeraffairs.nic.in` (the older host) refuses connections and was not used.
`indiacode.nic.in` handler pages time out repeatedly; the one direct bitstream
URL above did download.

---

## 3. Document inventory

Status values are from `manifest.json`. `integrity_flags` come from
`text_integrity_flags()` in `legal_rag/english_extract.py`.

| ID | File | Instrument | Dated | In force | Status | Ingestion | Pages | Bytes | SHA-256 (16) |
| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | --- |
| CPA_2019 | cpa_2019.pdf | Act No. 35 of 2019 | 2019-08-09 | 2020-07-20 | current | ready_for_review | 40 | 1,236,998 | 0ae7f82ab5b77d50 |
| CPA_2019_CONSOLIDATED | indiacode_cpa_2019.pdf | Act No. 35 of 2019 | 2019-08-09 | — | current | ready_for_review | 39 | 450,383 | 414fb1edd9b0f7fb |
| CPA_2019_CORRIGENDUM | cpa_2019_corrigendum.pdf | — | 2020-04-24 | 2020-04-24 | current | blocked_ocr | 1 | 2,859,968 | 3f6edfe5afd9f8b5 |
| CPA_2019_COMMENCEMENT_1 | cpa_2019_commencement.pdf | S.O. 2351(E) | 2020-07-15 | 2020-07-20 | current | ready_for_review | 2 | 1,064,098 | 636aa9e92a972c1c |
| CPA_2019_COMMENCEMENT_2 | cpa_2019_provisions_in_force.pdf | S.O. 2421(E) | 2020-07-23 | 2020-07-24 | current | ready_for_review | 2 | 1,120,231 | 817a447bb2a35c03 |
| CCR_2020_AND_GENERAL_RULES_2020 | cc_rules_2020_and_general_rules_2020.pdf | G.S.R. 448(E) and G.S.R. 449(E) | 2020-07-15 | 2020-07-20 | current | ready_for_review | 18 | 1,650,463 | 65b360f6a62bb219 |
| CCR_2022_AMENDMENT | cc_rules_2022_amendment.pdf | G.S.R. 892(E) | 2022-12-20 | 2022-12-21 | superseded | ready_for_review | 3 | 472,632 | a4a2ff2f7dfa0bc8 |
| CCR_2023_AMENDMENT | cc_rules_2023_amendment.pdf | G.S.R. 606(E) | 2023-08-17 | 2023-08-17 | current | ready_for_review | 3 | 1,503,104 | 7984ef2f8f324a46 |
| ECR_2020 | ecr_2020.pdf | G.S.R. 462(E) | 2020-07-23 | 2020-07-23 | current | ready_for_review | 11 | 1,281,359 | 3012b37f6f6dba2d |
| ECR_2020_CORRIGENDUM | ecr_2020_corrigendum.pdf | G.S.R. 488(E) | 2020-08-04 | — | current | ready_for_review | 1 | 789,211 | 47f56d66c0df51a5 |
| ECR_2021_AMENDMENT | ecr_2021_amendment.pdf | G.S.R. 328(E) | 2021-05-17 | 2021-05-17 | current | ready_for_review | 2 | 1,564,930 | a7db1f7a8c900e0b |
| ECR_2026_AMENDMENT | ecr_2026_amendment.pdf | G.S.R. 789(E) | 2026-09-09 | **2027-01-01** | **future** | blocked_text_layer | 7 | 1,428,970 | 78b0b8de1b6c0e9c |
| JUR_2021 | jurisdiction_rules_2021_candidate_a.pdf | G.S.R. 912(E) | 2021-12-30 | 2021-12-30 | current | ready_for_review | 2 | 1,182,260 | dd22dbfa7ac8bc0e |

All five PDFs in the original `legal_corpus/originals/` are byte-identical to
their DCA downloads. The new files do not replace them; they sit beside them.

---

## 4. Amendment chains

### Consumer Protection Act, 2019

1. **Act No. 35 of 2019**, gazetted 2019-08-09.
2. **Corrigendum, 2020-04-24** — page 20, lines 12–13: for
   "sub-sections (1) and (2)" read "sub-sections (2) and (3)". Printed as an
   image; the text layer is empty.
3. **S.O. 2351(E), 2020-07-15** — brings most provisions into force on
   2020-07-20.
4. **S.O. 2421(E), 2020-07-23** — brings the remaining provisions into force
   on 2020-07-24.
5. **Act 33 of 2021, s. 30 (w.e.f. 2021-04-04)** — insertion at s. 58(1)(b),
   recorded in the India Code consolidated text.
6. **Unknown after 2021-09-17.** India Code's text says
   "Last Updated: 17-9-2021". No later consolidated copy was found.

Any CPA quote must use the gazette text **with the corrigendum applied**, and
must state which commencement tranche made the provision operative.

### Consumer Protection (Consumer Disputes Redressal Commissions) Rules, 2020

1. **G.S.R. 448(E), 2020-07-15**, in force 2020-07-20. The same PDF also
   carries **G.S.R. 449(E)** (General Rules, 2020).
2. **G.S.R. 892(E), 2022-12-20** (gazetted 2022-12-21) — substitutes the
   rule 7(2) fee table. **Superseded.** The rules commence on publication, and
   the gazette masthead is 2022-12-21; the 2023 amendment also calls this
   instrument "dated 21st December 2022".
3. **G.S.R. 606(E), 2023-08-17** — substitutes the rule 7(2) fee table again.
   **This is the current table.**

The principal 2020 text alone quotes a stale fee table. A fee answer must cite
the 2023 amendment, not the 2020 rule.

### Consumer Protection (E-Commerce) Rules, 2020

1. **G.S.R. 462(E), 2020-07-23**, in force on publication.
2. **Corrigendum G.S.R. 488(E), 2020-08-04** (gazetted 2020-08-05) —
   replaces Devanagari clause labels (क), (ख), (ग), (घ), (ङ), (च) with
   (a)–(f). No change to English text, and no commencement clause; the
   manifest records no effective date.
3. **G.S.R. 328(E), 2021-05-17** — substitutes rule 4(1) (nodal officer /
   resident functionary).
4. **G.S.R. 789(E), 2026-09-09**, effective **2027-01-01** — see below.

---

## 5. The 2026 E-Commerce amendment (future law)

This is the most important retrieval finding. The corpus the project started
with does not contain it.

- **Instrument:** Consumer Protection (E-Commerce) (Amendment) Rules, 2026,
  G.S.R. 789(E), dated 2026-09-09.
- **Commencement:** "with effect from 1st January, 2027" (read from the page
  image; the text layer lost the digits).
- **Status:** `future`. It is **not** in force today (2026-11-08).
- **What it touches:** ECR 2020 rules 3(1)(j), 4(2), 4(5), 4(6), 4(7), 4(11),
  5 and 7(1)(a), including return, refund and exchange disclosures and
  grievance timelines. These specifics were read visually and are **not yet
  transcribed or verified**.

Two hard rules follow:

1. A refund dispute dated before 2027-01-01 must be answered under ECR 2020 as
   amended in 2021, not under this instrument.
2. The document cannot be ingested until its digits are recovered. A future-law
   flag alone is not enough; the text itself is currently unusable.

The engine already carries `version_status`, and
`evaluate_source_validity()` returns `not_yet_effective` for a `future` source
(unit-tested in `test_engine.py`). What is missing is a **real-corpus**
evaluation case: no fixture or official-corpus case yet pairs a pre-2027 facts
pattern with this instrument to prove the guard fires end to end.

---

## 6. Blocked documents and why

### ECR_2026_AMENDMENT — `blocked_text_layer`

The PDF has a text layer, but that layer drops **every operative digit**. It is
not a scan, so ordinary extraction appears to succeed. Examples from the
extracted file:

```
G.S.R.    (E).— In exercise of the powers conferred ...
with effect from  st January      .
vide number G.S.R. 4   (E), dated the   rd July, 2020.
```

`text_integrity_flags()` returns:

```
missing_commencement_date, missing_dated_day, missing_effective_date,
missing_gazette_number, missing_gsr_number
```

Ingesting this text would put a false G.S.R. number, a false commencement date
and wrong rule numbers into the corpus. It is excluded from the curated ingest.
The rendered pages were inspected visually; values recorded in the manifest
come from that inspection, not from the text layer.

### CPA_2019_CORRIGENDUM — `blocked_ocr`

A one-page scan with an empty text layer. Its single correction was read from
the page image and is recorded in the manifest. It must be applied by hand when
the affected CPA lines are reviewed. It is a metadata document, not a provision
source, so it is excluded from ingestion.

Both documents need OCR or hand transcription before they can enter a corpus.
No OCR engine is installed on this machine yet.

---

## 7. Duplicates

`jurisdiction_rules_2021_candidate_a.pdf` and `_b.pdf` are **byte-identical**
(SHA-256 `dd22dbfa…`). The DCA page links the same PDF under two labels.
Only candidate A is ingested; candidate B is recorded in `manifest.json` under
`duplicates` so it cannot be counted twice.

---

## 8. Curated ingestion result

**8 sources / 149 provisions. All `review_status: unverified`. All
`citation_ready: false`. Zero provisions have `conditions`.**

| Source ID | Provisions |
| --- | ---: |
| CPA_2019 | 107 |
| CC_RULES_2020_AND_GENERAL_RULES_2020 | 18 |
| CC_RULES_2020_AND_GENERAL_RULES_2020_2 | 5 |
| ECR_2020 | 8 |
| JURISDICTION_RULES_2021_CANDIDATE_A | 5 |
| CC_RULES_2022_AMENDMENT | 2 |
| CC_RULES_2023_AMENDMENT | 2 |
| ECR_2021_AMENDMENT | 2 |

Excluded from ingestion, with reasons in `ingestion_plan.json`:

| Excluded | Reason |
| --- | --- |
| CPA_2019_COMMENCEMENT | commencement notification: metadata, not a provision |
| CPA_2019_PROVISIONS_IN_FORCE | commencement notification: metadata, not a provision |
| ECR_2020_CORRIGENDUM | corrects Devanagari labels only; no English text change |
| ECR_2026_AMENDMENT | blocked: text layer lost every operative digit |
| INDIACODE_CPA_2019 | alternate consolidated text of CPA_2019; cross-check only |
| JURISDICTION_RULES_2021_CANDIDATE_B | byte-identical duplicate of candidate A |

The uncurated run in `draft/` produced 14 sources / 266 provisions. It includes
the blocked and duplicate documents and is superseded by `draft_curated/`. Do
not review `draft/`.

### 8.1 Real-mode acceptance gate

`legal_rag/corpus_acceptance.py` runs from `load_corpus()` whenever
`CORPUS_MODE=real`. It refuses to start unless:

- at least one source is `human_verified`;
- every `human_verified` source has `publisher`, `official_url`,
  `published_date`, `document_sha256`, `reviewed_by`, `reviewed_at`, and a
  `version_status` other than `uncertain`;
- every provision under a verified source has its own `reviewed_by` and
  `reviewed_at`;
- every condition under a verified provision is `human_review_status:
  reviewed`.

A verified flag with no named reviewer is treated as no evidence. A partially
reviewed corpus is allowed: verified entries must be complete, unverified
entries load but stay uncitable. Fixture mode is not gated.

---

## 9. Pipeline behaviour worth knowing

- **Bilingual gazettes.** The Hindi text layer has a broken `ToUnicode` map, so
  naive extraction yields substituted glyphs. English pages extract cleanly;
  extraction keeps English-majority pages and drops non-Latin lines verbatim,
  without repair or translation.
- **Text-layer number loss is silent.** The 2026 amendment proves a PDF can
  render correctly and still lose digits on extraction. `text_integrity_flags()`
  now checks G.S.R. number, gazette number, dated day, effective date,
  commencement date and total digit presence. It is a guard, not a repair.
- **Two instruments in one PDF.** `cc_rules_2020_and_general_rules_2020.pdf`
  contains G.S.R. 448(E) and G.S.R. 449(E); extraction splits them into two
  parts, which is why the curated set has `…_2`.
- **Titles are candidates.** Several titles are quoted from each document's own
  "may be called" sentence. They are placeholders until a reviewer confirms
  them.
- **Dateline is not publication date.** A notification can be dated one day and
  gazetted the next. When an instrument commences "on the date of publication",
  the gazette masthead governs. This bit the 2022 amendment (dated 20 December,
  gazetted 21 December) and the 2020 ECR corrigendum (dated 4 August, gazetted
  5 August).

---

## 10. Open questions a human must settle

1. **CPA amendments after 2021-09-17.** India Code's consolidated text stops
   there. Confirm whether the Jan Vishwas Act, 2023 or any later Act amended
   the CPA. If yes, obtain the gazette copy; without it the Act cannot be
   `human_verified`.
2. **2026 E-Commerce amendment.** Confirm the effective date and the full rule
   changes from the printed gazette. OCR or transcribe before ingest. Decide
   how the engine should behave for disputes that straddle 2027-01-01.
3. **CPA corrigendum.** Apply the page 20 correction by hand to the reviewed
   text and record where it was applied.
4. **Commencement.** For each CPA provision, record which S.O. brought it into
   force. The two notifications differ.
5. **Fee table.** Confirm G.S.R. 606(E) (2023) is still current and that the
   2022 table is not inadvertently quoted.
6. **Source metadata.** Every source still needs `publisher`, `official_url`,
   `published_date`, `effective_from`/`effective_to`, and a reviewer identity.
7. **Conditions.** None of the 149 provisions has structured
   conditions/provisos/exceptions. The refund flow needs them authored and
   reviewed before R0–R7 can rely on the real corpus.
8. **Retrieved-at date.** `manifest.json` records 2026-11-08 as the retrieval
   date. Re-check all URLs before any release; gazette hosts move files.

---

## 11. Reproduction

```powershell
# rebuild provenance (reads originals/, writes manifest.json)
.\.venv\Scripts\python.exe ai_lawyer\legal_corpus\official\build_manifest.py

# re-extract English text + integrity flags
.\.venv\Scripts\python.exe -m ai_lawyer.legal_rag.english_extract `
  --corpus-dir ai_lawyer\legal_corpus\official

# rebuild the curated staging corpus
.\.venv\Scripts\python.exe -m ai_lawyer.legal_rag.draft_ingest `
  --corpus-dir ai_lawyer\legal_corpus\official `
  --out ai_lawyer\legal_corpus\official\draft_curated `
  --text-dir ai_lawyer\legal_corpus\official\extracted_en `
  --originals-dir ai_lawyer\legal_corpus\official\originals `
  --manifest ai_lawyer\legal_corpus\official\extracted_en\_ingest_manifest.json `
  --as-of 2026-11-08
```

`_ingest_manifest.json` is the filtered subset of `extracted_en/metadata.json`
described in `ingestion_plan.json`. It is not generated by `english_extract`;
it is filtered from that output.

---

## 12. What this is not

- Not verified. Every source is `unverified`; every provision is unusable by
  the engine.
- Not complete. The 2026 amendment is missing from the corpus, and post-2021
  CPA amendments are unconfirmed.
- Not a substitute for a lawyer. No citation, date or URL here has been
  independently confirmed by a second person.
- Not wired into the runtime. `sources.json` and `provisions.json` still do not
  exist, so real mode fails closed by design.
