"""Decision controller: Python wins over the LLM's proposed outcome."""
from __future__ import annotations

import logging

from ai_lawyer.contracts.models import Assessment, LegalDraft

logger = logging.getLogger(__name__)


def apply_python_decision(assessment: Assessment, draft: LegalDraft | None) -> Assessment:
    proposed = draft.proposed_outcome.value if draft is not None else None
    assessment.llm_proposed_outcome = proposed
    if proposed and proposed != assessment.outcome.value:
        assessment.rule_trace.append(
            f"decision_controller: LLM proposed {proposed}; Python outcome {assessment.outcome.value} wins"
        )
        logger.info(
            "outcome mismatch: llm=%s python=%s", proposed, assessment.outcome.value
        )
    return assessment
