"""Bounded retrieval/verification retry loop (v3 Section 6 step 10).

Retry 1: self-contained query with more facts, expansions dropped.
Retry 2: broader but issue-bounded.
No attempt repeats an identical query string.  Still nothing => abstain.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from ai_lawyer.config.settings import Settings, get_settings
from ai_lawyer.contracts.models import Candidate, Fact, RetrievalRun
from ai_lawyer.legal_engine import relevance_filter
from ai_lawyer.legal_engine.acceptance import assign_roles
from ai_lawyer.legal_rag.corpus_loader import Corpus
from ai_lawyer.legal_rag.provision_expander import expand
from ai_lawyer.legal_rag.query_planner import QueryPlan
from ai_lawyer.legal_rag.retriever import Retriever

logger = logging.getLogger(__name__)


@dataclass
class AttemptRecord:
    attempt: int
    queries: list[str]
    candidate_count: int
    accepted_count: int
    reason: str


@dataclass
class VerificationOutcome:
    candidates: list[Candidate] = field(default_factory=list)
    accepted: list[Candidate] = field(default_factory=list)
    attempts: list[AttemptRecord] = field(default_factory=list)
    runs: list[RetrievalRun] = field(default_factory=list)
    retry_count: int = 0
    abstained: bool = False
    queries_seen: list[str] = field(default_factory=list)

    @property
    def rejected_count(self) -> int:
        return sum(1 for c in self.candidates if not c.accepted)


def rewrite_plan(plan: QueryPlan, attempt: int, used: set[str]) -> QueryPlan:
    if attempt == 1:
        base = plan.self_contained_query.strip()
        suffix = "exact dates, refund status, payment method, support contact"
        candidates = [f"{base}; {suffix}" if base else f"e-commerce refund dispute; {suffix}"]
        expansions: list[str] = []
    else:
        candidates = [
            "e-commerce consumer refund return cancellation delayed denied pending "
            "grievance complaint India"
        ]
        expansions = []
    unique: list[str] = []
    for q in candidates:
        if q not in used:
            unique.append(q)
    if not unique:
        unique = [f"{candidates[0]} (attempt {attempt})"]
    return QueryPlan(
        original_query=plan.original_query,
        self_contained_query=unique[0],
        expansions=expansions,
        issue_tags=list(plan.issue_tags),
        include_original=False,
    )


# Backwards-compatible alias used by early tests.
rerwrite_plan = rewrite_plan


def run_with_verification(
    *,
    retriever: Retriever,
    corpus: Corpus,
    facts: list[Fact],
    as_of_date: date | None,
    plan: QueryPlan,
    case_summary: str,
    llm,
    settings: Settings | None = None,
    conversation_id: str | None = None,
) -> VerificationOutcome:
    settings = settings or get_settings()
    outcome = VerificationOutcome()
    used: set[str] = set()
    current = plan

    for attempt in range(settings.max_retrieval_retries + 1):
        result = retriever.search(
            current,
            include_expansions=(attempt == 0),
            conversation_id=conversation_id,
            retry_index=attempt,
        )
        queries = result.run.query_variants if result.run else []
        # Guarantee no identical query string is repeated across attempts.
        fresh_queries = [q for q in queries if q not in used]
        if attempt > 0 and not fresh_queries and queries:
            # all duplicates: skip this attempt rather than silently repeating
            logger.info("Retry %s produced only duplicate queries; stopping retries", attempt)
            outcome.attempts.append(
                AttemptRecord(attempt, queries, 0, 0, "all queries duplicated earlier attempts")
            )
            break
        used.update(queries)
        outcome.queries_seen.extend(queries)
        if result.run is not None:
            outcome.runs.append(result.run)

        expanded = expand(result.candidates, corpus)
        grades = relevance_filter.grade_candidates(case_summary, expanded, corpus, llm)
        candidates = assign_roles(
            expanded,
            corpus,
            facts,
            as_of_date,
            grades,
            min_grade=settings.relevance_min_grade,
        )
        accepted = [c for c in candidates if c.accepted]
        outcome.candidates = candidates
        outcome.accepted = accepted
        outcome.attempts.append(
            AttemptRecord(
                attempt=attempt,
                queries=queries,
                candidate_count=len(candidates),
                accepted_count=len(accepted),
                reason="accepted" if accepted else "nothing accepted",
            )
        )
        if accepted:
            outcome.retry_count = attempt
            outcome.abstained = False
            return outcome
        if attempt < settings.max_retrieval_retries:
            current = rewrite_plan(plan, attempt + 1, used)

    outcome.retry_count = len(outcome.attempts) - 1 if outcome.attempts else 0
    outcome.abstained = True
    return outcome
