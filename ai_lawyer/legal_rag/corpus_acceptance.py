"""Fail-closed acceptance for a real corpus.

Two verification levels are allowed:

``human_verified``
    a named person read the provision.  ``reviewed_by`` and ``reviewed_at``
    must be present; only the review tool writes them.

``machine_verified``
    the automated pipeline recorded its evidence.  It must show at least two
    independent extraction methods, a full V1-V6 evidence record that passed,
    no integrity flags, a checked amendment chain on the source, and a source
    PDF that is byte-identical to the Gazette of India copy.

Machine verification is never described as human review anywhere.  This module
is pure; the caller decides whether to raise.
"""
from __future__ import annotations

from ai_lawyer.contracts.errors import CorpusValidationError
from ai_lawyer.legal_rag.corpus_loader import CITABLE_STATUSES, Corpus
from ai_lawyer.legal_rag.official_copy import official_copy_problems

SOURCE_PROVENANCE_FIELDS = ("publisher", "official_url", "published_date", "document_sha256")

# Every check a machine_verified provision must carry, all "pass".
MACHINE_CHECKS = (
    "V1_independent_extraction",
    "V2_number_inventory",
    "V3_document_integrity",
    "V4_metadata_evidence",
    "V5_boundary",
    "V6_amendment_effect",
)


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _machine_source_problems(source) -> list[str]:
    problems: list[str] = []
    if source.verified_by != "machine":
        problems.append(
            f"source {source.source_id} is machine_verified but verified_by is not 'machine'"
        )
    if source.verified_at is None:
        problems.append(f"source {source.source_id} is machine_verified but verified_at is missing")
    if not source.amendment_chain_checked:
        problems.append(
            f"source {source.source_id} is machine_verified but its amendment chain "
            "was never checked"
        )
    unchecked = [
        entry.instrument
        for entry in source.amendment_chain
        if entry.status != "checked"
    ]
    if unchecked:
        problems.append(
            f"source {source.source_id} has unchecked amendments: {', '.join(unchecked)}"
        )
    if not source.verification_evidence:
        problems.append(
            f"source {source.source_id} is machine_verified but has no verification evidence"
        )
    problems.extend(
        official_copy_problems(source.source_id, source.official_copy, source.document_sha256)
    )
    return problems


def _machine_provision_problems(provision) -> list[str]:
    problems: list[str] = []
    if provision.verified_by != "machine":
        problems.append(
            f"provision {provision.provision_id} is machine_verified but verified_by "
            "is not 'machine'"
        )
    if provision.verified_at is None:
        problems.append(
            f"provision {provision.provision_id} is machine_verified but verified_at is missing"
        )
    if provision.verification_method_count < 2:
        problems.append(
            f"provision {provision.provision_id} is machine_verified but has fewer than "
            "two independent extraction methods"
        )
    for check in MACHINE_CHECKS:
        if provision.verification_evidence.get(check) != "pass":
            problems.append(
                f"provision {provision.provision_id} is machine_verified but {check} "
                "did not pass"
            )
    if provision.integrity_flags:
        problems.append(
            f"provision {provision.provision_id} is machine_verified but carries "
            f"integrity flags: {', '.join(provision.integrity_flags)}"
        )
    return problems


def real_corpus_problems(corpus: Corpus) -> list[str]:
    """Return every reason this real corpus must not be used."""
    problems: list[str] = []

    verified_sources = [
        source
        for source in corpus.sources.values()
        if source.review_status in CITABLE_STATUSES
    ]

    verified_provisions = [
        provision
        for provision in corpus.provisions.values()
        if provision.review_status in CITABLE_STATUSES
    ]
    if not verified_provisions:
        problems.append(
            "real corpus contains no verified provision; nothing in it is citable, "
            "so the service must not start"
        )

    for source in sorted(verified_sources, key=lambda s: s.source_id):
        for field in SOURCE_PROVENANCE_FIELDS:
            if _blank(getattr(source, field)):
                problems.append(
                    f"source {source.source_id} is {source.review_status} but "
                    f"{field} is missing"
                )
        if source.version_status == "uncertain":
            problems.append(
                f"source {source.source_id} is {source.review_status} but its "
                "version_status is 'uncertain'"
            )
        if source.review_status == "machine_verified":
            problems.extend(_machine_source_problems(source))
        else:
            for field in ("reviewed_by", "reviewed_at"):
                if _blank(getattr(source, field)):
                    problems.append(
                        f"source {source.source_id} is human_verified but {field} is missing"
                    )

    for provision in sorted(corpus.provisions.values(), key=lambda p: p.provision_id):
        source = corpus.sources.get(provision.source_id)
        if provision.review_status == "rejected":
            problems.append(
                f"provision {provision.provision_id} is marked rejected but is present "
                "in the runtime corpus; rebuild from verified rows only"
            )
            continue
        if provision.review_status not in CITABLE_STATUSES:
            continue
        if source is None or source.review_status not in CITABLE_STATUSES:
            problems.append(
                f"provision {provision.provision_id} is {provision.review_status} but its "
                f"source {provision.source_id} is not; verify the source first"
            )
            continue

        if provision.review_status == "human_verified":
            for field in ("reviewed_by", "reviewed_at"):
                if _blank(getattr(provision, field)):
                    problems.append(
                        f"provision {provision.provision_id} is human_verified but "
                        f"{field} is missing"
                    )
        else:
            problems.extend(_machine_provision_problems(provision))

        for condition in provision.conditions:
            human = condition.human_review_status == "reviewed"
            machine = (
                condition.machine_review_status == "machine_verified"
                and bool(condition.source_quote.strip())
            )
            if not (human or machine):
                problems.append(
                    f"provision {provision.provision_id} condition "
                    f"{condition.condition_id} is neither human-reviewed nor "
                    "machine-verified with a source quote"
                )

    return problems


def enforce_real_corpus_acceptance(corpus: Corpus) -> None:
    """Raise ``CorpusValidationError`` if a real corpus fails acceptance."""
    if corpus.mode != "real":
        return
    problems = real_corpus_problems(corpus)
    if problems:
        raise CorpusValidationError(problems)
