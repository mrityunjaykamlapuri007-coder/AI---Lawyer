from __future__ import annotations

from copy import deepcopy

import pytest

from ai_lawyer.contracts.errors import CorpusValidationError
from ai_lawyer.legal_rag.corpus_loader import load_corpus, validate_and_build

SOURCE = {
    "source_id": "S1",
    "title": "Fixture source",
    "source_type": "act",
    "publisher": "Fixture",
    "official_url": "",
    "published_date": "2020-01-01",
    "retrieved_at": "2026-01-01",
    "document_sha256": None,
    "review_status": "human_verified",
    "version_label": "v1",
    "effective_from": "2020-01-01",
    "effective_to": None,
    "version_status": "current",
    "notes": "",
}

PROVISION = {
    "provision_id": "S1_A1",
    "source_id": "S1",
    "citation": "Fixture Article A1",
    "hierarchy_type": "section",
    "parent_provision_id": None,
    "original_text": "FAKE TEST TEXT: a refund must be processed.",
    "search_text": "refund",
    "provisos": [],
    "exceptions": [],
    "definitions_used": [],
    "cross_references": [],
    "mandatory_context": [],
    "conditions": [],
    "page_start": 1,
    "page_end": 1,
}


def _build(provisions=None, sources=None):
    return validate_and_build(sources or [deepcopy(SOURCE)], provisions or [deepcopy(PROVISION)])


def test_fixture_corpus_loads_with_expected_counts(corpus):
    assert corpus.mode == "fixture"
    assert len(corpus.sources) == 4
    assert len(corpus.provisions) == 11
    assert corpus.usable_count == 10
    assert corpus.unusable_count == 1
    assert not corpus.is_usable("TEST_UNVERIFIED_A10")
    assert corpus.is_usable("TEST_ACT_A1")
    assert any("unusable" in warning for warning in corpus.warnings)


def test_manifest_hash_is_stable_across_loads(corpus, settings):
    again = load_corpus(settings=settings)
    assert again.corpus_version == corpus.corpus_version
    assert again.manifest.corpus_version == corpus.manifest.corpus_version


def test_dangling_reference_is_rejected():
    bad = deepcopy(PROVISION)
    bad["parent_provision_id"] = "MISSING"
    with pytest.raises(CorpusValidationError) as exc:
        _build([bad])
    assert "dangling parent_provision_id" in str(exc.value.errors)


def test_duplicate_provision_id_is_rejected():
    with pytest.raises(CorpusValidationError) as exc:
        _build([deepcopy(PROVISION), deepcopy(PROVISION)])
    assert any("duplicate provision_id" in e for e in exc.value.errors)


def test_missing_original_text_is_rejected():
    bad = deepcopy(PROVISION)
    bad["original_text"] = "   "
    with pytest.raises(CorpusValidationError) as exc:
        _build([bad])
    assert any("provision[0] invalid" in e for e in exc.value.errors)


def test_unknown_condition_operator_is_rejected():
    bad = deepcopy(PROVISION)
    bad["conditions"] = [
        {
            "condition_id": "C1",
            "description": "bad",
            "fact_type": "refund_status",
            "operator": "contains",
            "expected_value": "pending",
            "human_review_status": "reviewed",
        }
    ]
    with pytest.raises(CorpusValidationError) as exc:
        _build([bad])
    assert any("provision[0] invalid" in e for e in exc.value.errors)


def test_unknown_source_id_is_rejected():
    bad = deepcopy(PROVISION)
    bad["source_id"] = "NOPE"
    with pytest.raises(CorpusValidationError) as exc:
        _build([bad])
    assert any("unknown source_id" in e for e in exc.value.errors)


def test_unverified_source_is_loaded_but_unusable():
    sources = [deepcopy(SOURCE), {**deepcopy(SOURCE), "source_id": "S2", "review_status": "unverified"}]
    bad = deepcopy(PROVISION)
    bad["provision_id"] = "S2_A2"
    bad["source_id"] = "S2"
    corpus = _build([deepcopy(PROVISION), bad], sources)
    assert corpus.usable_count == 1
    assert corpus.unusable_count == 1
    assert not corpus.is_usable("S2_A2")


def test_real_mode_without_sources_fails_clearly(tmp_path):
    with pytest.raises(CorpusValidationError) as exc:
        load_corpus("real", corpus_dir=tmp_path)
    assert "missing corpus file" in str(exc.value.errors[0])
