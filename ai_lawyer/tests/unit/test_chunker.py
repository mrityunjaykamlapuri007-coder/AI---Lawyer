from __future__ import annotations

from ai_lawyer.contracts.models import Provision
from ai_lawyer.legal_rag.chunker import chunk_corpus, chunk_provision


def _provision(text: str, pid: str = "S1_A1") -> Provision:
    return Provision(
        provision_id=pid,
        source_id="S1",
        citation="Fixture Article A1",
        hierarchy_type="section",
        original_text=text,
        search_text="refund return",
        provisos=[],
        exceptions=[],
        definitions_used=[],
        cross_references=[],
        mandatory_context=[],
        conditions=[],
    )


def test_short_provision_is_one_chunk_with_stable_id():
    provision = _provision("FAKE TEST TEXT: a short refund rule.")
    chunks = chunk_provision(provision, max_chars=1800)
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "S1_A1::c0"
    assert chunks[0].provision_id == "S1_A1"
    assert chunks[0].original_text == provision.original_text


def test_chunk_ids_do_not_change_when_chunk_size_changes():
    provision = _provision("FAKE TEST TEXT: a short refund rule.")
    a = chunk_provision(provision, max_chars=1800)
    b = chunk_provision(provision, max_chars=120)
    assert [c.provision_id for c in a] == [c.provision_id for c in b]
    assert {c.chunk_id.split("::")[0] for c in a} == {c.chunk_id.split("::")[0] for c in b}


def test_long_provision_splits_at_clause_boundaries_and_keeps_parent_links():
    text = (
        "FAKE TEST TEXT: first clause.\n"
        "(a) second clause with refund wording.\n"
        "(b) third clause with return wording.\n"
        "Provided that a proviso applies."
    )
    provision = _provision(text)
    chunks = chunk_provision(provision, max_chars=45)
    assert len(chunks) > 1
    assert all(c.provision_id == "S1_A1" for c in chunks)
    assert all(c.original_text == text for c in chunks)
    assert "Fixture Article A1" in chunks[0].search_text
    assert [c.chunk_order for c in chunks] == list(range(len(chunks)))


def test_chunk_corpus_keeps_every_provision(corpus):
    chunks = chunk_corpus(corpus, max_chars=1800)
    assert {c.provision_id for c in chunks} == set(corpus.provisions)
    assert all(c.chunk_id == f"{c.provision_id}::c0" for c in chunks)
