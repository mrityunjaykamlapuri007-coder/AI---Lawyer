from __future__ import annotations

import hashlib
import sqlite3

import pytest

from ai_lawyer.backend.db.repo import Database
from ai_lawyer.backend.services.case_manager import (
    persist_facts,
    resolve_case,
    update_resolution_status,
)
from ai_lawyer.backend.services.evidence_store import EvidenceStore
from ai_lawyer.backend.services.fact_extractor import (
    extract_fact_dicts,
    find_dates,
    mark_conflicts,
)
from ai_lawyer.contracts.errors import UserSafeError
from ai_lawyer.contracts.fakes import FakeLLM
from ai_lawyer.contracts.models import Fact
from ai_lawyer.legal_engine.applicability import active_facts


# ---------------------------------------------------------------------------
# database
# ---------------------------------------------------------------------------
def test_event_sequence_is_unique_and_gapless(db: Database, conversation):
    db.ensure_user("u1")
    case_id = db.create_case("u1", {"identifiers": ["A-1"]})
    assert db.append_event(case_id, "x", {}) == 2
    assert db.append_event(case_id, "y", {}) == 3
    events = db.get_events(case_id)
    assert [e["sequence_no"] for e in events] == [1, 2, 3]
    assert db.latest_event(case_id, "y")["payload"] == {}


def test_foreign_key_violation_is_enforced(db: Database):
    with pytest.raises(sqlite3.IntegrityError):
        db.add_message("conv_missing", "user", "hello")


def test_case_state_can_be_replayed_from_events(db: Database):
    db.ensure_user("u1")
    case_id = db.create_case("u1", {"identifiers": ["A-1"]})
    db.update_case(case_id, status="resolved")
    db.append_event(case_id, "case_resolved", {"reason": "test"})
    replayed = [e["event_type"] for e in db.get_events(case_id)]
    assert replayed == ["case_created", "case_resolved"]
    assert db.get_case(case_id).status == "resolved"


# ---------------------------------------------------------------------------
# fact extraction
# ---------------------------------------------------------------------------
B01 = (
    "I returned a pair of shoes I bought from FakeMart (order FM-1001) on 10 October 2026. "
    "FakeMart approved the return on 10 October and said the refund was initiated on 12 October. "
    "It is 8 November and I still have nothing in my account. "
    "I emailed their support on 25 October and they replied that it takes time. "
    "I have not contacted anyone else."
)


def test_deterministic_extraction_keeps_provenance_and_dates():
    facts = extract_fact_dicts(B01, source_type="user_message", source_id="user", default_year=2026)
    by_type: dict[str, list[dict]] = {}
    for item in facts:
        by_type.setdefault(item["fact_type"], []).append(item)

    assert by_type["order_id"][0]["raw_value"] == "FM-1001"
    assert by_type["merchant_name"][0]["normalised_value"] == "FakeMart"
    assert by_type["refund_status"][0]["normalised_value"] == "initiated"
    assert by_type["support_contact_made"][0]["normalised_value"] is True
    assert by_type["return_requested_date"][0]["normalised_value"] == "2026-10-10"
    assert by_type["return_approved_date"][0]["normalised_value"] == "2026-10-10"
    assert by_type["refund_initiated_date"][0]["normalised_value"] == "2026-10-12"
    assert by_type["support_contact_date"][0]["normalised_value"] == "2026-10-25"
    assert all(item["source_id"] == "user" for item in facts)


def test_hallucinated_llm_fact_is_dropped():
    llm = FakeLLM(
        scripts={
            "fact_extractor": [
                {
                    "facts": [
                        {
                            "fact_type": "order_id",
                            "raw_value": "ZZ-9999",
                            "normalised_value": "ZZ-9999",
                        }
                    ]
                }
            ]
        }
    )
    facts = extract_fact_dicts(
        "My order FM-1001 refund is pending.",
        source_type="user_message",
        llm=llm,
        default_year=2026,
    )
    values = {f["raw_value"] for f in facts}
    assert "FM-1001" in values
    assert "ZZ-9999" not in values


def test_yearless_date_inference_and_repeatable_contacts():
    hits = find_dates("I returned it on 30 October 2026 and support replied on 5 November.", 2026)
    assert [h.value.isoformat() for h in hits] == ["2026-10-30", "2026-11-05"]

    conflicting = mark_conflicts(
        [
            {"fact_type": "return_requested_date", "normalised_value": "2026-10-10", "raw_value": "10 Oct", "ambiguity_flag": False},
            {"fact_type": "return_requested_date", "normalised_value": "2026-10-20", "raw_value": "20 Oct", "ambiguity_flag": False},
            {"fact_type": "support_contact_date", "normalised_value": "2026-10-21", "raw_value": "21 Oct", "ambiguity_flag": False},
            {"fact_type": "support_contact_date", "normalised_value": "2026-10-25", "raw_value": "25 Oct", "ambiguity_flag": False},
        ]
    )
    assert all(f["ambiguity_flag"] for f in conflicting if f["fact_type"] == "return_requested_date")
    assert not any(f["ambiguity_flag"] for f in conflicting if f["fact_type"] == "support_contact_date")


def test_return_and_pickup_mismatch_is_flagged():
    facts = mark_conflicts(
        [
            {"fact_type": "return_requested_date", "normalised_value": "2026-10-10", "raw_value": "10 Oct", "ambiguity_flag": False},
            {"fact_type": "pickup_date", "normalised_value": "2026-10-12", "raw_value": "12 Oct", "ambiguity_flag": False},
        ]
    )
    assert all(f["ambiguity_flag"] for f in facts)


# ---------------------------------------------------------------------------
# case manager
# ---------------------------------------------------------------------------
def _order_fact(value: str = "FM-1001") -> dict:
    return {
        "fact_type": "order_id",
        "raw_value": value,
        "normalised_value": value,
        "source_type": "user_message",
        "source_id": "user",
        "status": "user_reported",
    }


def test_same_order_id_attaches_to_the_same_case(db, conversation, settings):
    first = resolve_case(
        db,
        user_id=settings.demo_user_id,
        conversation_id=conversation.conversation_id,
        facts=[_order_fact()],
        message="order FM-1001 refund pending",
    )
    persist_facts(db, first.case_id, [_order_fact()])
    second = resolve_case(
        db,
        user_id=settings.demo_user_id,
        conversation_id=conversation.conversation_id,
        facts=[_order_fact()],
        message="still waiting on FM-1001",
    )
    assert first.case_id == second.case_id
    assert second.is_new is False


def test_two_order_ids_ask_to_split(db, conversation, settings):
    result = resolve_case(
        db,
        user_id=settings.demo_user_id,
        conversation_id=conversation.conversation_id,
        facts=[_order_fact("FM-1001"), _order_fact("FM-2002")],
        message="two orders",
    )
    assert result.case_id is None
    assert result.split_required is True
    assert "two different order references" in result.clarification


def test_correction_supersedes_without_mutating_old_fact(db, conversation, settings):
    result = resolve_case(
        db,
        user_id=settings.demo_user_id,
        conversation_id=conversation.conversation_id,
        facts=[_order_fact()],
        message="order FM-1001",
    )
    first = persist_facts(
        db,
        result.case_id,
        [
            {
                "fact_type": "refund_status",
                "raw_value": "pending",
                "normalised_value": "pending",
                "status": "user_reported",
            }
        ],
    )[0]
    second = persist_facts(
        db,
        result.case_id,
        [
            {
                "fact_type": "refund_status",
                "raw_value": "received",
                "normalised_value": "received",
                "status": "user_reported",
            }
        ],
        correction=True,
    )[0]
    assert second.supersedes_fact_id == first.fact_id
    all_facts = db.get_facts(result.case_id)
    active = active_facts(all_facts)
    assert [f.normalised_value for f in active if f.fact_type == "refund_status"] == ["received"]
    assert db.get_facts(result.case_id)[0].normalised_value == "pending"


def test_resolved_case_reopens_on_new_message(db, conversation, settings):
    result = resolve_case(
        db,
        user_id=settings.demo_user_id,
        conversation_id=conversation.conversation_id,
        facts=[_order_fact()],
        message="order FM-1001",
    )
    persist_facts(db, result.case_id, [_order_fact()])
    db.update_case(result.case_id, status="resolved")
    reopened = resolve_case(
        db,
        user_id=settings.demo_user_id,
        conversation_id=conversation.conversation_id,
        facts=[_order_fact()],
        message="the money was reversed, FM-1001",
    )
    assert reopened.reopened is True
    assert db.get_case(result.case_id).status == "reopened"
    assert db.latest_event(result.case_id, "case_reopened") is not None


def test_latest_resolution_status_controls_resolved(db, conversation, settings):
    result = resolve_case(
        db,
        user_id=settings.demo_user_id,
        conversation_id=conversation.conversation_id,
        facts=[_order_fact()],
        message="order FM-1001",
    )
    received = persist_facts(
        db,
        result.case_id,
        [
            {"fact_type": "refund_status", "raw_value": "received", "normalised_value": "received", "status": "user_reported"},
            {"fact_type": "bank_credit_confirmed", "raw_value": "arrived", "normalised_value": True, "status": "user_reported"},
        ],
    )
    assert update_resolution_status(db, result.case_id, db.get_facts(result.case_id)) == "resolved"

    persist_facts(
        db,
        result.case_id,
        [{"fact_type": "refund_status", "raw_value": "reversed", "normalised_value": "reversed", "status": "user_reported"}],
        correction=True,
    )
    assert update_resolution_status(db, result.case_id, db.get_facts(result.case_id)) == "resolved"


# ---------------------------------------------------------------------------
# evidence store
# ---------------------------------------------------------------------------
def test_evidence_hash_round_trip_and_filename_traversal(settings):
    store = EvidenceStore(settings)
    data = b"Refund initiated 2 November 2026.\n"
    evidence = store.save("../../secret.txt", data)
    assert evidence.original_filename == "secret.txt"
    assert evidence.sha256 == hashlib.sha256(data).hexdigest()
    assert evidence.size_bytes == len(data)
    assert evidence.extraction_status == "completed"
    assert (store.root / evidence.storage_key).read_bytes() == data
    assert ".." not in evidence.storage_key


def test_evidence_rejects_signature_spoof_and_bad_type(settings):
    store = EvidenceStore(settings)
    with pytest.raises(UserSafeError) as exc:
        store.save("fake.pdf", b"not a pdf")
    assert exc.value.error_code == "signature_mismatch"
    with pytest.raises(UserSafeError) as exc2:
        store.save("image.png", b"\x89PNG")
    assert exc2.value.error_code == "unsupported_file_type"


def test_evidence_rejects_oversize_and_reports_corrupt_pdf(settings):
    store = EvidenceStore(settings)
    with pytest.raises(UserSafeError) as exc:
        store.save("big.txt", b"x" * (settings.max_upload_bytes + 1))
    assert exc.value.error_code == "file_too_large"

    corrupt = store.save("corrupt.pdf", b"%PDF-1.4 not really a pdf")
    assert corrupt.extraction_status == "failed"
    assert corrupt.error_code in {"pdf_corrupt", "pdf_no_pages"}
