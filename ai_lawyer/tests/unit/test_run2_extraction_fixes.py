"""Run-2 extraction defects, fixed as general rules (built from development cases only)."""
from __future__ import annotations

from ai_lawyer.backend.services.fact_extractor import (
    _coerce_llm_fact,
    _contact_flags,
    deterministic_facts,
    find_dates,
    normalise_refund_status,
)


def _facts(text):
    return deterministic_facts(text, source_type="user_message", source_id="user")


def _dates(facts):
    return {(f["fact_type"], f["normalised_value"]) for f in facts if f["fact_type"].endswith("_date")}


def test_yearless_date_is_never_completed_with_the_current_year():
    from ai_lawyer.backend.services.fact_extractor import explicit_year

    text = "They promised the money by August 16th."
    # The orchestrator passes only a year the user stated; here there is none.
    assert explicit_year(text) is None
    assert find_dates(text, default_year=explicit_year(text)) == []


def test_year_stated_in_an_attachment_can_complete_a_message_date():
    from ai_lawyer.backend.services.fact_extractor import explicit_year

    year = explicit_year("I called customer care on 30 October.", "Refund processed on 20-10-2026.")
    assert year == 2026
    assert [h.value.isoformat() for h in find_dates("I called on 30 October.", default_year=year)] == ["2026-10-30"]


def test_yearless_date_uses_an_explicit_year_from_the_same_text():
    hits = find_dates("I ordered on 3 August 2025. They promised the money by August 16th.")
    assert [h.value.isoformat() for h in hits] == ["2025-08-03", "2025-08-16"]


def test_second_date_in_a_sentence_takes_the_event_word_next_to_it():  # development case R03
    text = ("We cancelled the whole order through Amazon on 29th November 2021 and returned the one "
            "item, as Amazon instructed, on 8th December 2021.")
    dates = _dates(_facts(text))
    assert ("cancellation_date", "2021-11-29") in dates
    assert ("return_requested_date", "2021-12-08") in dates
    assert ("cancellation_date", "2021-12-08") not in dates


def test_llm_date_without_an_event_word_is_dropped():  # development case R09
    text = "I ordered a laptop backpack on the Flipkart app. When the parcel arrived on July 4, 2022 it was empty."
    item = {"fact_type": "purchase_date", "raw_value": "July 4, 2022", "normalised_value": "2022-07-04"}
    assert _coerce_llm_fact(item, text) is None


def test_llm_date_role_is_corrected_from_the_text():  # development case R03
    text = ("We cancelled the whole order on 29th November 2021 and returned the one item on 8th December 2021.")
    item = {"fact_type": "cancellation_date", "raw_value": "8th December 2021", "normalised_value": "2021-12-08"}
    assert _coerce_llm_fact(item, text)["fact_type"] == "return_requested_date"


def test_placed_an_order_is_a_purchase_date():
    assert ("purchase_date", "2024-09-26") in _dates(_facts("I placed a prepaid order on September 26, 2024."))


def test_refund_that_reached_the_account_is_received():  # development case R02
    raw = "refunded ₹59,730, which reached my account the same day"
    assert normalise_refund_status(raw, "processed") == "received"
    assert normalise_refund_status("the money has not reached my account", None) == "not_received"


def test_more_ways_of_contacting_the_platform_count_as_support_contact():
    for sentence in (
        "We sent notices to the platform and to the seller.",            # R03 (development)
        "I reported it in the Flipkart app straight away.",              # R09 (development)
        "I kept calling customer care about it.",
        "I tried many times through chats and calls.",
        "I raised a complaint with the marketplace.",
    ):
        flag = _contact_flags(sentence).get("support_contact_made")
        assert flag is not None and flag["normalised_value"] is True, sentence


def test_not_contacting_is_still_recognised():
    flag = _contact_flags("I have not contacted them yet.")["support_contact_made"]
    assert flag["normalised_value"] is False


# --- run-3 regressions (the run-2 date rule was too strict) -------------------
def test_event_word_after_the_date_gives_its_role():
    text = "On 14 March 2024 I bought hair gummies for 799 rupees."
    item = {"fact_type": "purchase_date", "raw_value": "14 March 2024", "normalised_value": "2024-03-14"}
    assert _coerce_llm_fact(item, text)["fact_type"] == "purchase_date"
    assert ("purchase_date", "2024-03-14") in _dates(_facts(text))


def test_collected_is_a_pickup_word():
    text = "The product was collected on 24/07/2023 with assurances of a refund."
    assert ("pickup_date", "2023-07-24") in _dates(_facts(text))


def test_llm_role_is_kept_when_the_text_names_no_event():
    text = "My case reference date is 10 January 2025 and nothing has been paid."
    item = {"fact_type": "refund_initiated_date", "raw_value": "10 January 2025", "normalised_value": "2025-01-10"}
    assert _coerce_llm_fact(item, text)["fact_type"] == "refund_initiated_date"


def test_draft_output_cap_leaves_room_for_long_answers():
    from ai_lawyer.config.settings import Settings

    assert Settings().llm_max_tokens >= 3000
