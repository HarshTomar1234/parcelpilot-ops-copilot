"""SQLite connection and schema initialization.

The database is a rebuilt-from-scratch artefact (scripts/ingest_sources.py
always starts from an empty file), never a target for incremental migration
in Phase 1 - so "migration path" here means "deterministic full rebuild",
which is the correct scope for a tiny, immutable corpus.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: Path) -> sqlite3.Connection:
    """Create a fresh database at db_path, replacing any existing file."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = connect(db_path)
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    return conn
