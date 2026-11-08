"""SQLite repositories.  Parameterised SQL only; no table creation on import."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_lawyer.contracts.ids import new_id
from ai_lawyer.contracts.models import (
    CaseRecord,
    Conversation,
    DocumentDraft,
    Evidence,
    Fact,
    Message,
    PageExtraction,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def _connect(self):
        """Commit-and-close helper.

        ``with sqlite3.Connection`` commits but does not close the connection,
        which leaks file handles (and locks the database on Windows).  Every
        short-lived query goes through this helper instead.
        """
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- users / conversations / messages ---------------------------------
    def ensure_user(self, user_id: str) -> str:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users(user_id, created_at) VALUES (?, ?)",
                (user_id, _now()),
            )
        return user_id

    def create_conversation(self, user_id: str) -> Conversation:
        self.ensure_user(user_id)
        conv = Conversation(user_id=user_id)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations(conversation_id, user_id, created_at) VALUES (?, ?, ?)",
                (conv.conversation_id, user_id, conv.created_at.isoformat()),
            )
        return conv

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE conversation_id = ?", (conversation_id,)
            ).fetchone()
        return dict(row) if row else None

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        payload: dict[str, Any] | None = None,
        message_id: str | None = None,
    ) -> Message:
        msg = Message(
            message_id=message_id or new_id("msg_"),
            conversation_id=conversation_id,
            role=role,  # type: ignore[arg-type]
            content=content,
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO messages(message_id, conversation_id, role, content, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    msg.message_id,
                    conversation_id,
                    role,
                    content,
                    _dumps(payload) if payload is not None else None,
                    msg.created_at.isoformat(),
                ),
            )
        return msg

    # -- cases -------------------------------------------------------------
    def create_case(
        self,
        user_id: str,
        summary: dict[str, Any],
        conversation_id: str | None = None,
    ) -> str:
        case_id = new_id("case_")
        now = _now()
        for attempt in range(6):
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO cases(case_id, user_id, conversation_id, status, summary_json, created_at, updated_at) "
                    "VALUES (?, ?, ?, 'open', ?, ?, ?)",
                    (case_id, user_id, conversation_id, _dumps(summary), now, now),
                )
                conn.execute(
                    "INSERT INTO case_events(event_id, case_id, sequence_no, event_type, payload_json, created_at) "
                    "VALUES (?, ?, 1, 'case_created', ?, ?)",
                    (new_id("evt_"), case_id, _dumps({"summary": summary}), now),
                )
                conn.commit()
                return case_id
            except sqlite3.OperationalError as exc:
                conn.rollback()
                if "locked" not in str(exc).lower() or attempt == 5:
                    raise
                time.sleep(0.03 * (attempt + 1))
            finally:
                conn.close()
        raise RuntimeError("unreachable")

    def get_case(self, case_id: str) -> CaseRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        return self._row_to_case(row) if row else None

    def _row_to_case(self, row: sqlite3.Row) -> CaseRecord:
        return CaseRecord(
            case_id=row["case_id"],
            user_id=row["user_id"],
            status=row["status"],
            summary=_loads(row["summary_json"], {}),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def list_cases(self, user_id: str) -> list[CaseRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cases WHERE user_id = ? ORDER BY updated_at DESC", (user_id,)
            ).fetchall()
        return [self._row_to_case(r) for r in rows]

    def open_cases(self, user_id: str) -> list[CaseRecord]:
        return [c for c in self.list_cases(user_id) if c.status in {"open", "reopened"}]

    def cases_for_conversation(self, conversation_id: str) -> list[CaseRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cases WHERE conversation_id = ? ORDER BY updated_at DESC",
                (conversation_id,),
            ).fetchall()
        return [self._row_to_case(r) for r in rows]

    def update_case(
        self,
        case_id: str,
        *,
        status: str | None = None,
        summary: dict[str, Any] | None = None,
    ) -> None:
        sets: list[str] = ["updated_at = ?"]
        params: list[Any] = [_now()]
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if summary is not None:
            sets.append("summary_json = ?")
            params.append(_dumps(summary))
        params.append(case_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE cases SET {', '.join(sets)} WHERE case_id = ?", params)

    def find_cases_by_identifier(self, user_id: str, value: str) -> list[CaseRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT c.* FROM cases c "
                "JOIN case_facts f ON f.case_id = c.case_id "
                "WHERE c.user_id = ? AND f.fact_type IN ('order_id', 'transaction_id') "
                "AND (f.raw_value = ? OR f.normalised_value_json = ?)",
                (user_id, value, _dumps(value)),
            ).fetchall()
        return [self._row_to_case(r) for r in rows]

    # -- events ------------------------------------------------------------
    def append_event(self, case_id: str, event_type: str, payload: dict[str, Any]) -> int:
        for attempt in range(6):
            conn = self.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT COALESCE(MAX(sequence_no), 0) AS seq FROM case_events WHERE case_id = ?",
                    (case_id,),
                ).fetchone()
                seq = int(row["seq"]) + 1
                conn.execute(
                    "INSERT INTO case_events(event_id, case_id, sequence_no, event_type, payload_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (new_id("evt_"), case_id, seq, event_type, _dumps(payload), _now()),
                )
                conn.execute("UPDATE cases SET updated_at = ? WHERE case_id = ?", (_now(), case_id))
                conn.commit()
                return seq
            except sqlite3.OperationalError as exc:
                conn.rollback()
                if "locked" not in str(exc).lower() or attempt == 5:
                    raise
                time.sleep(0.03 * (attempt + 1))
            finally:
                conn.close()
        raise RuntimeError("unreachable")

    def get_events(self, case_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM case_events WHERE case_id = ? ORDER BY sequence_no",
                (case_id,),
            ).fetchall()
        return [
            {
                "event_id": r["event_id"],
                "case_id": r["case_id"],
                "sequence_no": r["sequence_no"],
                "event_type": r["event_type"],
                "payload": _loads(r["payload_json"], {}),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def latest_event(self, case_id: str, event_type: str) -> dict[str, Any] | None:
        events = [e for e in self.get_events(case_id) if e["event_type"] == event_type]
        return events[-1] if events else None

    # -- facts -------------------------------------------------------------
    def add_fact(self, fact: Fact) -> str:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO case_facts(fact_id, case_id, fact_type, raw_value, normalised_value_json, "
                "source_type, source_id, evidence_id, page_number, status, inferred, ambiguity_flag, "
                "supersedes_fact_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fact.fact_id,
                    fact.case_id,
                    fact.fact_type,
                    fact.raw_value,
                    _dumps(fact.normalised_value),
                    fact.source_type,
                    fact.source_id,
                    fact.evidence_id,
                    fact.page_number,
                    fact.status,
                    int(fact.inferred),
                    int(fact.ambiguity_flag),
                    fact.supersedes_fact_id,
                    fact.created_at.isoformat(),
                ),
            )
        return fact.fact_id

    def get_facts(self, case_id: str) -> list[Fact]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM case_facts WHERE case_id = ? ORDER BY created_at", (case_id,)
            ).fetchall()
        return [
            Fact(
                fact_id=r["fact_id"],
                case_id=r["case_id"],
                fact_type=r["fact_type"],
                raw_value=r["raw_value"],
                normalised_value=_loads(r["normalised_value_json"], None),
                source_type=r["source_type"],
                source_id=r["source_id"],
                evidence_id=r["evidence_id"],
                page_number=r["page_number"],
                status=r["status"],
                inferred=bool(r["inferred"]),
                ambiguity_flag=bool(r["ambiguity_flag"]),
                supersedes_fact_id=r["supersedes_fact_id"],
                created_at=datetime.fromisoformat(r["created_at"]),
            )
            for r in rows
        ]

    # -- messages ----------------------------------------------------------
    def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at",
                (conversation_id,),
            ).fetchall()
        return [
            {
                "message_id": r["message_id"],
                "conversation_id": r["conversation_id"],
                "role": r["role"],
                "content": r["content"],
                "payload": _loads(r["payload_json"], None),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # -- evidence ----------------------------------------------------------
    def save_evidence(self, evidence: Evidence) -> str:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO evidence(evidence_id, case_id, original_filename, storage_key, sha256, "
                "mime_type, size_bytes, extraction_status, error_code, pages_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    evidence.evidence_id,
                    evidence.case_id,
                    evidence.original_filename,
                    evidence.storage_key,
                    evidence.sha256,
                    evidence.mime_type,
                    evidence.size_bytes,
                    evidence.extraction_status,
                    evidence.error_code,
                    _dumps([p.model_dump(mode="json") for p in evidence.pages]),
                    evidence.created_at.isoformat(),
                ),
            )
        return evidence.evidence_id

    def attach_evidence_to_case(self, evidence_id: str, case_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE evidence SET case_id = ? WHERE evidence_id = ?", (case_id, evidence_id)
            )

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)
            ).fetchone()
        if not row:
            return None
        return Evidence(
            evidence_id=row["evidence_id"],
            case_id=row["case_id"],
            original_filename=row["original_filename"],
            storage_key=row["storage_key"],
            sha256=row["sha256"],
            mime_type=row["mime_type"],
            size_bytes=row["size_bytes"],
            extraction_status=row["extraction_status"],
            error_code=row["error_code"],
            pages=[PageExtraction.model_validate(p) for p in _loads(row["pages_json"], [])],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # -- drafts ------------------------------------------------------------
    def save_draft(self, draft: DocumentDraft) -> str:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO document_drafts(draft_id, case_id, draft_type, content, status, "
                "missing_fields_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    draft.draft_id,
                    draft.case_id,
                    draft.draft_type,
                    draft.content,
                    draft.status,
                    _dumps(draft.missing_fields),
                    draft.created_at.isoformat(),
                ),
            )
        return draft.draft_id

    def list_drafts(self, case_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM document_drafts WHERE case_id = ? ORDER BY created_at DESC",
                (case_id,),
            ).fetchall()
        return [
            {
                "draft_id": r["draft_id"],
                "case_id": r["case_id"],
                "draft_type": r["draft_type"],
                "content": r["content"],
                "status": r["status"],
                "missing_fields": _loads(r["missing_fields_json"], []),
                "created_at": r["created_at"],
            }
            for r in rows
        ]
