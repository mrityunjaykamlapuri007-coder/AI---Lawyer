from __future__ import annotations

from datetime import date, datetime

from ai_lawyer.backend.services.context_assembler import assemble_context
from ai_lawyer.tests.fakes import FakeLLM
from ai_lawyer.contracts.models import (
    ApplicationAnalysis,
    Assessment,
    Candidate,
    Condition,
    Fact,
    LegalDraft,
    Outcome,
    RelevanceGrade,
    RelevanceGradeBatch,
)
from ai_lawyer.legal_engine.acceptance import assign_roles
from ai_lawyer.legal_engine.applicability import evaluate_condition, evaluate_provision
from ai_lawyer.legal_engine.assessment import assess_case
from ai_lawyer.legal_engine.citation_validator import validate_draft
from ai_lawyer.legal_engine.date_guard import validate_dates
from ai_lawyer.legal_engine.decision_controller import apply_python_decision
from ai_lawyer.legal_engine.phrase_guard import sanitize_draft, sanitize_text
from ai_lawyer.legal_engine.reasoning import build_prompt
from ai_lawyer.legal_engine.relevance_filter import grade_candidates
from ai_lawyer.legal_engine.source_validity import evaluate_source_validity

AS_OF = date(2026, 11, 8)
_CREATED = datetime(2026, 1, 1)


def fact(fact_type: str, value, index: int = 0) -> Fact:
    return Fact(
        case_id="case_1",
        fact_type=fact_type,
        raw_value=str(value),
        normalised_value=value,
        source_type="user_message",
        source_id="user",
        status="user_reported",
        created_at=_CREATED.replace(day=1 + index),
    )


def candidate(pid: str) -> Candidate:
    source = "TEST_UNVERIFIED" if pid.startswith("TEST_UNVERIFIED") else "TEST_ACT"
    if pid.startswith("TEST_FUTURE"):
        source = "TEST_FUTURE"
    if pid.startswith("TEST_OLD"):
        source = "TEST_OLD"
    return Candidate(
        chunk_id=f"{pid}::c0",
        provision_id=pid,
        source_id=source,
        rrf_score=1.0,
        accepted=True,
    )


def condition(fact_type, operator, expected=None, reviewed=True, cid="C1") -> Condition:
    return Condition(
        condition_id=cid,
        description="test",
        fact_type=fact_type,
        operator=operator,
        expected_value=expected,
        human_review_status="reviewed" if reviewed else "unreviewed",
    )


# ---------------------------------------------------------------------------
# source validity
# ---------------------------------------------------------------------------
def test_source_validity_current_future_and_superseded(corpus):
    assert evaluate_source_validity(corpus.sources["TEST_ACT"], AS_OF)[0] == "current_for_date"
    assert evaluate_source_validity(corpus.sources["TEST_FUTURE"], AS_OF)[0] == "not_yet_effective"
    assert evaluate_source_validity(corpus.sources["TEST_OLD"], AS_OF)[0] == "superseded"


def test_source_validity_unknown_date_is_uncertain(corpus):
    assert evaluate_source_validity(corpus.sources["TEST_ACT"], None)[0] == "uncertain"


# ---------------------------------------------------------------------------
# applicability
# ---------------------------------------------------------------------------
def test_exists_is_unknown_when_fact_absent_and_false_on_explicit_negation():
    c = condition("support_contact_made", "exists")
    assert evaluate_condition(c, []).value is None
    assert evaluate_condition(c, [fact("support_contact_made", False)]).value is False
    assert evaluate_condition(c, [fact("support_contact_made", True)]).value is True


def test_equals_and_in_operators():
    assert evaluate_condition(condition("refund_status", "equals", "pending"), [fact("refund_status", "pending")]).value is True
    assert evaluate_condition(condition("refund_status", "equals", "pending"), [fact("refund_status", "denied")]).value is False
    conflict = [fact("refund_status", "pending", 1), fact("refund_status", "denied", 2)]
    assert evaluate_condition(condition("refund_status", "equals", "pending"), conflict).value is None
    in_c = condition("refund_status", "in", ["pending", "denied"])
    assert evaluate_condition(in_c, [fact("refund_status", "denied")]).value is True
    assert evaluate_condition(in_c, [fact("refund_status", "received")]).value is False


def test_date_operators_and_manual_and_unreviewed():
    before = condition("cancellation_date", "date_before", "2026-11-01")
    assert evaluate_condition(before, [fact("cancellation_date", "2026-10-30")]).value is True
    after = condition("cancellation_date", "date_after", "2026-11-01")
    assert evaluate_condition(after, [fact("cancellation_date", "2026-10-30")]).value is False
    assert evaluate_condition(condition("x", "manual"), [fact("x", 1)]).value is None
    assert evaluate_condition(condition("x", "exists", reviewed=False), [fact("x", 1)]).value is None


def test_provision_aggregation(corpus):
    assert evaluate_provision(corpus.provisions["TEST_ACT_A1_P1"], []).value is None
    meets = evaluate_provision(corpus.provisions["TEST_ACT_A1"], [fact("refund_status", "pending")])
    assert meets.value is True
    fails = evaluate_provision(corpus.provisions["TEST_ACT_A1"], [fact("refund_status", "received")])
    assert fails.value is False


# ---------------------------------------------------------------------------
# relevance filter
# ---------------------------------------------------------------------------
def test_relevance_filter_accepts_default_fake(corpus):
    cands = [candidate("TEST_ACT_A3")]
    grades = grade_candidates(
        "refund not received, grievance officer complaint", cands, corpus, FakeLLM()
    )
    assert grades["TEST_ACT_A3"].grade >= 2


def test_relevance_filter_falls_back_after_two_invalid_outputs(corpus):
    cands = [candidate("TEST_ACT_A3")]
    llm = FakeLLM(scripts={"relevance_grader": ["__INVALID_JSON__", "__INVALID_JSON__"]})
    grades = grade_candidates("refund pending", cands, corpus, llm)
    assert grades["TEST_ACT_A3"].grade == 0
    assert grades["TEST_ACT_A3"].reason == "grader_failed"
    assert len([c for c in llm.calls if c["task"] == "relevance_grader"]) == 2


def test_relevance_filter_rejects_reason_that_does_not_reference_text(corpus):
    cands = [candidate("TEST_ACT_A3")]
    llm = FakeLLM(
        scripts={
            "relevance_grader": [
                RelevanceGradeBatch(
                    grades=[
                        RelevanceGrade(
                            provision_id="TEST_ACT_A3",
                            grade=3,
                            reason="zzzz unrelated",
                        )
                    ]
                )
            ]
        }
    )
    grades = grade_candidates("refund pending", cands, corpus, llm)
    assert grades["TEST_ACT_A3"].grade == 0
    assert "did not reference" in grades["TEST_ACT_A3"].reason


# ---------------------------------------------------------------------------
# acceptance
# ---------------------------------------------------------------------------
def _grade(pid: str, score: int) -> RelevanceGrade:
    return RelevanceGrade(provision_id=pid, grade=score, reason="test reason")


def test_acceptance_roles(corpus):
    facts = [fact("refund_status", "not_received")]
    graded = assign_roles(
        [candidate("TEST_ACT_A1")],
        corpus,
        facts,
        AS_OF,
        {"TEST_ACT_A1": _grade("TEST_ACT_A1", 3)},
    )
    assert graded[0].accepted is True
    assert graded[0].role == "primary"
    assert graded[0].applicability == "applicable"
    assert graded[0].source_validity == "current_for_date"


def test_low_relevance_is_background_not_accepted(corpus):
    graded = assign_roles(
        [candidate("TEST_ACT_A1")],
        corpus,
        [fact("refund_status", "pending")],
        AS_OF,
        {"TEST_ACT_A1": _grade("TEST_ACT_A1", 1)},
    )
    assert graded[0].role == "background"
    assert graded[0].accepted is False


def test_conditions_false_and_unusable_sources_are_rejected(corpus):
    graded = assign_roles(
        [candidate("TEST_ACT_A1"), candidate("TEST_UNVERIFIED_A10"), candidate("TEST_FUTURE_A8")],
        corpus,
        [fact("refund_status", "received")],
        AS_OF,
        {
            "TEST_ACT_A1": _grade("TEST_ACT_A1", 3),
            "TEST_UNVERIFIED_A10": _grade("TEST_UNVERIFIED_A10", 3),
            "TEST_FUTURE_A8": _grade("TEST_FUTURE_A8", 3),
        },
    )
    by_id = {c.provision_id: c for c in graded}
    assert by_id["TEST_ACT_A1"].accepted is False
    assert "conditions not met" in by_id["TEST_ACT_A1"].rejection_reason
    assert by_id["TEST_UNVERIFIED_A10"].accepted is False
    assert "not human_verified" in by_id["TEST_UNVERIFIED_A10"].rejection_reason
    assert by_id["TEST_FUTURE_A8"].accepted is False
    assert "not current for date" in by_id["TEST_FUTURE_A8"].rejection_reason


def test_mandatory_proviso_is_kept_even_with_grade_zero(corpus):
    graded = assign_roles(
        [candidate("TEST_ACT_A1_P1")],
        corpus,
        [],
        AS_OF,
        {"TEST_ACT_A1_P1": _grade("TEST_ACT_A1_P1", 0)},
    )
    assert graded[0].accepted is True
    assert graded[0].role == "mandatory_qualifier"


# ---------------------------------------------------------------------------
# assessment rules
# ---------------------------------------------------------------------------
def test_r1_no_accepted_provision_abstains(corpus):
    result = assess_case(
        in_scope=True,
        accepted_candidates=[],
        corpus=corpus,
        facts=[fact("refund_status", "pending")],
        as_of_date=AS_OF,
        user_text="refund pending",
    )
    assert result.outcome == Outcome.needs_more_information
    assert result.rule_trace[0].startswith("R1")


def test_r4_within_promised_timeline_is_no_action(corpus):
    facts = [
        fact("refund_status", "initiated"),
        fact("cancellation_date", "2026-11-05"),
        fact("merchant_promised_timeline_days", 7),
        fact("support_contact_made", False),
    ]
    result = assess_case(
        in_scope=True,
        accepted_candidates=[candidate("TEST_ACT_A1")],
        corpus=corpus,
        facts=facts,
        as_of_date=AS_OF,
        user_text="today is 8 November, within 7 days",
    )
    assert result.outcome == Outcome.no_legal_action_currently_required
    assert result.rule_trace[0].startswith("R4")
    # A decided outcome must not contradict itself by asking follow-ups.
    assert result.missing_information == []


def test_r3_pending_without_support_is_informal(corpus):
    facts = [
        fact("refund_status", "pending"),
        fact("cancellation_date", "2026-10-01"),
        fact("support_contact_made", False),
    ]
    result = assess_case(
        in_scope=True,
        accepted_candidates=[candidate("TEST_ACT_A1")],
        corpus=corpus,
        facts=facts,
        as_of_date=AS_OF,
        user_text="refund pending",
    )
    assert result.outcome == Outcome.informal_resolution_recommended


def test_r5_support_contacted_is_formal_grievance(corpus):
    facts = [
        fact("refund_status", "initiated"),
        fact("cancellation_date", "2026-09-01"),
        fact("support_contact_made", True),
        fact("grievance_officer_contacted", False),
    ]
    result = assess_case(
        in_scope=True,
        accepted_candidates=[candidate("TEST_ACT_A1")],
        corpus=corpus,
        facts=facts,
        as_of_date=AS_OF,
        user_text="I emailed support",
    )
    assert result.outcome == Outcome.formal_grievance_recommended


def test_r6_grievance_plus_commission_route_is_formal_legal(corpus):
    facts = [
        fact("refund_status", "initiated"),
        fact("cancellation_date", "2026-09-01"),
        fact("support_contact_made", True),
        fact("grievance_officer_contacted", True),
    ]
    result = assess_case(
        in_scope=True,
        accepted_candidates=[candidate("TEST_ACT_A1"), candidate("TEST_ACT_A4")],
        corpus=corpus,
        facts=facts,
        as_of_date=AS_OF,
        user_text="I contacted the grievance officer",
    )
    assert result.outcome == Outcome.formal_legal_proceedings_may_be_justified
    assert "TEST_ACT_A4" in result.provision_ids_used


def test_court_or_fraud_language_sets_lawyer_flag(corpus):
    result = assess_case(
        in_scope=True,
        accepted_candidates=[candidate("TEST_ACT_A1")],
        corpus=corpus,
        facts=[
            fact("refund_status", "initiated"),
            fact("cancellation_date", "2026-09-01"),
            fact("support_contact_made", True),
        ],
        as_of_date=AS_OF,
        user_text="Should I go to court? The seller cheated me.",
    )
    assert result.lawyer_needed is True
    assert result.urgency == "high"


def test_conflict_and_missing_status_need_information(corpus):
    conflict = fact("cancellation_date", "2026-10-01")
    conflict.ambiguity_flag = True
    result = assess_case(
        in_scope=True,
        accepted_candidates=[candidate("TEST_ACT_A1")],
        corpus=corpus,
        facts=[fact("refund_status", "pending"), conflict],
        as_of_date=AS_OF,
        user_text="refund pending",
    )
    assert result.outcome == Outcome.needs_more_information
    assert result.rule_trace[0].startswith("R2-conflict")

    result2 = assess_case(
        in_scope=True,
        accepted_candidates=[candidate("TEST_ACT_A1")],
        corpus=corpus,
        facts=[fact("cancellation_date", "2026-10-01")],
        as_of_date=AS_OF,
        user_text="cancelled",
    )
    assert result2.outcome == Outcome.needs_more_information
    assert result2.rule_trace[0].startswith("R2")


def test_amount_alone_never_gives_formal_proceedings(corpus):
    result = assess_case(
        in_scope=True,
        accepted_candidates=[candidate("TEST_ACT_A1")],
        corpus=corpus,
        facts=[fact("refund_amount", 99900)],
        as_of_date=AS_OF,
        user_text="999 rupees refund",
    )
    assert result.outcome != Outcome.formal_legal_proceedings_may_be_justified


# ---------------------------------------------------------------------------
# guards
# ---------------------------------------------------------------------------
def test_phrase_guard_rewrites_forbidden_claims():
    draft = LegalDraft(
        issue_summary="The seller broke the law and you will win. Definitely.",
        application_analysis=[
            ApplicationAnalysis(
                provision_id="TEST_ACT_A1",
                conditional_statement="The seller violated the law and is guilty.",
            )
        ],
    )
    clean = sanitize_draft(draft)
    text = clean.draft.issue_summary.lower()
    assert "broke the law" not in text
    assert "you will win" not in text
    assert "definitely" not in text
    assert "violated" not in clean.draft.application_analysis[0].conditional_statement.lower()
    assert clean.rewrites


def test_sanitize_text_removes_guarantee_language():
    out = sanitize_text("The outcome is guaranteed and this is illegal.")
    assert "the outcome is guaranteed" not in out.lower()
    assert "not guaranteed" in out.lower()
    assert "illegal" not in out.lower()


def test_citation_guard_removes_invented_ids_and_sections(corpus):
    accepted = [candidate("TEST_ACT_A1")]
    accepted[0].accepted = True
    draft = LegalDraft(
        issue_summary="Section 999 applies to this refund.",
        relevant_provision_ids=["TEST_ACT_A1", "INVENTED_A99"],
        application_analysis=[
            ApplicationAnalysis(provision_id="TEST_ACT_A1", conditional_statement="May apply."),
            ApplicationAnalysis(provision_id="INVENTED_A99", conditional_statement="Invented."),
        ],
    )
    result = validate_draft(draft, accepted, corpus)
    assert result.draft.relevant_provision_ids == ["TEST_ACT_A1"]
    assert len(result.draft.application_analysis) == 1
    assert "Section 999" not in result.draft.issue_summary
    types = {b["type"] for b in result.blocked_claims}
    assert "unknown_provision_id" in types
    assert "citation_blocked" in types


def test_date_guard_removes_unbacked_days_and_dates():
    draft = LegalDraft(
        issue_summary="The refund took 30 days.",
        proposed_next_step="The refund was initiated on 10 October 2026.",
        uncertainties=["The deadline is soon."],
    )
    result = validate_dates(draft, {7}, {"10 October 2026"})
    assert "30 days" not in result.draft.issue_summary
    assert "10 October 2026" in result.draft.proposed_next_step
    assert [item for item in result.draft.uncertainties if item] == []
    assert result.blocked_claims


def test_decision_controller_python_wins():
    assessment = Assessment(outcome=Outcome.informal_resolution_recommended)
    draft = LegalDraft(proposed_outcome=Outcome.formal_grievance_recommended)
    result = apply_python_decision(assessment, draft)
    assert result.outcome == Outcome.informal_resolution_recommended
    assert result.llm_proposed_outcome == "formal_grievance_recommended"
    assert any("wins" in line for line in result.rule_trace)


# ---------------------------------------------------------------------------
# reasoning prompt
# ---------------------------------------------------------------------------
def test_reasoning_prompt_contains_only_accepted_provision_text(corpus):
    accepted = [candidate("TEST_ACT_A1")]
    accepted[0].accepted = True
    rejected = candidate("TEST_ACT_A2")
    rejected.accepted = False
    context = assemble_context(
        case_id="case_1",
        case_summary={},
        facts=[fact("refund_status", "pending")],
        message="refund pending",
        as_of_date=AS_OF,
        as_of_basis="test",
    )
    prompt = build_prompt(context, accepted + [rejected], corpus)
    assert corpus.provisions["TEST_ACT_A1"].original_text in prompt
    assert corpus.provisions["TEST_ACT_A2"].original_text not in prompt
    assert "<case_data>" in prompt and "<legal_provisions>" in prompt
