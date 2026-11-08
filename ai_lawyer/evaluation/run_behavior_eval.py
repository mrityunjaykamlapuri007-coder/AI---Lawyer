"""Behaviour suite over the 17 end-to-end cases.

Each case gets a fresh SQLite database and evidence folder, a fixed ``now``
date, and the same fixture corpus / HashEmbedder / FakeLLM.  The unedited
response payloads are written under ``raw_outputs/behavior/<id>.json``; the
summary never rewrites them.

Run with:
    python -m ai_lawyer.evaluation.run_behavior_eval
"""
from __future__ import annotations

import csv
import json
import re
import tempfile
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ai_lawyer.backend.db.migrate import migrate
from ai_lawyer.backend.db.repo import Database
from ai_lawyer.backend.services.evidence_store import EvidenceStore
from ai_lawyer.backend.services.orchestrator import Orchestrator, Upload
from ai_lawyer.config.settings import PROJECT_ROOT, Settings
from ai_lawyer.contracts.fakes import FakeLLM, HashEmbedder
from ai_lawyer.legal_rag.corpus_loader import load_corpus
from ai_lawyer.legal_rag.index_manager import build_index
from ai_lawyer.legal_rag.retriever import Retriever

EVAL_DIR = PROJECT_ROOT / "ai_lawyer" / "evaluation"
DATASET = EVAL_DIR / "dataset" / "behavior_cases.jsonl"
RAW_DIR = EVAL_DIR / "raw_outputs" / "behavior"
RESULT_DIR = EVAL_DIR / "results"
FIXTURE_CORPUS = PROJECT_ROOT / "ai_lawyer" / "legal_corpus"
SECTION_RE = re.compile(r"\b(?:Section|Sec\.?|Rule)\s+\d+[A-Za-z]?", re.IGNORECASE)


def _settings(tmp: Path) -> Settings:
    return Settings(
        app_env="evaluation",
        corpus_mode="fixture",
        corpus_dir=str(FIXTURE_CORPUS),
        vectorstore_dir=str(tmp / "vectorstore"),
        sqlite_path=str(tmp / "lawyer.db"),
        evidence_dir=str(tmp / "evidence"),
        embedding_backend="hash",
        llm_provider="fake",
        reranker_enabled=False,
    )


def _load_cases() -> list[dict[str, Any]]:
    with DATASET.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _lower(text: Any) -> str:
    return str(text or "").lower()


def _run_turns(
    orchestrator: Orchestrator,
    conversation_id: str,
    settings: Settings,
    case: dict[str, Any],
    as_of: date,
) -> list[dict[str, Any]]:
    responses: list[dict[str, Any]] = []
    for turn in case.get("turns", []):
        uploads = None
        if turn.get("attachment_text"):
            uploads = [
                Upload(
                    filename=f"{case['test_id']}-attachment.txt",
                    data=str(turn["attachment_text"]).encode("utf-8"),
                )
            ]
        response = orchestrator.handle_message(
            conversation_id=conversation_id,
            user_id=settings.demo_user_id,
            message=turn.get("message", ""),
            uploads=uploads,
            as_of_date=as_of,
        )
        responses.append(response.model_dump(mode="json"))
    return responses


def _check_case(
    case: dict[str, Any],
    responses: list[dict[str, Any]],
    case_status: str | None,
    event_types: list[str],
    corpus,
) -> tuple[list[str], dict[str, Any]]:
    expected = case.get("expected") or {}
    final = responses[-1]
    text = final.get("assistant_message", "")
    failed: list[str] = []
    observed: dict[str, Any] = {}

    if "outcome" in expected:
        observed["outcome"] = final.get("assessment", {}).get("outcome")
        if observed["outcome"] != expected["outcome"]:
            failed.append(f"outcome {observed['outcome']!r} != {expected['outcome']!r}")
    if "outcome_any_of" in expected:
        observed["outcome"] = final.get("assessment", {}).get("outcome")
        if observed["outcome"] not in expected["outcome_any_of"]:
            failed.append(
                f"outcome {observed['outcome']!r} not in {expected['outcome_any_of']}"
            )

    if "must_ask_question" in expected:
        asked = bool(final.get("missing_information")) or "## Missing information" in text
        observed["asked_question"] = asked
        if asked != bool(expected["must_ask_question"]):
            failed.append(f"asked_question {asked} != {expected['must_ask_question']}")

    if "must_refuse" in expected:
        refused = final.get("processing_status") == "out_of_scope"
        observed["refused"] = refused
        if refused != bool(expected["must_refuse"]):
            failed.append(f"refused {refused} != {expected['must_refuse']}")

    if "max_questions" in expected:
        questions = final.get("missing_information") or []
        observed["question_count"] = len(questions)
        if len(questions) > int(expected["max_questions"]):
            failed.append(
                f"{len(questions)} questions > max {expected['max_questions']}: {questions}"
            )

    if "fact_status_checks" in expected:
        by_type: dict[str, list[dict[str, Any]]] = {}
        for fact in final.get("extracted_facts", []):
            by_type.setdefault(fact.get("fact_type", ""), []).append(fact)
        statuses: dict[str, str | None] = {}
        for fact_type, wanted in expected["fact_status_checks"].items():
            found = by_type.get(fact_type) or []
            actual = found[-1].get("status") if found else None
            statuses[fact_type] = actual
            if actual != wanted:
                failed.append(f"fact {fact_type} status {actual!r} != {wanted!r}")
        observed["fact_statuses"] = statuses

    if expected.get("no_document_draft"):
        draft = final.get("document_draft")
        observed["document_draft"] = draft.get("draft_type") if draft else None
        if draft:
            failed.append(f"unexpected document draft {draft.get('draft_type')!r}")

    if expected.get("no_legal_provisions_cited"):
        sources = final.get("legal_sources") or []
        observed["legal_source_count"] = len(sources)
        if sources:
            failed.append(f"expected no legal sources, got {len(sources)}")

    if "requires_corpus" in expected:
        used = (final.get("assessment") or {}).get("provision_ids_used") or []
        blobs = []
        for pid in used:
            provision = corpus.get(pid)
            if provision:
                blobs.append(
                    f"{provision.original_text} {provision.search_text} {provision.citation}".lower()
                )
        missing_tags = []
        for tag in expected["requires_corpus"]:
            words = tag.removesuffix("_route").replace("_", " ").lower().split()
            if not any(all(word in blob for word in words) for blob in blobs):
                missing_tags.append(tag)
        observed["required_corpus_tags"] = missing_tags or "satisfied"
        if missing_tags:
            failed.append(f"required corpus content not used: {missing_tags}")

    behavior = expected.get("case_behavior")
    if behavior:
        observed["case_behavior"] = behavior
        ids = [r.get("case_id") for r in responses if r.get("case_id")]
        if behavior == "new_case" and not ids:
            failed.append("expected a new case but no case_id was returned")
        elif behavior == "ask_split":
            if final.get("case_id") is not None:
                failed.append("expected no case for a two-order split")
            if "one message per order" not in _lower(text):
                failed.append("split clarification text missing")
        elif behavior == "same_case":
            if not ids or len(set(ids)) != 1:
                failed.append(f"expected one case id across turns, got {ids}")

    if "expect_case_status_final" in expected:
        observed["case_status"] = case_status
        if case_status != expected["expect_case_status_final"]:
            failed.append(
                f"case status {case_status!r} != {expected['expect_case_status_final']!r}"
            )

    if "expected_event_types" in expected:
        observed["event_types"] = event_types
        missing = [e for e in expected["expected_event_types"] if e not in event_types]
        if missing:
            failed.append(f"missing events: {missing}")

    if expected.get("expect_conflict_flag"):
        conflicts = [
            f for f in final.get("extracted_facts", []) if f.get("ambiguity_flag")
        ]
        observed["conflict_flags"] = len(conflicts)
        if not conflicts:
            failed.append("expected a conflict flag, none found")

    if expected.get("no_unsupported_section_numbers"):
        citations = " ".join(
            str(s.get("citation", "")) for s in final.get("legal_sources", [])
        ).lower()
        found = [m.group(0) for m in SECTION_RE.finditer(text)]
        unsupported = [item for item in found if item.lower() not in citations]
        observed["section_numbers"] = found
        if unsupported:
            failed.append(f"unsupported section numbers in text: {unsupported}")

    if "must_contain_any" in expected:
        hits = [item for item in expected["must_contain_any"] if _lower(item) in _lower(text)]
        observed["must_contain_any_hits"] = hits
        if not hits:
            failed.append(f"none of {expected['must_contain_any']} present")

    if "must_not_contain" in expected:
        bad = [item for item in expected["must_not_contain"] if _lower(item) in _lower(text)]
        observed["must_not_contain_hits"] = bad
        if bad:
            failed.append(f"forbidden text present: {bad}")

    if "document_draft_offered" in expected:
        draft = final.get("document_draft") or {}
        observed["document_draft"] = draft.get("draft_type")
        if draft.get("draft_type") != expected["document_draft_offered"]:
            failed.append(
                f"draft {draft.get('draft_type')!r} != {expected['document_draft_offered']!r}"
            )

    if "lawyer_needed" in expected:
        value = bool((final.get("assessment") or {}).get("lawyer_needed"))
        observed["lawyer_needed"] = value
        if value != bool(expected["lawyer_needed"]):
            failed.append(f"lawyer_needed {value} != {expected['lawyer_needed']}")

    return failed, observed


def _corpus_without(corpus, needle: str):
    """Return a copy of the corpus with every provision containing ``needle``.

    Used only for the B09 fallback check: the evaluator must show what happens
    when the Consumer Commission route is absent from the corpus.
    """
    from ai_lawyer.legal_rag.corpus_loader import provision_is_usable

    kept = {}
    removed: list[str] = []
    for pid, provision in corpus.provisions.items():
        blob = (
            f"{provision.original_text} {provision.search_text} {provision.citation}"
        ).lower()
        if needle in blob:
            removed.append(pid)
        else:
            kept[pid] = provision
    usable = sum(
        1
        for p in kept.values()
        if provision_is_usable(corpus.sources.get(p.source_id), p)
    )
    manifest = corpus.manifest.model_copy(
        update={
            "provisions_count": len(kept),
            "usable_count": usable,
            "unusable_count": len(kept) - usable,
        }
    )
    return replace(corpus, provisions=kept, manifest=manifest), removed


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    cases = _load_cases()
    summary: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        base = _settings(tmp)
        corpus = load_corpus(settings=base)
        index = build_index(
            corpus, HashEmbedder(), out_dir=base.vectorstore_path,
            max_chunk_chars=base.max_chunk_chars,
        )
        retriever = Retriever(index, corpus, base)

        for case in cases:
            case_dir = tmp / case["test_id"]
            case_dir.mkdir(parents=True, exist_ok=True)
            settings = base.model_copy(
                update={
                    "sqlite_path": str(case_dir / "lawyer.db"),
                    "evidence_dir": str(case_dir / "evidence"),
                }
            )
            migrate(settings.db_path)
            db = Database(settings.db_path)
            orchestrator = Orchestrator(
                db=db,
                corpus=corpus,
                retriever=retriever,
                llm=FakeLLM(),
                settings=settings,
                evidence_store=EvidenceStore(settings),
            )
            conversation = db.create_conversation(settings.demo_user_id)
            as_of = date.fromisoformat(case["now"])
            responses = _run_turns(
                orchestrator, conversation.conversation_id, settings, case, as_of
            )

            final = responses[-1]
            case_id = final.get("case_id")
            case_status = None
            event_types: list[str] = []
            if case_id:
                record = db.get_case(case_id)
                case_status = record.status if record else None
                event_types = [e["event_type"] for e in db.get_events(case_id)]

            failed, observed = _check_case(case, responses, case_status, event_types, corpus)
            raw = {
                "label": "FIXTURE DATA, NOT REAL LAW",
                "test_id": case["test_id"],
                "category": case.get("category"),
                "notes": case.get("notes"),
                "turns": case.get("turns"),
                "expected": case.get("expected"),
                "responses": responses,
                "case_status_final": case_status,
                "event_types": event_types,
                "checks_failed": failed,
                "observed": observed,
                "result": "PASS" if not failed else "FAIL",
            }
            (RAW_DIR / f"{case['test_id']}.json").write_text(
                json.dumps(raw, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            summary.append(
                {
                    "label": "FIXTURE DATA, NOT REAL LAW",
                    "test_id": case["test_id"],
                    "category": case.get("category", ""),
                    "result": raw["result"],
                    "observed_outcome": observed.get("outcome", ""),
                    "expected_outcome": case.get("expected", {}).get("outcome")
                    or "|".join(case.get("expected", {}).get("outcome_any_of", [])),
                    "case_status_final": case_status or "",
                    "checks_failed": "; ".join(failed),
                }
            )

        # B09 fallback: remove the Consumer Commission provision and confirm
        # that Python refuses to recommend formal proceedings without it.
        b09 = next((c for c in cases if c["test_id"] == "B09"), None)
        if b09 and b09.get("expected", {}).get("outcome_if_corpus_missing"):
            variant_dir = tmp / "B09_missing_corpus"
            variant_dir.mkdir(parents=True, exist_ok=True)
            variant_settings = base.model_copy(
                update={
                    "vectorstore_dir": str(variant_dir / "vectorstore"),
                    "sqlite_path": str(variant_dir / "lawyer.db"),
                    "evidence_dir": str(variant_dir / "evidence"),
                }
            )
            variant_corpus, removed = _corpus_without(corpus, "consumer commission")
            failed_variant: list[str] = []
            observed_variant: dict[str, Any] = {"removed_provisions": removed}
            variant_responses: list[dict[str, Any]] = []
            if not removed:
                failed_variant.append("could not remove the Consumer Commission provision")
            else:
                variant_index = build_index(
                    variant_corpus,
                    HashEmbedder(),
                    out_dir=variant_settings.vectorstore_path,
                    max_chunk_chars=variant_settings.max_chunk_chars,
                )
                variant_retriever = Retriever(variant_index, variant_corpus, variant_settings)
                migrate(variant_settings.db_path)
                variant_db = Database(variant_settings.db_path)
                variant_orchestrator = Orchestrator(
                    db=variant_db,
                    corpus=variant_corpus,
                    retriever=variant_retriever,
                    llm=FakeLLM(),
                    settings=variant_settings,
                    evidence_store=EvidenceStore(variant_settings),
                )
                variant_conversation = variant_db.create_conversation(
                    variant_settings.demo_user_id
                )
                variant_responses = _run_turns(
                    variant_orchestrator,
                    variant_conversation.conversation_id,
                    variant_settings,
                    b09,
                    date.fromisoformat(b09["now"]),
                )
                variant_final = variant_responses[-1]
                observed_variant["outcome"] = (
                    variant_final.get("assessment") or {}
                ).get("outcome")
                wanted = b09["expected"]["outcome_if_corpus_missing"]
                if observed_variant["outcome"] != wanted:
                    failed_variant.append(
                        f"outcome {observed_variant['outcome']!r} != fallback {wanted!r}"
                    )
                cited = [
                    s.get("provision_id") for s in variant_final.get("legal_sources") or []
                ]
                leaked = sorted(set(cited) & set(removed))
                observed_variant["leaked_citations"] = leaked
                if leaked:
                    failed_variant.append(f"removed provisions still cited: {leaked}")

            variant_raw = {
                "label": "FIXTURE DATA, NOT REAL LAW",
                "test_id": "B09_missing_corpus",
                "category": "corpus_missing_variant",
                "notes": (
                    "Derived from B09 by removing every provision that mentions "
                    "the Consumer Commission route."
                ),
                "turns": b09.get("turns"),
                "expected": {
                    "outcome": b09["expected"]["outcome_if_corpus_missing"],
                    "removed_corpus": b09["expected"].get("requires_corpus", []),
                },
                "responses": variant_responses,
                "checks_failed": failed_variant,
                "observed": observed_variant,
                "result": "PASS" if not failed_variant else "FAIL",
            }
            (RAW_DIR / "B09_missing_corpus.json").write_text(
                json.dumps(variant_raw, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            summary.append(
                {
                    "label": "FIXTURE DATA, NOT REAL LAW",
                    "test_id": "B09_missing_corpus",
                    "category": "corpus_missing_variant",
                    "result": variant_raw["result"],
                    "observed_outcome": observed_variant.get("outcome", ""),
                    "expected_outcome": b09["expected"]["outcome_if_corpus_missing"],
                    "case_status_final": "",
                    "checks_failed": "; ".join(failed_variant),
                }
            )

    with (RESULT_DIR / "behavior_summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)

    passed = sum(1 for row in summary if row["result"] == "PASS")
    manifest = {
        "label": "FIXTURE DATA, NOT REAL LAW",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": len(cases),
        "checks": len(summary),
        "passed": passed,
        "failed": len(summary) - passed,
        "derived_checks": ["B09_missing_corpus"],
        "corpus_mode": corpus.mode,
        "corpus_version": corpus.corpus_version,
        "embedder": index.manifest.get("embedder_id"),
        "llm": "fake (deterministic, offline)",
        "as_of_policy": "each case uses its own now date",
    }
    (RESULT_DIR / "behavior_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    for row in summary:
        print(
            f"{row['test_id']}: {row['result']} "
            f"({row['observed_outcome'] or row['case_status_final']})"
            + (f" — {row['checks_failed']}" if row["checks_failed"] else "")
        )
    print(f"FIXTURE behaviour: {passed}/{len(summary)} checks PASS ({len(cases)} core cases + derived fallback)")
    print(f"summary: {RESULT_DIR / 'behavior_summary.csv'}")


if __name__ == "__main__":
    main()
