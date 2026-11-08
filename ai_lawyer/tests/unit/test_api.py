from __future__ import annotations

from fastapi.testclient import TestClient

from ai_lawyer.backend.main import create_app

B01 = (
    "I returned a pair of shoes I bought from FakeMart (order FM-1001) on 10 October 2026. "
    "FakeMart approved the return on 10 October and said the refund was initiated on 12 October. "
    "It is 8 November and I still have nothing in my account. "
    "I emailed their support on 25 October and they replied that it takes time. "
    "I have not contacted anyone else."
)
AS_OF = "2026-11-08"


def _client(orchestrator, settings):
    return TestClient(create_app(settings=settings, orchestrator=orchestrator))


def _conversation(client: TestClient, user: str = "demo-user") -> str:
    response = client.post("/conversations", headers={"X-User-Id": user})
    assert response.status_code == 200
    return response.json()["conversation_id"]


def test_health_lists_components_without_secrets(orchestrator, settings):
    with _client(orchestrator, settings) as client:
        response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["corpus"]["mode"] == "fixture"
    assert payload["corpus"]["provisions"] == 11
    assert payload["corpus"]["fixture_data_not_real_law"] is True
    assert payload["llm"]["provider"] == "fake"
    assert payload["llm"]["offline"] is True
    assert payload["index"]["loaded"] is True
    assert "api_key" not in response.text.lower()
    assert "llm_base_url" not in response.text.lower()


def test_message_returns_the_full_combined_payload(orchestrator, settings):
    with _client(orchestrator, settings) as client:
        conversation_id = _conversation(client)
        response = client.post(
            f"/conversations/{conversation_id}/messages",
            data={"message": B01, "as_of_date": AS_OF},
            headers={"X-User-Id": "demo-user", "X-Correlation-Id": "test-correlation-1"},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    for key in (
        "conversation_id",
        "message_id",
        "assistant_message_id",
        "case_id",
        "processing_status",
        "assistant_message",
        "extracted_facts",
        "evidence_processing",
        "legal_sources",
        "retrieval_summary",
        "verification",
        "assessment",
        "missing_information",
        "next_steps",
    ):
        assert key in payload
    assert payload["assessment"]["outcome"] == "formal_grievance_recommended"
    assert payload["legal_sources"]
    assert payload["document_draft"]["draft_type"] == "formal_grievance"
    assert response.headers["X-Correlation-Id"] == "test-correlation-1"


def test_unknown_conversation_is_a_safe_error(orchestrator, settings):
    with _client(orchestrator, settings) as client:
        response = client.post(
            "/conversations/conv_missing/messages",
            data={"message": B01},
            headers={"X-User-Id": "demo-user"},
        )
    assert response.status_code == 404
    payload = response.json()
    assert payload["error_code"] == "conversation_not_found"
    assert payload["retryable"] is False
    assert payload["correlation_id"]
    assert "Traceback" not in response.text


def test_case_endpoints_and_document_generation(orchestrator, settings):
    with _client(orchestrator, settings) as client:
        conversation_id = _conversation(client)
        message = client.post(
            f"/conversations/{conversation_id}/messages",
            data={"message": B01, "as_of_date": AS_OF},
            headers={"X-User-Id": "demo-user"},
        ).json()
        case_id = message["case_id"]

        listing = client.get("/cases", headers={"X-User-Id": "demo-user"})
        assert listing.status_code == 200
        assert listing.json()["count"] == 1

        detail = client.get(f"/cases/{case_id}", headers={"X-User-Id": "demo-user"})
        assert detail.status_code == 200
        assert detail.json()["case_id"] == case_id
        assert detail.json()["facts"]
        assert detail.json()["events"]

        document = client.post(
            f"/cases/{case_id}/documents",
            json={"draft_type": "support_request"},
            headers={"X-User-Id": "demo-user"},
        )
        assert document.status_code == 200, document.text
        assert document.json()["draft_type"] == "support_request"
        assert document.json()["content"].splitlines()[0].upper().startswith("# DRAFT")

        forbidden = client.get(f"/cases/{case_id}", headers={"X-User-Id": "someone-else"})
        assert forbidden.status_code == 404
        assert forbidden.json()["error_code"] == "case_not_found"


def test_upload_returns_document_supported_facts(orchestrator, settings):
    with _client(orchestrator, settings) as client:
        conversation_id = _conversation(client)
        response = client.post(
            f"/conversations/{conversation_id}/messages",
            data={"message": B01, "as_of_date": AS_OF},
            files={
                "files": (
                    "note.txt",
                    b"Refund initiated on 12 October 2026 for order FM-1001. Status: initiated.\n",
                    "text/plain",
                )
            },
            headers={"X-User-Id": "demo-user"},
        )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["evidence_processing"][0]["status"] == "completed"
    assert any(f["status"] == "document_supported" for f in payload["extracted_facts"])


def test_bad_input_is_rejected_with_safe_errors(orchestrator, settings):
    with _client(orchestrator, settings) as client:
        conversation_id = _conversation(client)
        bad_date = client.post(
            f"/conversations/{conversation_id}/messages",
            data={"message": B01, "as_of_date": "not-a-date"},
        )
        assert bad_date.status_code == 400
        assert bad_date.json()["error_code"] == "invalid_as_of_date"

        empty = client.post(
            f"/conversations/{conversation_id}/messages",
            data={"message": "   "},
        )
        assert empty.status_code == 400
        assert empty.json()["error_code"] == "empty_message"
