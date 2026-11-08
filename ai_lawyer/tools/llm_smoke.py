"""Smoke test the configured language model on the three structured steps.

Run against the real endpoint::

    python -m ai_lawyer.tools.llm_smoke

It sends one tiny prompt per step, validates the reply against the same
pydantic schema the application uses, and prints PASS/FAIL with the raw output.
Every failure is appended verbatim to ``evaluation/results/llm_failures.jsonl``
and every call (latency, tokens) to ``evaluation/results/llm_calls.jsonl``.

``--allow-fake`` exists only so the plumbing can be exercised offline with
``FakeLLM``; it is not evidence about a real model.  With
``CORPUS_MODE=real`` the fake provider is refused outright.

This module never prints the API key or the base URL's query string.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from ai_lawyer.backend.services.llm_providers import (
    get_llm,
    log_llm_failure,
)
from ai_lawyer.config.settings import Settings, get_settings
from ai_lawyer.contracts.errors import UserSafeError
from ai_lawyer.contracts.models import FactExtraction, LegalDraft, RelevanceGradeBatch

FACT_PROMPT = """Extract facts from this consumer message. Return JSON with a single
"facts" list. Each item may contain fact_type, raw_value and confidence.
Message: "I cancelled my order on 2026-10-02 and the seller still has not refunded me."
"""

GRADE_PROMPT = """Grade how relevant provision X is to the consumer message.
Return JSON with a "grades" list; each item has provision_id, grade (0-3) and reason.
Message: "My refund has not arrived after a return."
Provision X: "A seller must process a refund after cancellation or return."
"""

DRAFT_PROMPT = """Draft a cautious JSON response for a consumer whose refund is
unresolved. Use only the supplied inert test text. Return the LegalDraft fields
issue_summary and proposed_outcome; proposed_outcome must be one of the allowed
enum values and, with this little information, should be needs_more_information.
No legal citations.
"""


@dataclass
class Step:
    name: str
    schema: type[BaseModel]
    prompt: str


STEPS = [
    Step("fact_extraction", FactExtraction, FACT_PROMPT),
    Step("relevance_grading", RelevanceGradeBatch, GRADE_PROMPT),
    Step("answer_drafting", LegalDraft, DRAFT_PROMPT),
]


def _masked_base_url(settings: Settings) -> str:
    url = settings.llm_base_url or ""
    return url.split("?")[0]


def run(settings: Settings, *, allow_fake: bool = False) -> int:
    if settings.llm_provider == "fake" and not allow_fake:
        print(
            "REFUSED: LLM_PROVIDER=fake. This smoke test must run against a real "
            "model. Use --allow-fake only to test the local plumbing."
        )
        return 2
    if settings.corpus_mode == "real" and settings.llm_provider == "fake":
        print("REFUSED: CORPUS_MODE=real with LLM_PROVIDER=fake.")
        return 2

    print(f"provider : {settings.llm_provider}")
    print(f"model    : {settings.llm_model_name or '(none)'}")
    print(f"base url : {_masked_base_url(settings) or '(none)'}")
    print(f"schema   : {settings.llm_json_schema_mode}")
    print(f"timeout  : {settings.llm_timeout_s}s, http retries: {settings.llm_max_retries_http}")

    try:
        llm = get_llm(settings)
    except UserSafeError as exc:
        print(f"REFUSED: {exc.user_safe_message}")
        return 2

    failures = 0
    for step in STEPS:
        print(f"\n--- {step.name} ---")
        try:
            result = llm.generate_structured(step.prompt, step.schema, {"task": step.name})
        except Exception as exc:  # noqa: BLE001 - print the real failure
            failures += 1
            detail = getattr(exc, "user_safe_message", str(exc))
            print(f"FAIL {step.name}: {type(exc).__name__}: {detail}")
            log_llm_failure(
                settings,
                {
                    "step": step.name,
                    "model": settings.llm_model_name,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "detail": detail,
                },
            )
            continue
        raw = result.model_dump_json(indent=2)
        print(f"PASS {step.name}")
        print(raw)

    print(f"\n{len(STEPS) - failures}/{len(STEPS)} steps passed")
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ai_lawyer.tools.llm_smoke",
        description="One tiny structured call per LLM step.",
    )
    parser.add_argument(
        "--allow-fake",
        action="store_true",
        help="exercise the plumbing with FakeLLM (never evidence about a real model)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print a JSON summary line at the end",
    )
    args = parser.parse_args(argv)
    code = run(get_settings(), allow_fake=args.allow_fake)
    if args.json:
        print(json.dumps({"exit_code": code}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
