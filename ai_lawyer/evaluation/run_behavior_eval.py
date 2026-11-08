"""Behaviour suite over the 17 end-to-end cases.

Each case gets a fresh SQLite database and evidence folder, a fixed ``now``
date, and the same fixture corpus / HashEmbedder / FakeLLM.  The unedited
response payloads are written under ``raw_outputs/behavior/<id>.json``; the
summary never rewrites them.

Run with:
    python -m ai_lawyer.evaluation.run_behavior_eval
"""
from __future__ import annotations

import argparse
import csv
import hashlib
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
from ai_lawyer.backend.services.llm_providers import get_llm
from ai_lawyer.backend.services.orchestrator import Orchestrator, Upload
from ai_lawyer.config.settings import PROJECT_ROOT, Settings
from ai_lawyer.contracts.errors import CorpusValidationError, UserSafeError
from ai_lawyer.tests.fakes import FakeLLM, HashEmbedder
from ai_lawyer.legal_rag.corpus_loader import load_corpus
from ai_lawyer.legal_rag.embedders import get_embedder
from ai_lawyer.legal_rag.index_manager import build_index
from ai_lawyer.legal_rag.retriever import Retriever

EVAL_DIR = PROJECT_ROOT / "ai_lawyer" / "evaluation"
DATASET = EVAL_DIR / "dataset" / "behavior_cases.jsonl"
RAW_DIR = EVAL_DIR / "raw_outputs" / "behavior"
RESULT_DIR = EVAL_DIR / "results"
FIXTURE_CORPUS = PROJECT_ROOT / "ai_lawyer" / "legal_corpus"
SECTION_RE = re.compile(r"\b(?:Section|Sec\.?|Rule)\s+(\d+[A-Za-z]?)", re.IGNORECASE)


def _settings(tmp: Path, mode: str = "fixture", corpus_dir: Path | None = None) -> Settings:
    values = {
        "app_env": "evaluation",
        "corpus_mode": mode,
        "corpus_dir": str(corpus_dir or FIXTURE_CORPUS),
        "vectorstore_dir": str(tmp / "vectorstore"),
        "sqlite_path": str(tmp / "lawyer.db"),
        "evidence_dir": str(tmp / "evidence"),
        "reranker_enabled": False,
    }
    if mode == "fixture":
        values.update(embedding_backend="hash", llm_provider="fake")
    return Settings(**values)


def _load_cases(path: Path = DATASET) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def dataset_origin(cases: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Return (origin, problem).  Purge rule: one origin per run, every row tagged."""
    origins = {str(c.get("data_origin") or "") for c in cases}
    if "" in origins:
        return None, "some rows have no data_origin tag"
    if len(origins) > 1:
        return None, f"rows mix data origins {sorted(origins)}; run them as separate tables"
    return origins.pop() if origins else None, None


STANDARD_FORBIDDEN = ("violated", "broke the law", "illegal", "you will win", "guaranteed")


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

    if expected.get("outcome") == "undetermined":
        # Rules R0-R7 do not settle this story from its stated facts: record the
        # output without an outcome pass/fail.
        observed["outcome"] = final.get("assessment", {}).get("outcome")
    elif "outcome" in expected:
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


def _usable_section_numbers(corpus) -> set[str]:
    numbers: set[str] = set()
    for pid in corpus.usable_ids():
        provision = corpus.provisions[pid]
        for text in (provision.citation, provision.original_text[:400]):
            numbers.update(m.group(1).lower() for m in SECTION_RE.finditer(text))
    return numbers


def _unverified_section_numbers(responses: list[dict[str, Any]], corpus) -> list[str]:
    allowed = _usable_section_numbers(corpus)
    found: list[str] = []
    for response in responses:
        for match in SECTION_RE.finditer(response.get("assistant_message", "")):
            if match.group(1).lower() not in allowed and match.group(0) not in found:
                found.append(match.group(0))
    return found


def _write_real_summary(
    result_dir: Path,
    rows: list[dict[str, Any]],
    manifest: dict[str, Any],
    section_defects: list[str],
    b09_note: str,
) -> Path:
    lines = [
        "# Real-corpus behaviour run",
        "",
        f"**Data origin: `{manifest.get('data_origin')}`. {manifest.get('data_note', '')}**",
        "",
        f"- generated: {manifest['generated_at']}",
        f"- corpus: `{manifest['corpus_version']}` "
        f"(mode={manifest['corpus_mode']}, usable={manifest['corpus_usable']})",
        f"- LLM: `{manifest['llm_model']}` via `{manifest['llm_provider']}`",
        f"- embedder: `{manifest['embedder']}`",
        f"- vLLM: `{manifest.get('vllm_version') or 'not recorded'}`",
        f"- quantization: `{manifest.get('quantization') or 'not recorded'}`",
        f"- GPU: `{manifest.get('gpu_type') or 'not recorded'}`",
        "",
        "## Results",
        "",
        "| case | result | observed outcome | failing assertion |",
        "|---|---|---|---|",
    ]
    for row in rows:
        failed = row["checks_failed"].replace("|", "\\|")
        lines.append(
            f"| {row['test_id']} | {row['result']} | "
            f"{row['observed_outcome'] or row['case_status_final']} | {failed or '-'} |"
        )
    lines += [
        "",
        "## B09 Consumer Commission route",
        "",
        b09_note,
        "",
        "## Section numbers not in the verified corpus",
        "",
    ]
    if section_defects:
        lines += [f"- CRITICAL: `{item}`" for item in section_defects]
    else:
        lines.append("None found in any assistant message.")
    lines += [
        "",
        "## Notes",
        "",
        "Raw files in `raw/` are code-written and unedited. This table is derived",
        "from them. A failing assertion is quoted, not rewritten.",
        "",
    ]
    path = result_dir / "summary.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ai_lawyer.evaluation.run_behavior_eval",
        description="Run B01-B17 in fixture or real mode.",
    )
    parser.add_argument("--mode", choices=["fixture", "real"], default="fixture")
    parser.add_argument("--vllm-version", default="")
    parser.add_argument("--quantization", default="")
    parser.add_argument("--gpu-type", default="")
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=None,
        help="real-mode corpus directory (default: ai_lawyer/legal_corpus)",
    )
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument(
        "--synthetic-table",
        action="store_true",
        help="real mode only: allow synthetic stories, reported in a separate labeled table",
    )
    args = parser.parse_args(argv)

    real = args.mode == "real"
    cases = _load_cases(args.dataset)
    origin, origin_problem = dataset_origin(cases)
    synthetic = bool(origin and origin.startswith("synthetic"))
    if real and origin_problem:
        print(f"BLOCKED: {origin_problem}.")
        return 2
    if real and synthetic and not args.synthetic_table:
        print(
            f"BLOCKED: dataset rows are data_origin={origin}. Real-mode results on "
            "synthetic stories are only written to a separate table; pass --synthetic-table."
        )
        return 2
    if real:
        table = "real_behavior_synthetic" if synthetic else "real_behavior"
        raw_dir = RESULT_DIR / table / "raw"
        result_dir = RESULT_DIR / table
    else:
        raw_dir = RAW_DIR
        result_dir = RESULT_DIR
    raw_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    summary: list[dict[str, Any]] = []
    section_defects: list[str] = []

    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        base = _settings(tmp, args.mode, args.corpus_dir)
        try:
            corpus = load_corpus(settings=base)
        except CorpusValidationError as exc:
            print("BLOCKED: the real corpus is not loadable, so nothing was run.")
            for error in exc.errors:
                print(f"  - {error}")
            print("Run `python -m ai_lawyer.legal_rag.build_runtime_corpus` after approval.")
            return 2
        if real and corpus.usable_count == 0:
            print(
                "BLOCKED: real corpus has no usable provisions. Approve at least "
                "one source and provision, then rebuild the runtime corpus."
            )
            return 2
        try:
            embedder = get_embedder(base)
            llm = get_llm(base) if real else FakeLLM()
            index = build_index(
                corpus, embedder, out_dir=base.vectorstore_path,
                max_chunk_chars=base.max_chunk_chars,
            )
        except UserSafeError as exc:
            # Rule 9: real mode fails closed with a clear message, never a fallback.
            print(f"BLOCKED: {exc.user_safe_message}")
            if exc.details.get("detail"):
                print(f"  - {exc.details['detail']}")
            print("Start kaggle/serve_all.ipynb, fill .env, then run "
                  "`python -m ai_lawyer.tools.check_remote`.")
            return 2
        retriever = Retriever(index, corpus, base)
        label = (
            f"REAL CORPUS, VERIFIED SUBSET ({corpus.usable_count} usable)"
            if real
            else "FIXTURE DATA, NOT REAL LAW"
        )

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
                llm=llm if real else FakeLLM(),
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
            if not synthetic:
                said = " ".join(_lower(r.get("assistant_message")) for r in responses)
                hits = [p for p in STANDARD_FORBIDDEN if p in said]
                if hits:
                    failed.append(f"forbidden phrase(s) present: {hits}")
            if real:
                invented = _unverified_section_numbers(responses, corpus)
                if invented:
                    failed.append(
                        "assistant cites section number(s) absent from the verified "
                        f"corpus: {', '.join(invented)}"
                    )
                    for item in invented:
                        if item not in section_defects:
                            section_defects.append(item)

            raw = {
                "label": label,
                "test_id": case["test_id"],
                "category": case.get("category"),
                "notes": case.get("notes"),
                "now": case.get("now"),
                "turns": case.get("turns"),
                "expected": case.get("expected"),
                "corpus": {
                    "mode": corpus.mode,
                    "version": corpus.corpus_version,
                    "usable_count": corpus.usable_count,
                    "usable_ids": sorted(corpus.usable_ids()),
                },
                "responses": responses,
                "case_status_final": case_status,
                "event_types": event_types,
                "checks_failed": failed,
                "observed": observed,
                "data_origin": case.get("data_origin"),
                "split": case.get("split"),
                "result": (
                    "FAIL" if failed
                    else "RECORDED" if case.get("expected", {}).get("outcome") == "undetermined"
                    else "PASS"
                ),
            }
            (raw_dir / f"{case['test_id']}.json").write_text(
                json.dumps(raw, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            summary.append(
                {
                    "label": label,
                    "test_id": case["test_id"],
                    "split": case.get("split", ""),
                    "category": case.get("category", ""),
                    "result": raw["result"],
                    "observed_outcome": observed.get("outcome", ""),
                    "expected_outcome": case.get("expected", {}).get("outcome")
                    or "|".join(case.get("expected", {}).get("outcome_any_of", [])),
                    "case_status_final": case_status or "",
                    "checks_failed": "; ".join(failed),
                }
            )

        if not real:
            # Fixture-only diagnostic: remove the Consumer Commission provision
            # and confirm Python refuses formal proceedings without it.
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

    with (result_dir / "behavior_summary.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)

    passed = sum(1 for row in summary if row["result"] == "PASS")
    manifest = {
        "label": label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "data_origin": origin,
        "data_note": (
            "SYNTHETIC STORIES, NOT REAL DATA: written for testing; do not present as results on real disputes"
            if synthetic
            else "real stories"
        ),
        "cases": len(cases),
        "checks": len(summary),
        "passed": passed,
        "failed": sum(1 for row in summary if row["result"] == "FAIL"),
        "recorded_without_pass_fail": sum(1 for row in summary if row["result"] == "RECORDED"),
        "per_split": {
            split: {
                result: sum(1 for r in summary if r.get("split") == split and r["result"] == result)
                for result in ("PASS", "FAIL", "RECORDED")
            }
            for split in sorted({r.get("split") or "none" for r in summary})
        },
        "embedder_model_hash": index.manifest.get("embedder_model_hash"),
        "trust_level": base.corpus_trust_level,
        # R-5: raw outputs are code-written; hashes let any later edit be detected.
        "raw_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(raw_dir.glob("*.json"))
        },
        "derived_checks": [] if real else ["B09_missing_corpus"],
        "corpus_mode": corpus.mode,
        "corpus_version": corpus.corpus_version,
        "corpus_usable": corpus.usable_count,
        "embedder": index.manifest.get("embedder_id"),
        "llm": (
            f"{base.llm_provider}:{base.llm_model_name}" if real else "fake (deterministic, offline)"
        ),
        "llm_provider": base.llm_provider,
        "llm_model": base.llm_model_name if real else "fake",
        "vllm_version": args.vllm_version,
        "quantization": args.quantization,
        "gpu_type": args.gpu_type,
        "as_of_policy": "each case uses its own now date",
        "unverified_section_numbers": section_defects,
    }
    (result_dir / ("manifest.json" if real else "behavior_manifest.json")).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if real:
        b09_row = next((r for r in summary if r["test_id"] == "B09"), None)
        b09_note = (
            "Not run."
            if b09_row is None
            else (
                f"Result: {b09_row['result']}; observed outcome "
                f"`{b09_row['observed_outcome'] or b09_row['case_status_final']}`. "
                "B09 passes only if the verified corpus holds the Consumer "
                "Commission route; otherwise `needs_more_information` is correct. "
                "The case was not edited."
            )
        )
        path = _write_real_summary(result_dir, summary, manifest, section_defects, b09_note)
        print(f"summary: {path}")

    for row in summary:
        print(
            f"{row['test_id']}: {row['result']} "
            f"({row['observed_outcome'] or row['case_status_final']})"
            + (f" — {row['checks_failed']}" if row["checks_failed"] else "")
        )
    if real and section_defects:
        print("CRITICAL unverified section numbers: " + ", ".join(section_defects))
    scoped = "REAL" if real else "FIXTURE"
    print(
        f"{scoped}: {passed}/{len(summary)} checks PASS "
        f"({len(cases)} core cases" + ("" if real else " + derived fallback") + ")"
    )
    print(f"summary: {result_dir / 'behavior_summary.csv'}")
    return 0 if passed == len(summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
