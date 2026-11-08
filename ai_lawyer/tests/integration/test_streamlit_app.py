"""Headless Streamlit interaction tests using Streamlit's official AppTest.

These are not browser-automation tests.  They execute the real app script,
render its widgets, and submit a chat message through the same code path the
browser uses.  All HTTP calls are replaced with in-process fakes, so the test
is offline and deterministic.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import streamlit as st
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[2] / "frontend" / "app.py"


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "fake error", request=httpx.Request("GET", "http://test"), response=self
            )

    def json(self) -> dict:
        return self._payload


HEALTH = {
    "status": "ok",
    "corpus": {
        "mode": "fixture",
        "provisions": 11,
        "usable": 10,
        "fixture_data_not_real_law": True,
    },
    "llm": {"provider": "fake"},
}

ASSISTANT_RESPONSE = {
    "assistant_message": "## What this means\nThis is a fixture response.",
    "processing_status": "ok",
    "case_id": "case_test_1",
    "extracted_facts": [
        {
            "fact_type": "refund_status",
            "raw_value": "pending",
            "status": "user_reported",
            "inferred": False,
            "page_number": None,
            "ambiguity_flag": False,
        }
    ],
    "legal_sources": [
        {
            "citation": "TEST_ACT Article A1 (FIXTURE)",
            "role": "primary",
            "applicability": "applicable",
            "source_validity": "current_for_date",
            "excerpt": "FAKE TEST TEXT: refund within a reasonable period.",
        }
    ],
    "assessment": {
        "outcome": "informal_resolution_recommended",
        "reasons": ["A refund is outstanding."],
        "provision_ids_used": ["TEST_ACT_A1"],
    },
    "missing_information": [],
    "next_steps": ["Ask the seller for a refund date."],
    "verification": {"overall": "verified", "note": "Fixture guard."},
    "document_draft": {
        "draft_id": "draft_test_1",
        "draft_type": "support_request",
        "content": "Dear support,\n\nPlease refund order [TO BE FILLED BY USER].",
    },
}


def _prepare(monkeypatch) -> None:
    st.cache_data.clear()
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *args, **kwargs: FakeResponse(HEALTH),
    )

    def fake_post(url: str, *args, **kwargs):
        if url.endswith("/conversations"):
            return FakeResponse({"conversation_id": "conv_test_1"})
        return FakeResponse(ASSISTANT_RESPONSE)

    monkeypatch.setattr(httpx, "post", fake_post)


def test_app_shows_fixture_banner_and_renders_a_response(monkeypatch):
    _prepare(monkeypatch)
    at = AppTest.from_file(str(APP), default_timeout=30).run()

    assert not at.exception
    assert any("FIXTURE DATA, NOT REAL LAW" in item.value for item in at.error)

    at.chat_input[0].set_value(
        "I returned my shoes and the refund is still pending."
    ).run()

    assert not at.exception
    latest = at.session_state["latest"]
    assert latest["case_id"] == "case_test_1"
    assert latest["assessment"]["outcome"] == "informal_resolution_recommended"

    rendered = " ".join(item.value for item in at.markdown)
    assert "FIXTURE" in rendered or "fixture response" in rendered.lower()
    assert at.text_area[0].value.startswith("Dear support")
    assert "[TO BE FILLED BY USER]" in at.text_area[0].value
    assert not any("send" == button.label.lower() for button in at.button)


def test_app_shows_offline_state_without_crashing(monkeypatch):
    st.cache_data.clear()

    def offline_get(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(httpx, "get", offline_get)
    at = AppTest.from_file(str(APP), default_timeout=30).run()

    assert not at.exception
    titles = " ".join(item.value for item in at.title)
    assert "AI Consumer Refund Dispute Assistant" in titles
    warnings = " ".join(item.value for item in at.warning)
    assert "Backend status is unknown" in warnings
