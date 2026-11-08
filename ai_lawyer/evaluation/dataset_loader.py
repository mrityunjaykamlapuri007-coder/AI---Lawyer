"""Load and validate retrieval-evaluation rows against a corpus."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ai_lawyer.legal_rag.corpus_loader import Corpus

REQUIRED_FIELDS = (
    "test_id",
    "split",
    "scenario_id",
    "user_query",
    "expected_provision_ids",
    "essential_provision_ids",
    "relevance_by_provision",
    "applicability_by_provision",
    "required_context_ids",
    "labeling_status",
)


@dataclass
class Dataset:
    rows: list[dict[str, Any]] = field(default_factory=list)

    def split(self, name: str) -> list[dict[str, Any]]:
        return [row for row in self.rows if row.get("split") == name]

    @property
    def fixture(self) -> bool:
        return all(str(row.get("labeling_status", "")).upper() == "FIXTURE" for row in self.rows)


def load_rows(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
            row["_line"] = line_no
            rows.append(row)
    return rows


def validate_rows(rows: Iterable[dict[str, Any]], corpus: Corpus) -> list[str]:
    errors: list[str] = []
    ids: set[str] = set()
    scenarios: dict[str, str] = {}
    known = set(corpus.provisions)

    for row in rows:
        line = row.get("_line", "?")
        for field_name in REQUIRED_FIELDS:
            if field_name not in row:
                errors.append(f"line {line}: missing field {field_name}")

        test_id = str(row.get("test_id", ""))
        if not test_id:
            errors.append(f"line {line}: empty test_id")
        elif test_id in ids:
            errors.append(f"line {line}: duplicate test_id {test_id}")
        ids.add(test_id)

        scenario = str(row.get("scenario_id", ""))
        split = str(row.get("split", ""))
        if scenario:
            other = scenarios.get(scenario)
            if other is not None and other != split:
                errors.append(
                    f"line {line}: scenario {scenario} appears in both {other} and {split}"
                )
            scenarios[scenario] = split

        referenced: list[str] = []
        referenced.extend(row.get("expected_provision_ids", []) or [])
        referenced.extend(row.get("essential_provision_ids", []) or [])
        referenced.extend(row.get("required_context_ids", []) or [])
        referenced.extend((row.get("relevance_by_provision", {}) or {}).keys())
        referenced.extend((row.get("applicability_by_provision", {}) or {}).keys())
        for pid in referenced:
            if pid not in known:
                errors.append(f"line {line}: provision id {pid} is not in the corpus")

        for pid, grade in (row.get("relevance_by_provision", {}) or {}).items():
            if not isinstance(grade, int) or not 0 <= grade <= 3:
                errors.append(f"line {line}: relevance grade for {pid} is not 0-3")

        for pid, label in (row.get("applicability_by_provision", {}) or {}).items():
            if label not in {"applicable", "not_applicable", "unknown"}:
                errors.append(f"line {line}: invalid applicability label {label!r} for {pid}")

        if str(row.get("split")) not in {"development", "test"}:
            errors.append(f"line {line}: split must be development or test")
    return errors


def load_dataset(directory: str | Path, corpus: Corpus) -> Dataset:
    directory = Path(directory)
    rows: list[dict[str, Any]] = []
    for name in ("development.jsonl", "test.jsonl"):
        path = directory / name
        if not path.exists():
            raise FileNotFoundError(f"missing dataset file: {path}")
        rows.extend(load_rows(path))
    errors = validate_rows(rows, corpus)
    if errors:
        raise ValueError("dataset validation failed:\n" + "\n".join(errors))
    return Dataset(rows=rows)
