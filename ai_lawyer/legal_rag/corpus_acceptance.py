"""Fail-closed acceptance gate for ``CORPUS_MODE=real``.

``validate_and_build`` will happily parse a real corpus that is entirely
unverified.  That is useful while building the review queue, but such a corpus
must never reach a running service: every provision in it is uncitable, so the
service could only answer "I have no law", and worse, a single stray
``human_verified`` flag with no named reviewer would be treated as evidence.

This gate runs from :func:`load_corpus` only for real mode.  It raises
``CorpusValidationError`` and the application refuses to start when:

* no source is ``human_verified``;
* a verified source has no publisher, official URL, publication date, document
  hash, reviewer name or review date;
* a verified source's ``version_status`` is ``uncertain``;
* a provision belonging to a verified source has no reviewer name or review
  date;
* a provision belonging to a verified source has an unreviewed condition.

Fixture mode is never gated: its synthetic sources are marked verified by
construction and must keep working without real-world provenance.
"""
from __future__ import annotations

from ai_lawyer.contracts.errors import CorpusValidationError
from ai_lawyer.legal_rag.corpus_loader import Corpus

# Required for every human_verified source in real mode.
SOURCE_PROVENANCE_FIELDS = (
    "publisher",
    "official_url",
    "published_date",
    "document_sha256",
    "reviewed_by",
    "reviewed_at",
)


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def real_corpus_problems(corpus: Corpus) -> list[str]:
    """Return every reason this real corpus must not be used.

    Empty list means the corpus passed.  The function is pure so the review
    tooling can call it without raising.
    """
    problems: list[str] = []

    verified = [
        source
        for source in corpus.sources.values()
        if source.review_status == "human_verified"
    ]
    if not verified:
        problems.append(
            "real corpus contains no human_verified source; nothing in it is "
            "citable, so the service must not start"
        )

    for source in sorted(verified, key=lambda s: s.source_id):
        for field in SOURCE_PROVENANCE_FIELDS:
            if _blank(getattr(source, field)):
                problems.append(
                    f"source {source.source_id} is human_verified but {field} is missing"
                )
        if source.version_status == "uncertain":
            problems.append(
                f"source {source.source_id} is human_verified but its version_status "
                "is 'uncertain'"
            )

    for provision in sorted(corpus.provisions.values(), key=lambda p: p.provision_id):
        source = corpus.sources[provision.source_id]
        if source.review_status != "human_verified":
            continue
        for field in ("reviewed_by", "reviewed_at"):
            if _blank(getattr(provision, field)):
                problems.append(
                    f"provision {provision.provision_id} belongs to a human_verified "
                    f"source but {field} is missing"
                )
        for condition in provision.conditions:
            if condition.human_review_status != "reviewed":
                problems.append(
                    f"provision {provision.provision_id} condition "
                    f"{condition.condition_id} is not human-reviewed"
                )

    return problems


def enforce_real_corpus_acceptance(corpus: Corpus) -> None:
    """Raise ``CorpusValidationError`` if a real corpus fails acceptance."""
    if corpus.mode != "real":
        return
    problems = real_corpus_problems(corpus)
    if problems:
        raise CorpusValidationError(problems)
