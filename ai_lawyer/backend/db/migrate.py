"""Explicit migration.  Tables are NEVER created on import."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from ai_lawyer.config.settings import get_settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def migrate(db_path: str | Path) -> Path:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = sqlite3.connect(str(path), timeout=30)
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the SQLite schema")
    parser.add_argument("--db", default=None)
    args = parser.parse_args()
    path = args.db or get_settings().db_path
    print(f"migrated {migrate(path)}")


if __name__ == "__main__":
    main()
