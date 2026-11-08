from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from ai_lawyer.contracts.errors import CorpusValidationError
from ai_lawyer.legal_rag.corpus_acceptance import real_corpus_problems
from ai_lawyer.legal_rag.corpus_loader import load_corpus

REAL_SOURCE = {
    "source_id": "REAL_ACT",
    "title": "A verified Act",
    "source_type": "act",
    "publisher": "Department of Consumer Affairs",
    "official_url": "https://example.gov.in/act.pdf",
    "published_date": "2020-07-20",
    "retrieved_at": "2026-11-08",
    "document_sha256": "a" * 64,
    "review_status": "human_verified",
    "version_label": "2020",
    "effective_from": "2020-07-20",
    "effective_to": None,
    "version_status": "current",
    "reviewed_by": "reviewer-name",
    "reviewed_at": "2026-11-08",
    "notes": "",
}

REAL_PROVISION = {
    "provision_id": "REAL_ACT_S1",
    "source_id": "REAL_ACT",
    "citation": "Section 1",
    "hierarchy_type": "section",
    "parent_provision_id": None,
    "original_text": "Verbatim text of section 1.",
    "search_text": "verbatim",
    "provisos": [],
    "exceptions": [],
    "definitions_used": [],
    "cross_references": [],
    "mandatory_context": [],
    "conditions": [],
    "page_start": 1,
    "page_end": 1,
    "review_status": "human_verified",
    "reviewed_by": "reviewer-name",
    "reviewed_at": "2026-11-08T12:00:00Z",
    "review_note": None,
}


def _write(tmp_path: Path, sources, provisions) -> None:
    (tmp_path / "sources.json").write_text(json.dumps(sources), encoding="utf-8")
    (tmp_path / "provisions.json").write_text(json.dumps(provisions), encoding="utf-8")


def test_real_corpus_with_no_verified_provision_is_rejected(tmp_path):
    provision = {**deepcopy(REAL_PROVISION), "review_status": "unverified"}
    _write(tmp_path, [deepcopy(REAL_SOURCE)], [provision])

    with pytest.raises(CorpusValidationError) as exc:
        load_corpus("real", corpus_dir=tmp_path)

    assert any("no human_verified provision" in e for e in exc.value.errors)


def test_verified_provision_under_unapproved_source_is_rejected(tmp_path):
    source = {**deepcopy(REAL_SOURCE), "review_status": "unverified"}
    _write(tmp_path, [source], [deepcopy(REAL_PROVISION)])

    with pytest.raises(CorpusValidationError) as exc:
        load_corpus("real", corpus_dir=tmp_path)

    assert any("approve the source first" in e for e in exc.value.errors)


def test_verified_source_without_reviewer_is_rejected(tmp_path):
    source = {**deepcopy(REAL_SOURCE), "reviewed_by": None, "reviewed_at": None}
    _write(tmp_path, [source], [deepcopy(REAL_PROVISION)])

    with pytest.raises(CorpusValidationError) as exc:
        load_corpus("real", corpus_dir=tmp_path)

    assert any("reviewed_by is missing" in e for e in exc.value.errors)
    assert any("reviewed_at is missing" in e for e in exc.value.errors)


def test_verified_source_without_official_url_is_rejected(tmp_path):
    source = {**deepcopy(REAL_SOURCE), "official_url": "  "}
    _write(tmp_path, [source], [deepcopy(REAL_PROVISION)])

    with pytest.raises(CorpusValidationError) as exc:
        load_corpus("real", corpus_dir=tmp_path)

    assert any("official_url is missing" in e for e in exc.value.errors)


def test_verified_source_without_document_hash_is_rejected(tmp_path):
    source = {**deepcopy(REAL_SOURCE), "document_sha256": None}
    _write(tmp_path, [source], [deepcopy(REAL_PROVISION)])

    with pytest.raises(CorpusValidationError) as exc:
        load_corpus("real", corpus_dir=tmp_path)

    assert any("document_sha256 is missing" in e for e in exc.value.errors)


def test_provision_under_verified_source_needs_its_own_provenance(tmp_path):
    provision = {**deepcopy(REAL_PROVISION), "reviewed_by": None}
    _write(tmp_path, [deepcopy(REAL_SOURCE)], [provision])

    with pytest.raises(CorpusValidationError) as exc:
        load_corpus("real", corpus_dir=tmp_path)

    assert any("REAL_ACT_S1" in e and "reviewed_by is missing" in e for e in exc.value.errors)


def test_unreviewed_condition_is_rejected(tmp_path):
    provision = deepcopy(REAL_PROVISION)
    provision["conditions"] = [
        {
            "condition_id": "C1",
            "description": "refund is pending",
            "fact_type": "refund_status",
            "operator": "equals",
            "expected_value": "pending",
            "human_review_status": "unreviewed",
        }
    ]
    _write(tmp_path, [deepcopy(REAL_SOURCE)], [provision])

    with pytest.raises(CorpusValidationError) as exc:
        load_corpus("real", corpus_dir=tmp_path)

    assert any("not human-reviewed" in e for e in exc.value.errors)


def test_fully_provenanced_real_corpus_loads(tmp_path):
    _write(tmp_path, [deepcopy(REAL_SOURCE)], [deepcopy(REAL_PROVISION)])

    corpus = load_corpus("real", corpus_dir=tmp_path)

    assert corpus.mode == "real"
    assert corpus.usable_count == 1
    assert real_corpus_problems(corpus) == []


def test_partial_real_corpus_is_allowed_when_verified_entries_are_complete(tmp_path):
    unverified = {
        **deepcopy(REAL_SOURCE),
        "source_id": "PENDING_ACT",
        "review_status": "unverified",
        "reviewed_by": None,
        "reviewed_at": None,
    }
    pending = {
        **deepcopy(REAL_PROVISION),
        "provision_id": "PENDING_ACT_S1",
        "source_id": "PENDING_ACT",
        "review_status": "unverified",
        "reviewed_by": None,
        "reviewed_at": None,
    }
    _write(
        tmp_path,
        [deepcopy(REAL_SOURCE), unverified],
        [deepcopy(REAL_PROVISION), pending],
    )

    corpus = load_corpus("real", corpus_dir=tmp_path)

    assert corpus.usable_count == 1
    assert corpus.unusable_count == 1
    assert real_corpus_problems(corpus) == []


def test_rejected_provision_must_not_be_in_runtime_corpus(tmp_path):
    provision = {**deepcopy(REAL_PROVISION), "review_status": "rejected"}
    _write(tmp_path, [deepcopy(REAL_SOURCE)], [provision])

    with pytest.raises(CorpusValidationError) as exc:
        load_corpus("real", corpus_dir=tmp_path)

    assert any("marked rejected" in e for e in exc.value.errors)


def test_unverified_provision_under_verified_source_is_allowed_as_background(tmp_path):
    background = {
        **deepcopy(REAL_PROVISION),
        "provision_id": "REAL_ACT_S2",
        "review_status": "unverified",
        "reviewed_by": None,
        "reviewed_at": None,
    }
    _write(tmp_path, [deepcopy(REAL_SOURCE)], [deepcopy(REAL_PROVISION), background])

    corpus = load_corpus("real", corpus_dir=tmp_path)

    assert corpus.usable_count == 1
    assert not corpus.is_usable("REAL_ACT_S2")
    assert real_corpus_problems(corpus) == []
