"""Fixtures for the red-team suite (final release validation phase).
Mirrors tests/fixture_backed/conftest.py exactly (same fabricated,
version-controlled dataset, same DI-override technique for the `client`
fixture) - red-team tests never need the real pack or a live server;
they attack the same in-process ASGI app and fixture database that
guarantee this tier always runs.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from app.authorization.context import INTERNAL_SYSTEM_CONTEXT, AuthContext, Role
from app.db.connection import init_db
from app.time.clock import FixedSnapshotClock, SnapshotClock
from tests.fixtures.seed_fixture_db import (
    FIXTURE_AGREEMENT_OVERRIDES,
    FIXTURE_DEFAULT_SOURCE,
    FIXTURE_SNAPSHOT,
    build_fixture_db,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def fixture_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    db_path = tmp_path_factory.mktemp("red_team_fixture_db") / "fixture.db"
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


@pytest.fixture()
def client(fixture_db_path: Path) -> Iterator[TestClient]:
    from fastapi.testclient import TestClient

    from app.api.demo_users import DemoUser
    from app.api.deps import (
        get_clock,
        get_conn,
        get_demo_users,
        get_policy_registry,
        get_provider,
    )
    from app.api.main import app
    from app.config.settings import Settings, get_settings
    from app.llm.mock_provider import MockProvider

    fixture_demo_users = {
        "ops_admin": DemoUser(
            id="ops_admin", display_name="Fixture Ops Admin",
            role=Role.OPERATIONS_ADMIN, account_scope=None,
        ),
        "support_agent": DemoUser(
            id="support_agent", display_name="Fixture Support Agent (FX-001)",
            role=Role.SUPPORT_AGENT, account_scope=["FX-001"],
        ),
        "support_agent_b": DemoUser(
            id="support_agent_b", display_name="Fixture Support Agent B (FX-004)",
            role=Role.SUPPORT_AGENT, account_scope=["FX-004"],
        ),
        "restricted_support": DemoUser(
            id="restricted_support", display_name="Fixture Restricted Support (FX-002)",
            role=Role.RESTRICTED_SUPPORT, account_scope=["FX-002"],
        ),
    }

    def _get_conn() -> Iterator[sqlite3.Connection]:
        # check_same_thread=False: matches app.db.connection.connect()'s
        # fix - a TestClient dispatch under real thread concurrency (see
        # tests/red_team/test_concurrency.py) hits the exact same
        # cross-thread SQLite error this override would otherwise
        # reintroduce.
        connection = sqlite3.connect(fixture_db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    app.dependency_overrides[get_conn] = _get_conn
    app.dependency_overrides[get_clock] = lambda: FixedSnapshotClock(
        datetime.fromisoformat(FIXTURE_SNAPSHOT)
    )
    app.dependency_overrides[get_demo_users] = lambda: fixture_demo_users
    app.dependency_overrides[get_policy_registry] = lambda: (
        FIXTURE_AGREEMENT_OVERRIDES, FIXTURE_DEFAULT_SOURCE,
    )
    app.dependency_overrides[get_provider] = lambda: (MockProvider(), "mock-model")
    app.dependency_overrides[get_settings] = lambda: Settings(
        parcelpilot_source_dir=None, parcelpilot_db_path=fixture_db_path,
    )

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
