from ai_lawyer.evaluation.cost_report import summarise


def test_per_case_figures_are_computed_from_the_log():
    rows = [
        {"step": "scope_classifier", "ok": True, "seconds": 2.0, "prompt_tokens": 300, "completion_tokens": 40, "model": "m"},
        {"step": "reasoning", "ok": True, "seconds": 8.0, "prompt_tokens": 2000, "completion_tokens": 600, "model": "m"},
        {"step": "scope_classifier", "ok": True, "seconds": 2.0, "prompt_tokens": 300, "completion_tokens": 40, "model": "m"},
        {"step": "reasoning", "ok": False, "seconds": 4.0, "prompt_tokens": 1000, "completion_tokens": 0, "model": "m"},
    ]
    s = summarise(rows)
    assert s["cases_estimated_from_scope_calls"] == 2
    assert s["per_case"] == {"llm_calls": 2.0, "prompt_tokens": 1800, "completion_tokens": 340, "llm_seconds": 8.0}
    assert s["steps"]["reasoning"]["ok"] == 1
