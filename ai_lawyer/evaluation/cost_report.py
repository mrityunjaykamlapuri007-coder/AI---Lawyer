"""Per-call and per-case cost and latency from the real LLM call log.

    python -m ai_lawyer.evaluation.cost_report [--since ISO_TIMESTAMP]

Reads ``evaluation/results/llm_calls.jsonl`` (written by the LLM provider on every
call) and writes ``results/cost_summary.json``.  Cost is reported in tokens and
seconds, not money: prices depend on the provider, so multiply by the provider's
own per-token price.  On Kaggle the marginal cost is zero (free GPU quota).
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

RESULTS = Path(__file__).resolve().parent / "results"
CALLS = RESULTS / "llm_calls.jsonl"
CASE_STEPS = ("scope_classifier", "fact_extractor", "relevance_grader", "reasoning")


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 2),
        "median": round(statistics.median(values), 2),
        "max": round(max(values), 2),
        "total": round(sum(values), 2),
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_step: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_step[row.get("step", "unknown")].append(row)
    steps = {
        step: {
            "calls": len(items),
            "ok": sum(1 for r in items if r.get("ok")),
            "seconds": _stats([float(r.get("seconds") or 0) for r in items]),
            "prompt_tokens": _stats([float(r.get("prompt_tokens") or 0) for r in items]),
            "completion_tokens": _stats([float(r.get("completion_tokens") or 0) for r in items]),
        }
        for step, items in sorted(by_step.items())
    }
    cases = max(1, len(by_step.get("scope_classifier", [])))
    total_prompt = sum(float(r.get("prompt_tokens") or 0) for r in rows)
    total_completion = sum(float(r.get("completion_tokens") or 0) for r in rows)
    total_seconds = sum(float(r.get("seconds") or 0) for r in rows)
    return {
        "calls": len(rows),
        "ok_calls": sum(1 for r in rows if r.get("ok")),
        "cases_estimated_from_scope_calls": cases,
        "per_case": {
            "llm_calls": round(len(rows) / cases, 2),
            "prompt_tokens": round(total_prompt / cases),
            "completion_tokens": round(total_completion / cases),
            "llm_seconds": round(total_seconds / cases, 1),
        },
        "steps": steps,
        "models": sorted({str(r.get("model")) for r in rows}),
        "note": "Tokens and seconds measured on Kaggle 2x T4 (fp16, vLLM). Money cost = tokens x the "
                "provider's own price; not estimated here. Embedding calls are not in this log.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ai_lawyer.evaluation.cost_report")
    parser.add_argument("--since", default="", help="only calls logged at or after this ISO time")
    args = parser.parse_args(argv)
    rows = [json.loads(l) for l in CALLS.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.since:
        rows = [r for r in rows if str(r.get("logged_at", "")) >= args.since]
    summary = {"since": args.since or "all", **summarise(rows)}
    (RESULTS / "cost_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("since", "calls", "ok_calls", "per_case", "models")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
