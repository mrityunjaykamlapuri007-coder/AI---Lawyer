from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from ai_lawyer.backend.services import llm_providers
from ai_lawyer.backend.services.llm_providers import (
    OpenAICompatibleLLM,
    ensure_real_mode_has_real_llm,
    get_llm,
)
from ai_lawyer.config.settings import Settings
from ai_lawyer.contracts.errors import LLMUnavailable, ModelOutputInvalid, NotConfigured
from ai_lawyer.contracts.models import FactExtraction, RelevanceGradeBatch
from ai_lawyer.tools import llm_smoke


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "_env_file": None,
        "llm_provider": "openai_compatible",
        "llm_base_url": "https://tunnel.example.invalid/v1",
        "llm_model": "refund-llm",
        "llm_api_key": "test-key",
        "llm_call_log": str(tmp_path / "llm_calls.jsonl"),
        "llm_failure_log": str(tmp_path / "llm_failures.jsonl"),
    }
    values.update(overrides)
    return Settings(**values)


class _FakeResponse:
    def __init__(self, status: int, payload: dict | None = None) -> None:
        self.status_code = status
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://tunnel.example.invalid/v1/chat/completions")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("failed", request=request, response=response)

    def json(self) -> dict:
        return self._payload


def _install_client(monkeypatch, response_factory) -> dict:
    captured: dict = {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return response_factory(captured)

    monkeypatch.setattr(httpx, "Client", FakeClient)
    return captured


def test_llm_model_wins_over_legacy_model_id(tmp_path):
    settings = _settings(tmp_path, llm_model="refund-llm", llm_model_id="legacy")
    assert settings.llm_model_name == "refund-llm"


def test_legacy_model_id_still_works(tmp_path):
    settings = _settings(tmp_path, llm_model="", llm_model_id="legacy")
    assert settings.llm_model_name == "legacy"


def test_real_mode_with_fake_provider_is_refused(tmp_path):
    settings = _settings(
        tmp_path, corpus_mode="real", llm_provider="fake"
    )
    with pytest.raises(NotConfigured):
        ensure_real_mode_has_real_llm(settings)
    with pytest.raises(NotConfigured):
        get_llm(settings)


def test_missing_base_url_is_not_configured(tmp_path):
    settings = _settings(tmp_path, llm_base_url="")
    with pytest.raises(NotConfigured):
        OpenAICompatibleLLM(settings)


def test_json_schema_mode_uses_structured_response_format(tmp_path):
    settings = _settings(tmp_path, llm_json_schema_mode=True)
    llm = OpenAICompatibleLLM(settings)

    payload = llm._response_format(FactExtraction)

    assert payload is not None
    assert payload["type"] == "json_schema"
    assert payload["json_schema"]["name"] == "FactExtraction"


def test_json_object_mode_is_used_when_schema_mode_is_off(tmp_path):
    settings = _settings(tmp_path, llm_json_schema_mode=False)
    llm = OpenAICompatibleLLM(settings)

    assert llm._response_format(FactExtraction) == {"type": "json_object"}


def test_successful_call_logs_latency_and_tokens(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _install_client(
        monkeypatch,
        lambda captured: _FakeResponse(
            200,
            {
                "choices": [{"message": {"content": '{"facts": []}'}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            },
        ),
    )
    llm = OpenAICompatibleLLM(settings)

    result = llm.generate_structured("extract", FactExtraction, {"task": "fact_extraction"})

    assert result.facts == []
    log = [
        json.loads(line)
        for line in (tmp_path / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert log[-1]["ok"] is True
    assert log[-1]["prompt_tokens"] == 11
    assert log[-1]["completion_tokens"] == 7
    assert log[-1]["seconds"] >= 0
    assert log[-1]["step"] == "fact_extraction"


def test_bad_api_key_fails_immediately_with_a_clear_message(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    calls = {"n": 0}

    def factory(captured):
        calls["n"] += 1
        return _FakeResponse(401)

    _install_client(monkeypatch, factory)
    llm = OpenAICompatibleLLM(settings)

    with pytest.raises(LLMUnavailable) as exc:
        llm.generate_structured("x", FactExtraction)

    assert "LLM_API_KEY" in exc.value.user_safe_message
    assert exc.value.retryable is False
    assert calls["n"] == 1


def test_connection_failure_explains_the_tunnel(tmp_path, monkeypatch):
    settings = _settings(tmp_path, llm_max_retries_http=0)

    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "Client", FailingClient)
    llm = OpenAICompatibleLLM(settings)

    with pytest.raises(LLMUnavailable) as exc:
        llm.generate_structured("x", FactExtraction)

    assert "tunnel" in exc.value.user_safe_message.lower()
    assert "LLM_BASE_URL" in exc.value.user_safe_message


def test_schema_mismatch_logs_verbatim_output(tmp_path, monkeypatch):
    settings = _settings(tmp_path)
    _install_client(
        monkeypatch,
        lambda captured: _FakeResponse(
            200, {"choices": [{"message": {"content": "not json at all"}}]}
        ),
    )
    llm = OpenAICompatibleLLM(settings)

    with pytest.raises(ModelOutputInvalid):
        llm.generate_structured("x", RelevanceGradeBatch, {"task": "relevance_grading"})

    failures = [
        json.loads(line)
        for line in (tmp_path / "llm_failures.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert failures[-1]["raw_output"] == "not json at all"
    assert failures[-1]["step"] == "relevance_grading"


def test_smoke_refuses_fake_provider_by_default(tmp_path, capsys):
    settings = _settings(tmp_path, llm_provider="fake", llm_base_url="", llm_model="")

    code = llm_smoke.run(settings)

    assert code == 2
    assert "REFUSED" in capsys.readouterr().out


def test_smoke_runs_all_three_steps_against_fake_for_plumbing(tmp_path, capsys):
    settings = _settings(tmp_path, llm_provider="fake", llm_base_url="", llm_model="")

    code = llm_smoke.run(settings, allow_fake=True)

    output = capsys.readouterr().out
    assert code == 0
    assert "3/3 steps passed" in output
