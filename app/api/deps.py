"""FastAPI dependencies. Per Phase 6 s2, this module establishes request
context only - it never contains a business rule. Every dependency here
either builds a connection/clock the existing engines already accept, or
maps a demo identity to the real AuthContext the lower-level authorization
(app/authorization/context.py, enforced inside the repository/domain
layer) already treats as authoritative.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from app.api.demo_users import DEFAULT_DEMO_USERS, DemoUser
from app.config.settings import Settings, get_settings
from app.db.connection import connect
from app.llm.base import LLMProvider
from app.llm.factory import build_default_provider
from app.observability.tracing import RequestContext
from app.policy.applicability import (
    AGREEMENT_OVERRIDES,
    DEFAULT_SOURCE,
    AgreementOverride,
    ClauseTopic,
)
from app.time.clock import FixedSnapshotClock, SnapshotClock


def get_demo_users() -> dict[str, DemoUser]:
    """Overridden in tests (app.dependency_overrides) with a fixture-shaped
    equivalent so the same routes exercise tests/fixtures/seed_fixture_db.py
    (FX-00x accounts) instead of the real pack's ACCT-00x accounts."""
    return DEFAULT_DEMO_USERS


def get_current_user(
    x_demo_user: Annotated[str, Header(alias="X-Demo-User")] = "ops_admin",
    demo_users: dict[str, DemoUser] = Depends(get_demo_users),
) -> DemoUser:
    user = demo_users.get(x_demo_user)
    if user is None:
        raise HTTPException(status_code=400, detail=f"unknown demo identity: {x_demo_user!r}")
    return user


def get_db_path(settings: Settings = Depends(get_settings)) -> str:
    return str(settings.parcelpilot_db_path)


def get_conn(db_path: str = Depends(get_db_path)) -> Iterator[sqlite3.Connection]:
    if not Path(db_path).exists():
        raise HTTPException(
            status_code=503,
            detail="database not available - run scripts/ingest_sources.py first",
        )
    conn = connect(Path(db_path))
    try:
        yield conn
    finally:
        conn.close()


def get_clock(conn: sqlite3.Connection = Depends(get_conn)) -> SnapshotClock:
    row = conn.execute("SELECT value FROM meta WHERE key = 'snapshot_time'").fetchone()
    if row is None:
        raise HTTPException(status_code=503, detail="dataset snapshot time not found")
    return FixedSnapshotClock(datetime.fromisoformat(row["value"]))


def get_provider() -> tuple[LLMProvider, str]:
    """Live mode is opt-in via ANTHROPIC_API_KEY only - never fabricated,
    per app/llm/factory.py's rule. PARCELPILOT_MODEL lets the deployment
    pin a model without a code change."""
    live = bool(os.environ.get("ANTHROPIC_API_KEY"))
    model = os.environ.get("PARCELPILOT_MODEL", "claude-sonnet-4-5")
    return build_default_provider(live, model)


PolicyRegistry = tuple[tuple[AgreementOverride, ...], dict[ClauseTopic, tuple[str, str] | None]]


def get_policy_registry() -> PolicyRegistry:
    """Same production-default, test-injectable registry pattern already
    used by app/actions/workflow.py::prepare_escalation and
    app/detection/service.py::run_operations_radar - a real deployment
    always gets (AGREEMENT_OVERRIDES, DEFAULT_SOURCE); tests override this
    dependency with the fixture registries so the API layer is testable
    against tests/fixtures/seed_fixture_db.py without touching the real
    pack. Unlike app/agent/tools.py's tool boundary (deliberately fixed to
    production - see its module docstring), the API is not an LLM-facing
    surface, so extending the existing injection pattern here is not a
    new capability, just completing it at one more layer."""
    return AGREEMENT_OVERRIDES, DEFAULT_SOURCE


def get_request_context(request: Request) -> RequestContext:
    """Set once per HTTP request by app.api.middleware.RequestContextMiddleware
    so every dependency/route sees the same request_id/trace_id."""
    return request.state.request_context
