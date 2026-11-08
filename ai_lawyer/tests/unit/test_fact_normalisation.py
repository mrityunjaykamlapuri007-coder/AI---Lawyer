"""Run-1 defects (real model, R01): LLM fact values must map onto the fixed vocabulary."""
from __future__ import annotations

import json

from ai_lawyer.backend.services.fact_extractor import (
    _coerce_llm_fact,
    deterministic_facts,
    normalise_payment_method,
    normalise_refund_status,
)

TEXT = (
    "I paid using my Visa card online. Amazon told me the refund would be processed, but the app "
    "shows a total expected refund of ₹0.00 and nothing has been credited. Order FM-1001."
)


def _llm(fact_type, raw, normalised=None):
    return {"fact_type": fact_type, "raw_value": raw, "normalised_value": normalised}


def test_free_text_refund_status_is_mapped_to_the_vocabulary():
    fact = _coerce_llm_fact(_llm("refund_status", "nothing has been credited", "nothing has been credited"), TEXT)
    assert fact["normalised_value"] == "not_received"


def test_vocabulary_value_from_the_llm_is_kept():
    fact = _coerce_llm_fact(_llm("refund_status", "nothing has been credited", "not_received"), TEXT)
    assert fact["normalised_value"] == "not_received"


def test_unplaceable_refund_status_is_dropped():
    assert _coerce_llm_fact(_llm("refund_status", "Amazon told me", "unclear"), TEXT) is None


def test_id_without_digits_is_dropped_and_real_id_kept():
    assert _coerce_llm_fact(_llm("transaction_id", "Visa card online"), TEXT) is None
    assert _coerce_llm_fact(_llm("order_id", "FM-1001"), TEXT)["raw_value"] == "FM-1001"


def test_payment_method_is_normalised():
    assert _coerce_llm_fact(_llm("payment_method", "Visa card online", "Visa card online"), TEXT)["normalised_value"] == "card"
    assert normalise_payment_method("UPI") == "upi"
    assert normalise_payment_method("bank discount") is None


def test_negated_credit_is_not_read_as_received():
    assert normalise_refund_status("nothing has been credited", None) == "not_received"
    assert normalise_refund_status("the refund has not been credited yet", None) == "not_received"
    assert normalise_refund_status("the refund amount was credited", None) == "received"


def test_deterministic_extractor_no_longer_reads_negated_credit_as_received():
    facts = deterministic_facts("Refund of Rs 500 is still pending; nothing has been credited.",
                                source_type="user_message", source_id="user")
    statuses = [f["normalised_value"] for f in facts if f["fact_type"] == "refund_status"]
    assert "received" not in statuses


def test_llm_amount_string_is_parsed_to_minor_units():
    fact = _coerce_llm_fact(_llm("refund_amount", "₹0.00", "0.00"), TEXT)
    assert fact["normalised_value"] == 0 and isinstance(fact["normalised_value"], int)


def test_draft_money_never_crashes_on_a_bad_value():
    from ai_lawyer.documents.generator import PLACEHOLDER, _money

    assert _money("0.00") == PLACEHOLDER
    assert _money(None) == PLACEHOLDER
    assert _money(129999) == "INR 1,299.99"


def test_harness_records_a_crash_and_continues(monkeypatch, capsys, tmp_path):
    from ai_lawyer.evaluation import run_behavior_eval as harness

    # Never overwrite the committed fixture results from a test.
    monkeypatch.setattr(harness, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(harness, "RESULT_DIR", tmp_path / "results")
    calls = {"n": 0}
    original = harness._run_turns

    def flaky(orchestrator, conversation_id, settings, case, as_of):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TypeError("boom")
        return original(orchestrator, conversation_id, settings, case, as_of)

    monkeypatch.setattr(harness, "_run_turns", flaky)
    code = harness.main([])  # fixture mode, offline
    out = capsys.readouterr().out
    assert code in (0, 1)
    assert calls["n"] >= 17  # every case still ran
    assert "FIXTURE" in out
    first = json.loads(sorted((tmp_path / "raw").glob("*.json"))[0].read_text(encoding="utf-8"))
    assert first["result"] == "FAIL"
    assert first["checks_failed"][0].startswith("pipeline crashed: TypeError")
