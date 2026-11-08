"""Integration checks for the reference-stack parity stages.

The stages are opt-in, so these tests assert both directions: enabled stages
change behaviour, disabled stages leave the existing pipeline untouched.
"""
from __future__ import annotations

from types import SimpleNamespace

from ai_lawyer.config.settings import Settings
from ai_lawyer.contracts.models import Candidate
from ai_lawyer.legal_engine.reasoning import build_prompt
from ai_lawyer.legal_rag.query_planner import QueryPlan
from ai_lawyer.legal_rag.retriever import Retriever

LONG_PROVISION = (
    "The seller shall process every refund within thirty days of the return. "
    "The refund shall be made to the original payment method used by the consumer. "
    "Where the payment was made by cash, the refund may be made by bank transfer. "
    "The seller shall record the date on which the refund was initiated. "
    "The consumer may request an acknowledgement of the refund. "
    "Provided that the goods are unused and the packaging is intact, the consumer "
    "may return the goods within thirty days. "
    "This sub-rule does not apply to perishable goods."
)


class _StubCorpus:
    def get(self, provision_id: str):
        return SimpleNamespace(
            provision_id=provision_id,
            citation="Section 1",
            original_text=LONG_PROVISION,
            provisos=["Provided that the goods are unused."],
            exceptions=[],
            hierarchy_type="section",
        )


def _candidate(provision_id: str = "P1") -> Candidate:
    return Candidate(
        chunk_id=f"{provision_id}::c0",
        provision_id=provision_id,
        source_id="TEST_ACT",
        rrf_score=1.0,
        accepted=True,
    )


def _context() -> dict:
    return {"case_id": "case_1", "current_message": "refund timeline", "facts": {}}


# ---------------------------------------------------------------------------
# boost stage
# ---------------------------------------------------------------------------
def test_boost_ranks_the_article_the_user_named_first(corpus, index_bundle, settings: Settings):
    boosted = settings.model_copy(update={"boost_enabled": True})
    retriever = Retriever(index_bundle, corpus, boosted)

    plan = QueryPlan(
        original_query="TEST_ACT Article A3",
        self_contained_query="TEST_ACT Article A3",
    )
    result = retriever.search(plan, include_expansions=False)
    ids = [c.provision_id for c in result.candidates]

    assert "TEST_ACT_A3" in ids, "the named article must at least be retrieved"
    assert ids[0] == "TEST_ACT_A3", "the named article must rank first"


def test_boost_disabled_keeps_the_default_pipeline(corpus, index_bundle, settings: Settings):
    retriever = Retriever(index_bundle, corpus, settings)
    plan = QueryPlan(original_query="refund not received", self_contained_query="refund not received")
    result = retriever.search(plan, include_expansions=False)
    assert result.candidates, "default retrieval must still return candidates"
    assert result.candidates[0].rrf_score is not None


# ---------------------------------------------------------------------------
# compression stage
# ---------------------------------------------------------------------------
def test_compression_disabled_sends_the_full_provision(corpus, settings: Settings):
    prompt = build_prompt(_context(), [_candidate()], _StubCorpus(), settings=settings)
    assert LONG_PROVISION in prompt
    assert '"excerpt": false' in prompt


def test_compression_enabled_sends_a_verbatim_excerpt(corpus, settings: Settings):
    compressing = settings.model_copy(
        update={"compression_enabled": True, "compression_max_chars": 500}
    )
    prompt = build_prompt(_context(), [_candidate()], _StubCorpus(), settings=compressing)

    assert "Provided that the goods are unused" in prompt
    assert "This sub-rule does not apply to perishable goods." not in prompt
    assert '"excerpt": true' in prompt
    assert '"verbatim": true' in prompt


def test_compression_never_drops_a_qualifier_to_fit(corpus, settings: Settings):
    tiny = settings.model_copy(
        update={"compression_enabled": True, "compression_max_chars": 120}
    )
    prompt = build_prompt(_context(), [_candidate()], _StubCorpus(), settings=tiny)

    # A 120-character budget cannot hold the proviso, so nothing is trimmed.
    assert LONG_PROVISION in prompt
    assert '"excerpt": false' in prompt
