"""Known gaps in the real corpus, shown in the UI, the API and the submission notes.

Each item is a fact recorded in legal_corpus/official/manifest.json,
RETRIEVAL_NOTES.md or PROGRESS.md.  None of it is legal text.
"""
from __future__ import annotations

TRUST_NOTE = {
    "machine": "Corpus is machine-verified (automated checks against the official Gazette copy); "
               "it has NOT been reviewed by a human or a lawyer.",
    "human": "Corpus rows are human-verified only.",
}

KNOWN_CORPUS_GAPS: tuple[str, ...] = (
    "Consumer Protection (E-Commerce) Amendment Rules, 2026 (effective 2027-01-01) are not ingested: "
    "the PDF text layer drops every operative digit.",
    "Consumer Protection Act, 2019 is not citable: the 2026 Jan Vishwas Act schedule check is not recorded, "
    "and the 2020 corrigendum is a scan that was not ingested.",
    "E-Commerce Rules 2020 rule 3 (definitions) is excluded: text layer and OCR disagree on one clause label.",
    "E-Commerce Rules 2020 rule 4(1) is excluded as substituted; its 2021 replacement is included.",
    "Jurisdiction Rules 2021 (pecuniary limits) are excluded: OCR disagrees on the printed gazette number.",
    "No Consumer Commission complaint-route provision is verified, so 'formal proceedings may be justified' "
    "is never recommended.",
)


def gaps_for(sources) -> list[str]:
    """Static gaps plus any known_gaps recorded on the loaded sources."""
    out = list(KNOWN_CORPUS_GAPS)
    for source in sources:
        for gap in getattr(source, "known_gaps", []) or []:
            item = f"{source.source_id}: {gap}"
            if item not in out:
                out.append(item)
    return out
