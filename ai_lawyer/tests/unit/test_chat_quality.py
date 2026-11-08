from __future__ import annotations

from ai_lawyer.backend.services.fact_extractor import extract_fact_dicts
from ai_lawyer.backend.services.response_generator import _second_person
from ai_lawyer.backend.services.scope_classifier import is_small_talk, is_vague


def _amounts(text):
    return [
        f["normalised_value"]
        for f in extract_fact_dicts(text, source_type="user_message", source_id="user", llm=None)
        if f["fact_type"] == "refund_amount"
    ]


def test_small_talk_detection():
    assert is_small_talk("hy I am Mrityunjay.")
    assert is_small_talk("thank you")
    assert not is_small_talk("ok it arrived")
    assert not is_small_talk("It arrived today.")
    assert not is_small_talk("My refund for order AB-12 is late")


def test_vague_detection():
    assert is_vague("I am having issues here in this")
    assert not is_vague("My refund for order AB-12 is late")


def test_paid_amount_used_only_when_no_refund_amount():
    assert _amounts("I cancelled an order on Flipkart and paid ₹2,499 by UPI.") == [249900]
    assert _amounts("I paid Rs 2,000 but got only Rs 500 refunded.") == [50000]


def test_second_person_rewrite():
    assert _second_person("The user made a purchase on Flipkart.") == "You made a purchase on Flipkart."
    assert _second_person("The user has reported that they have not received their refund.") == (
        "You have reported that you have not received your refund."
    )


def test_information_display_duty_is_capped_to_background():
    from ai_lawyer.contracts.models import RelevanceGrade
    from ai_lawyer.legal_engine.relevance_filter import _cap_disclosure_duty

    item = {"provision_id": "P", "original_text": "(5) Any seller shall provide the following information: return, refund"}
    grades = {"P": RelevanceGrade(provision_id="P", grade=3, reason="return, refund")}
    _cap_disclosure_duty(grades, item, "My refund has not come after I cancelled.")
    assert grades["P"].grade == 1
    grades = {"P": RelevanceGrade(provision_id="P", grade=3, reason="return, refund")}
    _cap_disclosure_duty(grades, item, "The site never showed any refund policy.")
    assert grades["P"].grade == 3
