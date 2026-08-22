"""Shared fixtures. Tests that need the real source pack are skipped when it
is not available - the pack is never committed (AGENTS.md rule 18), so a
clean checkout must not fail collection, only skip what it can't run.
"""

from __future__ import annotations

import os

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")  # no network calls during tests

import sqlite3  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from app.authorization.context import INTERNAL_SYSTEM_CONTEXT, AuthContext
from app.db.connection import connect
from app.time.clock import FixedSnapshotClock, SnapshotClock
from scripts.ingest_sources import ingest


def _find_source_dir() -> Path | None:
    env = os.environ.get("PARCELPILOT_SOURCE_DIR")
    if env:
        candidate = Path(env)
        return candidate if candidate.exists() else None
    default = Path(__file__).resolve().parents[2] / "parcelpilot-assessment" / "source-pack"
    return default if default.exists() else None


@pytest.fixture(scope="session")
def source_dir() -> Path:
    found = _find_source_dir()
    if found is None:
        pytest.skip("source pack not found; set PARCELPILOT_SOURCE_DIR to run this test")
    return found


@pytest.fixture(scope="session")
def ingested_db_path(tmp_path_factory: pytest.TempPathFactory, source_dir: Path) -> Path:
    db_path = tmp_path_factory.mktemp("db") / "parcelpilot.db"
    ingest(source_dir, db_path)
    return db_path


@pytest.fixture()
def conn(ingested_db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(ingested_db_path)
    yield connection
    connection.close()


@pytest.fixture()
def clock(conn: sqlite3.Connection) -> SnapshotClock:
    row = conn.execute("SELECT value FROM meta WHERE key = 'snapshot_time'").fetchone()
    return FixedSnapshotClock(datetime.fromisoformat(row["value"]))


@pytest.fixture()
def auth() -> AuthContext:
    return INTERNAL_SYSTEM_CONTEXT
