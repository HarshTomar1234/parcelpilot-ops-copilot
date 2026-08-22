"""Fixtures for the always-runs public CI tier. No dependency on
PARCELPILOT_SOURCE_DIR or the real pack anywhere in this file.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from app.authorization.context import INTERNAL_SYSTEM_CONTEXT, AuthContext
from app.db.connection import init_db
from app.time.clock import FixedSnapshotClock, SnapshotClock
from tests.fixtures.seed_fixture_db import FIXTURE_SNAPSHOT, build_fixture_db


@pytest.fixture(scope="session")
def fixture_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    db_path = tmp_path_factory.mktemp("fixture_db") / "fixture.db"
    conn = init_db(db_path)
    build_fixture_db(conn)
    conn.close()
    return db_path


@pytest.fixture()
def conn(fixture_db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(fixture_db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    yield connection
    connection.close()


@pytest.fixture()
def clock() -> SnapshotClock:
    return FixedSnapshotClock(datetime.fromisoformat(FIXTURE_SNAPSHOT))


@pytest.fixture()
def auth() -> AuthContext:
    return INTERNAL_SYSTEM_CONTEXT
