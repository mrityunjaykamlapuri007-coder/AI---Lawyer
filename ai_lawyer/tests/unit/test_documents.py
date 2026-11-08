from __future__ import annotations

from datetime import datetime

import pytest

from ai_lawyer.contracts.errors import UserSafeError
from ai_lawyer.contracts.models import Candidate, Fact
from ai_lawyer.documents.generator import PLACEHOLDER, generate_document
from ai_lawyer.documents.validator import validate_draft_content


def fact(fact_type: str, raw: str, value=None) -> Fact:
    return Fact(
        case_id="case_1",
        fact_type=fact_type,
        raw_value=raw,
        normalised_value=value,
        source_type="user_message",
        source_id="user",
        status="user_reported",
        created_at=datetime(2026, 1, 1),
    )


@pytest.fixture()
def case_facts() -> list[Fact]:
    return [
        fact("merchant_name", "FakeMart", "FakeMart"),
        fact("order_id", "FM-1001", "FM-1001"),
        fact("refund_amount", "899.00", 89900),
        fact("refund_status", "initiated", "initiated"),
        fact("return_approved_date", "10 October 2026", "2026-10-10"),
        fact("refund_initiated_date", "12 October 2026", "2026-10-12"),
        fact("support_contact_made", "emailed support", True),
    ]


@pytest.fixture()
def accepted() -> list[Candidate]:
    return [
        Candidate(
            chunk_id="TEST_ACT_A1::c0",
            provision_id="TEST_ACT_A1",
            source_id="TEST_ACT",
            rrf_score=1.0,
            accepted=True,
            role="primary",
            applicability="applicable",
            source_validity="current_for_date",
        )
    ]


def test_support_request_uses_facts_and_placeholders(case_facts, accepted, corpus):
    draft = generate_document(
        draft_type="support_request",
        case_id="case_1",
        facts=case_facts,
        accepted=accepted,
        corpus=corpus,
    )
    content = draft.content
    assert content.splitlines()[0].upper().startswith("# DRAFT")
    assert "FM-1001" in content
    assert "INR 899.00" in content
    assert "not sent or filed" in content.lower()
    assert PLACEHOLDER in content
    assert draft.status == "needs_review"
    assert draft.missing_fields == [PLACEHOLDER]


def test_formal_grievance_lists_only_accepted_citation(case_facts, accepted, corpus):
    draft = generate_document(
        draft_type="formal_grievance",
        case_id="case_1",
        facts=case_facts,
        accepted=accepted,
        corpus=corpus,
    )
    assert "TEST_ACT Article A1 (FIXTURE)" in draft.content
    assert "FAKE TEST TEXT" in draft.content
    assert "TEST_ACT Article A2" not in draft.content


def test_unsupported_draft_type_is_blocked(case_facts, accepted, corpus):
    with pytest.raises(UserSafeError) as exc:
        generate_document(
            draft_type="consumer_commission_draft",
            case_id="case_1",
            facts=case_facts,
            accepted=accepted,
            corpus=corpus,
        )
    assert exc.value.error_code == "document_type_not_supported"


def test_validator_blocks_unbacked_amount_date_order_and_citation(case_facts, accepted, corpus):
    content = (
        "# DRAFT: prepared for your review. Not sent or filed.\n\n"
        "Order FM-9999 for INR 1,000.00 on 1 January 2025.\n"
        "- Merchant: NotInFacts\n"
        "- TEST_ACT Article A99 (FIXTURE): \"invented\"\n"
    )
    issues = validate_draft_content(
        content,
        facts=case_facts,
        accepted=accepted,
        corpus=corpus,
        draft_type="formal_grievance",
    )
    joined = "\n".join(issues)
    assert "order/transaction id not in fact store: FM-9999" in joined
    assert "amount not in fact store" in joined
    assert "date not in fact store" in joined
    assert "legal citation is not an accepted provision" in joined


def test_validator_requires_draft_header_and_not_sent_notice(case_facts, accepted, corpus):
    issues = validate_draft_content(
        "Hello",
        facts=case_facts,
        accepted=accepted,
        corpus=corpus,
        draft_type="support_request",
    )
    assert any("DRAFT" in issue for issue in issues)
    assert any("not sent" in issue for issue in issues)
