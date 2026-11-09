from __future__ import annotations

from datetime import date

import pytest

from ai_lawyer.backend.services.evidence_store import EvidenceStore
from ai_lawyer.backend.services.llm_providers import get_llm
from ai_lawyer.backend.services.orchestrator import Orchestrator, Upload
from ai_lawyer.config.settings import Settings
from ai_lawyer.contracts.errors import NotConfigured
from ai_lawyer.tests.fakes import FakeLLM
from ai_lawyer.contracts.models import Outcome, RetrievalRun
from ai_lawyer.legal_rag.retriever import RetrievalResult

B01 = (
    "I returned a pair of shoes I bought from FakeMart (order FM-1001) on 10 October 2026. "
    "FakeMart approved the return on 10 October and said the refund was initiated on 12 October. "
    "It is 8 November and I still have nothing in my account. "
    "I emailed their support on 25 October and they replied that it takes time. "
    "I have not contacted anyone else."
)
AS_OF = date(2026, 11, 8)


class EmptyRetriever:
    """Always returns nothing, to exercise bounded retries and abstention."""

    def __init__(self, corpus) -> None:
        self.corpus = corpus

    def search(self, plan, *, include_expansions=True, conversation_id=None, retry_index=0):
        variants = plan.variants(include_expansions=include_expansions)
        return RetrievalResult(
            candidates=[],
            run=RetrievalRun(
                conversation_id=conversation_id,
                query_variants=variants,
                corpus_version=self.corpus.corpus_version,
                index_version="empty-test",
                retry_index=retry_index,
            ),
        )


def _handle(orchestrator, conversation, settings, message, uploads=None, as_of=AS_OF):
    return orchestrator.handle_message(
        conversation_id=conversation.conversation_id,
        user_id=settings.demo_user_id,
        message=message,
        uploads=uploads,
        as_of_date=as_of,
    )


def test_pipeline_happy_path(orchestrator, conversation, settings):
    response = _handle(orchestrator, conversation, settings, B01)
    assert response.processing_status == "completed"
    assert response.case_id is not None
    assert response.assessment.outcome == Outcome.formal_grievance_recommended
    assert response.legal_sources
    assert all(source.provision_id.startswith("TEST_ACT") for source in response.legal_sources)
    assert response.retrieval_summary.accepted_count >= 1
    assert response.document_draft is not None
    assert response.document_draft.draft_type == "formal_grievance"
    assert "FIXTURE DATA, NOT REAL LAW" in response.assistant_message
    for forbidden in ("violated", "broke the law", "illegal", "you will win", "guaranteed"):
        assert forbidden not in response.assistant_message.lower()
    assert response.verification["overall"] in {"verified", "partially_verified"}


def test_pipeline_abstains_after_two_retries(db, corpus, settings, conversation):
    orchestrator = Orchestrator(
        db=db,
        corpus=corpus,
        retriever=EmptyRetriever(corpus),
        llm=FakeLLM(),
        settings=settings,
        evidence_store=EvidenceStore(settings),
    )
    response = _handle(orchestrator, conversation, settings, B01)
    assert response.assessment.outcome == Outcome.needs_more_information
    assert response.retrieval_summary.accepted_count == 0
    assert response.retrieval_summary.retry_count == 2
    assert response.verification["overall"] == "unverified"
    assert response.legal_sources == []


def test_pipeline_out_of_scope_refusal(orchestrator, conversation, settings):
    response = _handle(
        orchestrator,
        conversation,
        settings,
        "My landlord will not return my security deposit after I moved out of the flat.",
    )
    assert response.processing_status == "out_of_scope"
    assert response.assessment.outcome == Outcome.out_of_scope
    assert response.case_id is None
    assert "does not cover tenancy" in response.assistant_message
    assert response.legal_sources == []


def test_pipeline_missing_dates_asks_question(orchestrator, conversation, settings):
    response = _handle(
        orchestrator,
        conversation,
        settings,
        "The refund for order AB-1234 has not arrived. I paid 500 rupees by UPI.",
    )
    assert response.assessment.outcome == Outcome.needs_more_information
    assert response.processing_status == "needs_clarification"
    assert response.missing_information
    assert "## Missing information" in response.assistant_message


def test_pipeline_second_order_asks_split(orchestrator, conversation, settings):
    response = _handle(
        orchestrator,
        conversation,
        settings,
        "Both order FM-1001 and order FM-2002 have refunds pending.",
    )
    assert response.processing_status == "needs_clarification"
    assert response.case_id is None
    assert "one message per order" in response.assistant_message
    assert response.missing_information


def test_pipeline_partial_attachment_failure(orchestrator, conversation, settings):
    uploads = [
        Upload(
            filename="refund-note.txt",
            data=b"Refund initiated on 12 October 2026 for order FM-1001. Status: initiated.\n",
        ),
        Upload(filename="broken.pdf", data=b"%PDF this is not a real pdf"),
    ]
    response = _handle(orchestrator, conversation, settings, B01, uploads=uploads)
    statuses = {item.filename: item.status for item in response.evidence_processing}
    assert statuses["refund-note.txt"] == "completed"
    assert statuses["broken.pdf"] == "failed"
    assert response.processing_status == "partial"
    assert any(f.status == "document_supported" for f in response.extracted_facts)
    assert any(f.page_number for f in response.extracted_facts)


def test_pipeline_follow_up_without_keyword_stays_in_scope(orchestrator, conversation, settings):
    first = _handle(orchestrator, conversation, settings, B01)
    assert first.case_id
    follow_up = _handle(orchestrator, conversation, settings, "It arrived today.")
    assert follow_up.processing_status != "out_of_scope"
    assert follow_up.case_id == first.case_id


def test_case_resolves_then_reopens_same_case(orchestrator, conversation, settings):
    first = _handle(orchestrator, conversation, settings, B01)
    case_id = first.case_id
    resolved = _handle(
        orchestrator,
        conversation,
        settings,
        "The refund of 999 rupees arrived in my account today. Order FM-1001 is resolved.",
    )
    assert resolved.case_id == case_id
    state = orchestrator.db.get_case(case_id)
    assert state.status == "resolved"

    reopened = _handle(
        orchestrator,
        conversation,
        settings,
        "The refund for order FM-1001 was reversed. I still have nothing.",
    )
    assert reopened.case_id == case_id
    assert orchestrator.db.get_case(case_id).status == "reopened"
    assert orchestrator.db.latest_event(case_id, "case_reopened") is not None


def test_llm_provider_swap_via_config_only(tmp_path):
    fake = get_llm(Settings(llm_provider="fake", corpus_dir=str(tmp_path)))
    assert fake.provider == "fake"

    with pytest.raises(NotConfigured):
        get_llm(Settings(llm_provider="openai_compatible", llm_base_url="", llm_model_id=""))
    with pytest.raises(NotConfigured):
        get_llm(Settings(llm_provider="hf_local", llm_model_path="", llm_model_id=""))


def test_greeting_gets_instant_intake_reply_without_a_case(orchestrator, conversation, settings):
    response = _handle(orchestrator, conversation, settings, "hy I am Mrityunjay.")
    assert response.processing_status == "needs_clarification"
    assert response.case_id is None
    assert response.legal_sources == []
    assert "Hi Mrityunjay" in response.assistant_message
    assert response.missing_information


def test_vague_opener_is_asked_not_refused(orchestrator, conversation, settings):
    response = _handle(orchestrator, conversation, settings, "I am having issues here in this")
    assert response.processing_status != "out_of_scope"
    assert response.missing_information


def test_greeting_after_case_does_not_rerun_analysis(orchestrator, conversation, settings):
    first = _handle(orchestrator, conversation, settings, B01)
    greeting = _handle(orchestrator, conversation, settings, "hi there")
    assert greeting.case_id == first.case_id
    assert greeting.legal_sources == []
    assert "still have your refund case" in greeting.assistant_message


def test_answer_speaks_to_the_user_and_lists_each_fact_once(orchestrator, conversation, settings):
    response = _handle(orchestrator, conversation, settings, B01)
    text = response.assistant_message
    assert "the user" not in text.lower()
    assert "role:" not in text and "applicability:" not in text
    noted = next(line for line in text.splitlines() if line.startswith("Platform") or "Order:" in line)
    labels = [part.split(":")[0].strip() for part in noted.split(" · ")]
    assert len(labels) == len(set(labels))


def test_different_platform_in_same_chat_starts_a_new_case(orchestrator, conversation, settings):
    first = _handle(orchestrator, conversation, settings, "I ordered from Flipkart. The refund of 500 rupees for the cancelled order has not come.")
    second = orchestrator.handle_message(
        conversation_id=conversation.conversation_id,
        user_id=settings.demo_user_id,
        message="Separately, I ordered from Amazon. The refund of 900 rupees for the returned order has not come.",
        case_id_hint=first.case_id,
        as_of_date=AS_OF,
    )
    assert first.case_id and second.case_id and second.case_id != first.case_id


def _with_router(orchestrator, routes):
    orchestrator.llm.scripts["router"] = list(routes)
    return orchestrator


def test_router_off_topic_is_refused_with_its_own_words(orchestrator, conversation, settings):
    _with_router(orchestrator, [{"intent": "off_topic", "reply": "I can't help with choosing shoes to buy."}])
    response = _handle(orchestrator, conversation, settings, "I want to buy shoes from amazon")
    assert response.processing_status == "out_of_scope"
    assert response.assistant_message.startswith("I can't help with choosing shoes to buy.")
    assert "refund disputes" in response.assistant_message and "qualified lawyer" in response.assistant_message


def test_router_greeting_uses_model_reply(orchestrator, conversation, settings):
    _with_router(orchestrator, [{"intent": "greeting", "reply": "Hi Mrityunjay! What happened with your order?"}])
    response = _handle(orchestrator, conversation, settings, "Hy, I am Mrityunjay")
    assert response.assistant_message == "Hi Mrityunjay! What happened with your order?"
    assert response.legal_sources == []


def test_router_reply_with_legal_content_is_replaced(orchestrator, conversation, settings):
    _with_router(orchestrator, [{"intent": "greeting", "reply": "Under Rule 4 they must refund in 7 days."}])
    response = _handle(orchestrator, conversation, settings, "hello")
    assert "Rule 4" not in response.assistant_message and "7 days" not in response.assistant_message


def test_router_refund_case_runs_full_analysis(orchestrator, conversation, settings):
    _with_router(orchestrator, [{"intent": "refund_case", "reply": ""}])
    response = _handle(orchestrator, conversation, settings, B01)
    assert response.case_id and response.legal_sources


def test_unrelated_document_is_flagged_quickly(orchestrator, conversation, settings):
    uploads = [Upload(filename="note.txt", data=b"Happy holidays from the Sharma family. See you in Goa.\n")]
    response = _handle(orchestrator, conversation, settings, "Please read the attached document about my refund.", uploads=uploads)
    assert "does not look like an order or refund record" in response.assistant_message
    assert response.legal_sources == []
    assert response.missing_information


def test_useful_document_is_confirmed_with_what_was_found(orchestrator, conversation, settings):
    uploads = [Upload(filename="refund-note.txt", data=b"Refund initiated on 12 October 2026 for order FM-1001. Status: initiated.\n")]
    response = _handle(orchestrator, conversation, settings, B01, uploads=uploads)
    assert "refund-note.txt: read successfully. Found: order id FM-1001" in response.assistant_message


def test_spec_document_codes_are_not_orders(orchestrator, conversation, settings):
    text = b"Hashes use SHA-256 and dates use ISO-8601. Version 2.0, 8 November 2026. Refund disputes spec.\n"
    response = _handle(orchestrator, conversation, settings, "Please read the attached document about my refund.",
                       uploads=[Upload(filename="spec.txt", data=text)])
    assert "two different order references" not in response.assistant_message
    assert "spec.txt" in response.assistant_message


def test_model_document_check_rejects_unrelated_document(orchestrator, conversation, settings):
    orchestrator.llm.scripts["document_check"] = [{"is_refund_record": False, "what_it_is": "a software specification"}]
    text = b"Refund for order FM-1001 initiated on 12 October 2026. (example in a spec)\n"
    response = _handle(orchestrator, conversation, settings, "Please read the attached document about my refund.",
                       uploads=[Upload(filename="spec.txt", data=text)])
    assert "does not look like an order or refund record (it looks like a software specification)" in response.assistant_message
    assert not any(f.status == "document_supported" for f in response.extracted_facts)


def test_unusable_document_on_open_case_does_not_rerun_analysis(orchestrator, conversation, settings):
    first = _handle(orchestrator, conversation, settings, B01)
    orchestrator.llm.scripts["document_check"] = [{"is_refund_record": False, "what_it_is": "project notes"}]
    response = _handle(orchestrator, conversation, settings, "Please read the attached document about my refund.",
                       uploads=[Upload(filename="AGENTS.md", data=b"# Project instructions\nRead the spec first.\n")])
    assert response.case_id == first.case_id
    assert response.legal_sources == []
    assert "Nothing in your case has changed" in response.assistant_message


def test_fact_free_message_on_open_case_is_not_reanalysed(orchestrator, conversation, settings):
    first = _handle(orchestrator, conversation, settings, B01)
    orchestrator.llm.scripts["router"] = [{"intent": "follow_up", "reply": ""}]
    response = _handle(orchestrator, conversation, settings, "I will upload the documents")
    assert response.case_id == first.case_id
    assert response.legal_sources == []
    assert "Read my document" in response.assistant_message
