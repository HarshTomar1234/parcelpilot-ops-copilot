"""Liveness/readiness (Phase 6 s16). /health only proves the process is
up. /ready proves the runtime dependencies a request actually needs are
present - the SQLite database file, and a valid dataset snapshot inside
it - without exposing any secret or internal path detail beyond what's
already public in .env.example.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.demo_users import DemoUser
from app.api.deps import get_demo_users
from app.config.settings import Settings, get_settings
from app.db.connection import connect

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(settings: Settings = Depends(get_settings)) -> JSONResponse:
    db_path = Path(settings.parcelpilot_db_path)
    checks = {"database_file_present": db_path.exists(), "dataset_snapshot_present": False}
    dataset_snapshot: str | None = None

    if checks["database_file_present"]:
        try:
            conn = connect(db_path)
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'snapshot_time'"
            ).fetchone()
            checks["dataset_snapshot_present"] = row is not None
            dataset_snapshot = row["value"] if row else None
            conn.close()
        except sqlite3.Error:
            checks["dataset_snapshot_present"] = False

    is_ready = all(checks.values())
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={
            "status": "ready" if is_ready else "not_ready",
            "checks": checks,
            "dataset_snapshot": dataset_snapshot,
        },
    )


@router.get("/api/demo-users")
def list_demo_users(
    demo_users: dict[str, DemoUser] = Depends(get_demo_users),
) -> list[DemoUser]:
    """Lets the UI populate an identity picker without a real login -
    server-owned, never client-constructed (Phase 6 s4)."""
    return list(demo_users.values())
