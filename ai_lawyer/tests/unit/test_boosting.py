"""Unit tests for the legal-safe boost stage (reference "section boost" analogue).

Includes a regression test for the calibration bug found while building this:
an additive qualifier bonus larger than the RRF spread let one provision
hijack every query (hybrid MRR 0.82 -> 0.48).
"""
from __future__ import annotations

from types import SimpleNamespace

from ai_lawyer.config.settings import Settings
from ai_lawyer.legal_rag.boosting import (
    apply_boosts,
    boost_for,
    citation_references,
    query_references,
)
from ai_lawyer.legal_rag.rrf import FusedResult


def _settings(**overrides) -> Settings:
    base = Settings(boost_enabled=True, exact_reference_boost=0.5, qualifier_tiebreak=True)
    return base.model_copy(update=overrides)


class _Corpus:
    def __init__(self, provisions: dict[str, SimpleNamespace]) -> None:
        self._provisions = provisions

    def get(self, provision_id: str):
        return self._provisions.get(provision_id)


def _provision(citation: str, provisos=None, exceptions=None, hierarchy_type="section"):
    return SimpleNamespace(
        citation=citation,
        provisos=provisos or [],
        exceptions=exceptions or [],
        hierarchy_type=hierarchy_type,
    )


# ---------------------------------------------------------------------------
# reference parsing
# ---------------------------------------------------------------------------
def test_query_references_reads_section_numbers():
    assert query_references("What does Section 35(2) require?") == {"section:35"}


def test_query_references_reads_rules_and_articles():
    assert query_references("Under rule 12 and Article 21 of the Act") == {"rule:12", "article:21"}


def test_query_references_empty_when_no_reference():
    assert query_references("my refund has not arrived") == set()


def test_citation_references_matches_query_form():
    assert citation_references("Section 35") == {"section:35"}
    assert citation_references("Rule 12(1)") == {"rule:12"}


def test_lettered_article_is_supported():
    assert citation_references("Article A1") == {"article:A1"}


# ---------------------------------------------------------------------------
# boost values
# ---------------------------------------------------------------------------
def test_explicit_reference_gets_the_large_bonus():
    boost = boost_for(
        query_refs={"section:35"},
        citation="Section 35",
        provisos=None,
        exceptions=None,
        settings=_settings(),
    )
    assert boost.exact == 0.5
    assert any("explicit reference" in r for r in boost.reasons)


def test_unrelated_query_gets_no_boost():
    boost = boost_for(
        query_refs={"section:99"},
        citation="Section 35",
        provisos=None,
        exceptions=None,
        settings=_settings(),
    )
    assert boost.exact == 0.0
    assert boost.qualifier is False
    assert boost.reasons == ()


def test_qualifier_is_a_flag_not_a_score_bonus():
    boost = boost_for(
        query_refs=set(),
        citation="Section 35",
        provisos=["Provided that the goods are unused."],
        exceptions=[],
        settings=_settings(),
    )
    assert boost.qualifier is True
    assert boost.exact == 0.0


def test_boost_disabled_by_default():
    assert Settings().boost_enabled is False


# ---------------------------------------------------------------------------
# apply_boosts
# ---------------------------------------------------------------------------
def test_apply_boosts_puts_the_named_section_first():
    corpus = _Corpus({"P1": _provision("Section 35"), "P2": _provision("Section 12")})
    chunks = {
        "c1": {"provision_id": "P1", "citation": "Section 35"},
        "c2": {"provision_id": "P2", "citation": "Section 12"},
    }
    fused = [
        FusedResult(chunk_id="c2", score=0.030, ranks={"dense_0": 1}),
        FusedResult(chunk_id="c1", score=0.020, ranks={"dense_0": 2}),
    ]

    boosted = apply_boosts(
        fused,
        query="explain Section 35",
        chunk_lookup=chunks.get,
        corpus=corpus,
        settings=_settings(),
    )

    assert [r.chunk_id for r in boosted] == ["c1", "c2"]


def test_qualifier_never_outranks_a_better_rrf_score():
    """Regression: the qualifier flag must not act as an additive bonus."""
    corpus = _Corpus(
        {
            "P1": _provision("Section 35", provisos=["Provided that ..."]),
            "P2": _provision("Section 12"),
        }
    )
    chunks = {"c1": {"provision_id": "P1"}, "c2": {"provision_id": "P2"}}
    fused = [
        FusedResult(chunk_id="c1", score=0.010, ranks={}),
        FusedResult(chunk_id="c2", score=0.030, ranks={}),
    ]
    boosted = apply_boosts(
        fused,
        query="refund timeline",
        chunk_lookup=chunks.get,
        corpus=corpus,
        settings=_settings(),
    )
    assert [r.chunk_id for r in boosted] == ["c2", "c1"]


def test_qualifier_orders_exact_ties():
    corpus = _Corpus(
        {
            "P1": _provision("Section 35", provisos=["Provided that ..."]),
            "P2": _provision("Section 12"),
        }
    )
    chunks = {"a": {"provision_id": "P2"}, "b": {"provision_id": "P1"}}
    fused = [
        FusedResult(chunk_id="a", score=0.01, ranks={}),
        FusedResult(chunk_id="b", score=0.01, ranks={}),
    ]
    boosted = apply_boosts(
        fused,
        query="refund",
        chunk_lookup=chunks.get,
        corpus=corpus,
        settings=_settings(),
    )
    assert [r.chunk_id for r in boosted] == ["b", "a"]


def test_apply_boosts_is_deterministic_on_ties():
    corpus = _Corpus({"P1": _provision("Section 1"), "P2": _provision("Section 2")})
    chunks = {"b": {"provision_id": "P1"}, "a": {"provision_id": "P2"}}
    fused = [
        FusedResult(chunk_id="b", score=0.01, ranks={}),
        FusedResult(chunk_id="a", score=0.01, ranks={}),
    ]
    boosted = apply_boosts(
        fused,
        query="refund",
        chunk_lookup=chunks.get,
        corpus=corpus,
        settings=_settings(),
    )
    assert [r.chunk_id for r in boosted] == ["a", "b"]


def test_apply_boosts_survives_missing_metadata():
    fused = [FusedResult(chunk_id="ghost", score=0.01, ranks={})]
    boosted = apply_boosts(
        fused,
        query="Section 35",
        chunk_lookup=lambda _cid: None,
        corpus=_Corpus({}),
        settings=_settings(),
    )
    assert boosted[0].chunk_id == "ghost"
    assert boosted[0].score == 0.01
