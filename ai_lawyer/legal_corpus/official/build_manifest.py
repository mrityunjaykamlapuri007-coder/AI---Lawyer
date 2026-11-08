"""Build the provenance manifest for the downloaded official legal sources.

This is a staging tool, not part of the runtime.  It records only facts that
are printed in the documents themselves (or that were read visually from a
page whose text layer is broken).  Nothing here marks a source as verified.

Run:
    python ai_lawyer/legal_corpus/official/build_manifest.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
ORIGINALS = HERE / "originals"
EXTRACTED = HERE / "extracted_en"
RETRIEVED_AT = "2026-11-08"
LANDING_PAGE = "https://consumeraffairs.gov.in/pages/consumer-protection-acts"
DCA = "https://consumeraffairs.gov.in/public/upload/files"

# Facts below are taken from the printed notification / gazette text.
DOCUMENTS = [
    {
        "document_id": "CPA_2019",
        "file": "cpa_2019.pdf",
        "role": "principal_act",
        "title": "The Consumer Protection Act, 2019",
        "publisher": "Ministry of Law and Justice (Legislative Department)",
        "source_type": "act",
        "instrument_number": "Act No. 35 of 2019",
        "instrument_date": "2019-08-09",
        "gazette_id_as_printed": "No. 54",
        "effective_from": "2020-07-20",
        "effective_note": (
            "S.O. 2351(E) brought most provisions into force on 2020-07-20; "
            "S.O. 2421(E) brought the remainder into force on 2020-07-24."
        ),
        "version_status": "current",
        "amendment_chain": [
            "Insertion by Act 33 of 2021, s. 30 (w.e.f. 2021-04-04) at s. 58(1)(b), "
            "recorded in the India Code consolidated text.",
        ],
        "official_url": f"{DCA}/CP%20Act%202019_1732700731.pdf",
        "ingestion_status": "ready_for_review",
        "notes": [
            "Gazette copy, 40 pages.",
            "The corrigendum of 2020-04-24 must be applied before quoting the affected lines.",
            "Confirm whether any post-2021 amendment exists before human_verified.",
        ],
    },
    {
        "document_id": "CPA_2019_CONSOLIDATED",
        "file": "indiacode_cpa_2019.pdf",
        "role": "consolidated_text",
        "title": "The Consumer Protection Act, 2019 (India Code text)",
        "publisher": "India Code, Ministry of Law and Justice",
        "source_type": "act",
        "instrument_number": "Act No. 35 of 2019",
        "instrument_date": "2019-08-09",
        "gazette_id_as_printed": None,
        "effective_from": None,
        "effective_note": "Consolidated text, 'Last Updated: 17-9-2021'.",
        "version_status": "current",
        "amendment_chain": [
            "Includes 'Ins. by Act 33 of 2021, s. 30 (w.e.f. 4-4-2021)' at s. 58(1)(b).",
        ],
        "official_url": (
            "https://www.indiacode.nic.in/indiacode/bitstream/123456789/15256/1/eng201935.pdf"
        ),
        "ingestion_status": "ready_for_review",
        "notes": [
            "Useful for the amended text, but it is not a gazette copy.",
            "Last updated 2021-09-17; later amendments are not represented.",
            "39 pages; text layer is clean.",
        ],
    },
    {
        "document_id": "CPA_2019_CORRIGENDUM",
        "file": "cpa_2019_corrigendum.pdf",
        "role": "corrigendum",
        "title": "Corrigendum to the Consumer Protection Act, 2019",
        "publisher": "Ministry of Law and Justice (Legislative Department)",
        "source_type": "notification",
        "instrument_number": None,
        "instrument_date": "2020-04-24",
        "gazette_id_as_printed": "No. 27",
        "effective_from": "2020-04-24",
        "effective_note": None,
        "version_status": "current",
        "applies_to": ["CPA_2019"],
        "correction": (
            "Page 20, lines 12-13: for 'sub-sections (1) and (2)', "
            "read 'sub-sections (2) and (3)'."
        ),
        "official_url": f"{DCA}/CP%20Act%202019-corrigendum_1732702741.pdf",
        "ingestion_status": "blocked_ocr",
        "notes": [
            "Scanned image; the text layer is empty.",
            "The correction was read visually from the page image and must be "
            "applied by hand during review.",
        ],
    },
    {
        "document_id": "CPA_2019_COMMENCEMENT_1",
        "file": "cpa_2019_commencement.pdf",
        "role": "commencement_notification",
        "title": "Commencement notification (first tranche)",
        "publisher": "Department of Consumer Affairs",
        "source_type": "notification",
        "instrument_number": "S.O. 2351(E)",
        "instrument_date": "2020-07-15",
        "gazette_id_as_printed": "3150 GI/2020",
        "effective_from": "2020-07-20",
        "effective_note": "Appoints 2020-07-20 for the provisions listed in the notification.",
        "version_status": "current",
        "applies_to": ["CPA_2019"],
        "official_url": f"{DCA}/Act%20into%20force_1732702865.pdf",
        "ingestion_status": "ready_for_review",
        "notes": ["2 pages."],
    },
    {
        "document_id": "CPA_2019_COMMENCEMENT_2",
        "file": "cpa_2019_provisions_in_force.pdf",
        "role": "commencement_notification",
        "title": "Commencement notification (remaining provisions)",
        "publisher": "Department of Consumer Affairs",
        "source_type": "notification",
        "instrument_number": "S.O. 2421(E)",
        "instrument_date": "2020-07-23",
        "gazette_id_as_printed": "3259 GI/2020",
        "effective_from": "2020-07-24",
        "effective_note": "Appoints 2020-07-24 for the remaining provisions.",
        "version_status": "current",
        "applies_to": ["CPA_2019"],
        "official_url": f"{DCA}/Provisions%20of%20Act%20comes%20into%20force_1732703035.pdf",
        "ingestion_status": "ready_for_review",
        "notes": ["2 pages."],
    },
    {
        "document_id": "CCR_2020_AND_GENERAL_RULES_2020",
        "file": "cc_rules_2020_and_general_rules_2020.pdf",
        "role": "principal_rules",
        "title": (
            "The Consumer Protection (Consumer Disputes Redressal Commissions) "
            "Rules, 2020 and the Consumer Protection (General) Rules, 2020"
        ),
        "publisher": "Department of Consumer Affairs",
        "source_type": "rule",
        "instrument_number": "G.S.R. 448(E) and G.S.R. 449(E)",
        "instrument_date": "2020-07-15",
        "gazette_id_as_printed": "3146 GI/2020",
        "effective_from": "2020-07-20",
        "effective_note": (
            "CCR 2020 (G.S.R. 448(E)) and General Rules 2020 (G.S.R. 449(E)) "
            "both state 2020-07-20."
        ),
        "version_status": "current",
        "amendment_chain": [
            "CCR 2020 rule 7(2) table substituted by G.S.R. 892(E) (2022), "
            "then again by G.S.R. 606(E) (2023).",
        ],
        "official_url": (
            f"{DCA}/Consumer%20Commission%20Rules%20&%20General%20Rules_1732703661.pdf"
        ),
        "ingestion_status": "ready_for_review",
        "notes": [
            "Two instruments in one 18-page gazette PDF: English parts start at page 9.",
            "The 2023 amendment is the current fee table; the principal text alone is stale.",
        ],
    },
    {
        "document_id": "CCR_2022_AMENDMENT",
        "file": "cc_rules_2022_amendment.pdf",
        "role": "amendment",
        "title": (
            "The Consumer Protection (Consumer Disputes Redressal Commissions) "
            "Amendment Rules, 2022"
        ),
        "publisher": "Department of Consumer Affairs",
        "source_type": "notification",
        "instrument_number": "G.S.R. 892(E)",
        "instrument_date": "2022-12-20",
        "gazette_id_as_printed": "8552 GI/2022",
        "effective_from": "2022-12-21",
        "effective_note": (
            "The rules say they come into force on the date of publication in "
            "the Official Gazette. The notification dateline is 2022-12-20, but "
            "the gazette masthead is 2022-12-21, so the publication date is "
            "2022-12-21."
        ),
        "version_status": "superseded",
        "applies_to": ["CCR_2020"],
        "official_url": f"{DCA}/CP_CDRC_AmendmentRules2022_1732705759.pdf",
        "ingestion_status": "ready_for_review",
        "notes": [
            "Substitutes the rule 7(2) fee table.",
            "Superseded on that point by the 2023 amendment.",
            "The Hindi text layer has broken glyph mapping; the English text extracts cleanly.",
            "The 2023 amendment refers to this instrument as 'dated 21st December "
            "2022'; the dateline says 20th December and the gazette masthead "
            "says 21st December.",
        ],
    },
    {
        "document_id": "CCR_2023_AMENDMENT",
        "file": "cc_rules_2023_amendment.pdf",
        "role": "amendment",
        "title": (
            "The Consumer Protection (Consumer Disputes Redressal Commissions) "
            "(Amendment) Rules, 2023"
        ),
        "publisher": "Department of Consumer Affairs",
        "source_type": "notification",
        "instrument_number": "G.S.R. 606(E)",
        "instrument_date": "2023-08-17",
        "gazette_id_as_printed": "5300 GI/2023",
        "effective_from": "2023-08-17",
        "effective_note": "In force on the date of publication in the Official Gazette.",
        "version_status": "current",
        "applies_to": ["CCR_2020"],
        "official_url": f"{DCA}/CDRC%20Amendment%20Rules%202023-1_1732707073.pdf",
        "ingestion_status": "ready_for_review",
        "notes": [
            "Substitutes the rule 7(2) fee table; this is the current table.",
            "Its own note says the principal rules were last amended by "
            "G.S.R. 892(E), dated 21st December 2022 (the notification is dated 20 December).",
        ],
    },
    {
        "document_id": "ECR_2020",
        "file": "ecr_2020.pdf",
        "role": "principal_rules",
        "title": "The Consumer Protection (E-Commerce) Rules, 2020",
        "publisher": "Department of Consumer Affairs",
        "source_type": "rule",
        "instrument_number": "G.S.R. 462(E)",
        "instrument_date": "2020-07-23",
        "gazette_id_as_printed": "3261 GI/2020",
        "effective_from": "2020-07-23",
        "effective_note": "In force on the date of publication in the Official Gazette.",
        "version_status": "current",
        "amendment_chain": [
            "Corrigendum G.S.R. 488(E) (2020-08-04).",
            "Amendment Rules 2021, G.S.R. 328(E) (2021-05-17).",
            "Amendment Rules 2026, G.S.R. 789(E) (2026-09-09), effective 2027-01-01.",
        ],
        "official_url": f"{DCA}/E%20commerce%20rules_1732703966.pdf",
        "ingestion_status": "ready_for_review",
        "notes": [
            "11 pages; English part starts at page 7.",
            "The principal text alone is not the current law.",
        ],
    },
    {
        "document_id": "ECR_2020_CORRIGENDUM",
        "file": "ecr_2020_corrigendum.pdf",
        "role": "corrigendum",
        "title": "Corrigendum to the Consumer Protection (E-Commerce) Rules, 2020",
        "publisher": "Department of Consumer Affairs",
        "source_type": "notification",
        "instrument_number": "G.S.R. 488(E)",
        "instrument_date": "2020-08-04",
        "gazette_id_as_printed": "3498 GI/2020",
        "effective_from": None,
        "effective_note": (
            "The document has no commencement clause. Its dateline is "
            "2020-08-04; the gazette masthead is 2020-08-05. No effective date "
            "is stated, so none is recorded."
        ),
        "version_status": "current",
        "applies_to": ["ECR_2020"],
        "correction": (
            "Pages 8-10: replaces the Devanagari clause labels (क), (ख), (ग), "
            "(घ), (ङ), (च) with (a), (b), (c), (d), (e), (f)."
        ),
        "official_url": f"{DCA}/Corrigendum%20to%20e%20commerce%20rules_1732704181.pdf",
        "ingestion_status": "ready_for_review",
        "notes": [
            "No substantive change to the English text.",
            "Dateline 2020-08-04, gazette masthead 2020-08-05.",
        ],
    },
    {
        "document_id": "ECR_2021_AMENDMENT",
        "file": "ecr_2021_amendment.pdf",
        "role": "amendment",
        "title": "The Consumer Protection (E-Commerce) (Amendment) Rules, 2021",
        "publisher": "Department of Consumer Affairs",
        "source_type": "notification",
        "instrument_number": "G.S.R. 328(E)",
        "instrument_date": "2021-05-17",
        "gazette_id_as_printed": "2624 GI/2021",
        "effective_from": "2021-05-17",
        "effective_note": "In force on the date of publication in the Official Gazette.",
        "version_status": "current",
        "applies_to": ["ECR_2020"],
        "amends": "ECR 2020, rule 4(1): substitutes the nodal officer / resident functionary requirement.",
        "official_url": (
            f"{DCA}/Consumer%20Protection%20(E-Commerce)%20(Amendment)%20Rules,%202021_1732704241.pdf"
        ),
        "ingestion_status": "ready_for_review",
        "notes": ["2 pages."],
    },
    {
        "document_id": "ECR_2026_AMENDMENT",
        "file": "ecr_2026_amendment.pdf",
        "role": "amendment",
        "title": "The Consumer Protection (E-Commerce) (Amendment) Rules, 2026",
        "publisher": "Department of Consumer Affairs",
        "source_type": "notification",
        "instrument_number": "G.S.R. 789(E)",
        "instrument_date": "2026-09-09",
        "gazette_id_as_printed": None,
        "effective_from": "2027-01-01",
        "effective_note": "Printed as 'with effect from 1st January, 2027' (read visually).",
        "version_status": "future",
        "applies_to": ["ECR_2020"],
        "amends": (
            "ECR 2020 rules 3(1)(j), 4(2), 4(5), 4(6), 4(7), 4(11), 5 and 7(1)(a); "
            "includes return/refund/exchange disclosure and grievance timelines."
        ),
        "official_url": f"{DCA}/E%20Commerce%20Amendment%20Rules%202026_1789127949.pdf",
        "ingestion_status": "blocked_text_layer",
        "notes": [
            "The text layer drops every operative digit: G.S.R. number, dates, "
            "rule numbers and thresholds. Example: 'G.S.R.    (E)' and "
            "'with effect from  st January      .'",
            "Values above were read from the rendered page image.",
            "OCR or hand transcription is required before this text can be ingested.",
        ],
    },
    {
        "document_id": "JUR_2021",
        "file": "jurisdiction_rules_2021_candidate_a.pdf",
        "role": "principal_rules",
        "title": (
            "The Consumer Protection (Jurisdiction of the District Commission, "
            "the State Commission and the National Commission) Rules, 2021"
        ),
        "publisher": "Department of Consumer Affairs",
        "source_type": "rule",
        "instrument_number": "G.S.R. 912(E)",
        "instrument_date": "2021-12-30",
        "gazette_id_as_printed": "7647 GI/2021",
        "effective_from": "2021-12-30",
        "effective_note": "In force on the date of publication in the official gazette.",
        "version_status": "current",
        "official_url": f"{DCA}/232278_1732705181.pdf",
        "ingestion_status": "ready_for_review",
        "notes": [
            "The DCA page links the same PDF under two labels; the duplicate is "
            "recorded separately and should not be ingested twice.",
        ],
    },
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    extracted_meta = json.loads((EXTRACTED / "metadata.json").read_text(encoding="utf-8"))
    integrity = {
        item["pdf_name"]: item.get("integrity_flags", [])
        for item in extracted_meta.get("documents", [])
    }

    hashes = {}
    documents = []
    for spec in DOCUMENTS:
        path = ORIGINALS / spec["file"]
        digest = sha256(path)
        hashes.setdefault(digest, []).append(spec["document_id"])
        doc = pymupdf.open(path)
        pages = doc.page_count
        doc.close()
        entry = dict(spec)
        entry.update(
            {
                "sha256": digest,
                "bytes": path.stat().st_size,
                "pages": pages,
                "retrieved_at": RETRIEVED_AT,
                "review_status": "unverified",
                "extracted_file": (
                    f"extracted_en/{Path(spec['file']).stem}_1.txt"
                    if (EXTRACTED / f"{Path(spec['file']).stem}_1.txt").exists()
                    else None
                ),
                "integrity_flags": integrity.get(spec["file"], []),
            }
        )
        documents.append(entry)

    duplicates = [
        {
            "document_id": "JUR_2021_DUPLICATE_LINK",
            "file": "originals/jurisdiction_rules_2021_candidate_b.pdf",
            "sha256": sha256(ORIGINALS / "jurisdiction_rules_2021_candidate_b.pdf"),
            "duplicate_of": "JUR_2021",
            "note": "The DCA page links this PDF under two different labels.",
        }
    ]

    payload = {
        "generated_at": RETRIEVED_AT,
        "review_status": "unverified",
        "citation_ready": False,
        "landing_page": LANDING_PAGE,
        "publisher_note": (
            "All documents are Government of India gazette publications or "
            "India Code reproductions, downloaded from consumeraffairs.gov.in "
            "and indiacode.nic.in."
        ),
        "documents": documents,
        "duplicates": duplicates,
        "open_questions": [
            "Confirm whether the Consumer Protection Act, 2019 has been amended "
            "after 2021-09-17 (the India Code consolidated text stops there).",
            "The 2026 E-Commerce amendment is future law (effective 2027-01-01); "
            "it must not be applied to cases dated before that.",
            "The 2026 amendment PDF cannot be ingested until its digits are OCR'd.",
            "The 2020 CPA corrigendum is a scan; its one correction must be "
            "applied by hand.",
        ],
    }
    (HERE / "manifest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"wrote {HERE / 'manifest.json'} ({len(documents)} documents)")


if __name__ == "__main__":
    main()
