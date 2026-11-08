"""Behaviour runner rules for real stories (undetermined, blocked startup)."""
from __future__ import annotations

from ai_lawyer.evaluation import run_behavior_eval as harness


def _response(outcome: str, message: str = "Send a written grievance.") -> dict:
    return {"assistant_message": message, "assessment": {"outcome": outcome}}


def test_undetermined_expectation_records_without_outcome_failure():
    case = {"test_id": "R10", "expected": {"outcome": "undetermined"}}
    failed, observed = harness._check_case(case, [_response("needs_more_information")], None, [], None)

    assert failed == []
    assert observed["outcome"] == "needs_more_information"


def test_determined_expectation_still_fails_on_mismatch():
    case = {"test_id": "R01", "expected": {"outcome": "formal_grievance_recommended"}}
    failed, _ = harness._check_case(case, [_response("needs_more_information")], None, [], None)

    assert failed and "formal_grievance_recommended" in failed[0]


def test_standard_forbidden_phrases_cover_violation_and_guarantee_language():
    for phrase in ("violated", "broke the law", "illegal", "you will win", "guaranteed"):
        assert phrase in harness.STANDARD_FORBIDDEN


def test_real_story_run_without_remote_services_is_blocked_cleanly(capsys, monkeypatch):
    from ai_lawyer.config.settings import get_settings

    # Offline even when a developer's .env points at live Kaggle services.
    monkeypatch.setenv("EMBEDDING_BACKEND", "hash")
    get_settings.cache_clear()
    code = harness.main(["--mode", "real", "--dataset", str(harness.EVAL_DIR / "dataset" / "real_stories.jsonl")])

    out = capsys.readouterr().out
    assert code == 2
    assert out.startswith("BLOCKED:")
    assert "check_remote" in out
