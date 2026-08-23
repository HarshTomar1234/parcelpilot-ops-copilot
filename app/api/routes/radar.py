"""POST /api/radar/run, GET /api/radar/alerts/{alert_id} (Phase 6 s10). No
detection logic here - both routes call run_operations_radar() and let its
existing authorization (structural account-scope filtering plus the
restricted_support role denial) decide what comes back.
"""

from __future__ import annotations

import logging
import sqlite3
import time

from fastapi import APIRouter, Depends, HTTPException

from app.api.demo_users import DemoUser
from app.api.deps import PolicyRegistry, get_clock, get_conn, get_current_user, get_policy_registry
from app.api.schemas import RadarRequest, RadarResponse
from app.detection.models import AlertCandidate
from app.detection.service import group_by_account, run_operations_radar
from app.errors import NotAuthorizedError
from app.time.clock import SnapshotClock

router = APIRouter(tags=["radar"])
logger = logging.getLogger("api.radar")


@router.post("/api/radar/run", response_model=RadarResponse)
def run_radar(
    body: RadarRequest,
    user: DemoUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: SnapshotClock = Depends(get_clock),
    registry: PolicyRegistry = Depends(get_policy_registry),
) -> RadarResponse:
    overrides, defaults = registry
    start = time.perf_counter()
    try:
        alerts = run_operations_radar(
            conn, user.to_auth_context(), clock,
            alert_types=body.alert_types, window_days=body.window_days,
            overrides=overrides, defaults=defaults,
        )
    except NotAuthorizedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    latency_ms = (time.perf_counter() - start) * 1000

    logger.info(
        "radar_run",
        extra={
            "demo_user": user.id, "role": user.role.value,
            "alert_count": len(alerts), "latency_ms": round(latency_ms, 3),
        },
    )
    return RadarResponse(
        alerts=alerts,
        total_alerts=len(alerts),
        grouped_by_account=group_by_account(alerts) if body.group_by_account else None,
        latency_ms=latency_ms,
        viewed_as=user,
        dataset_snapshot=clock.now(),
    )


@router.get("/api/radar/alerts/{alert_id}", response_model=AlertCandidate)
def get_alert(
    alert_id: str,
    user: DemoUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: SnapshotClock = Depends(get_clock),
    registry: PolicyRegistry = Depends(get_policy_registry),
) -> AlertCandidate:
    overrides, defaults = registry
    try:
        alerts = run_operations_radar(
            conn, user.to_auth_context(), clock, overrides=overrides, defaults=defaults
        )
    except NotAuthorizedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    for alert in alerts:
        if alert.alert_id == alert_id:
            return alert
    raise HTTPException(status_code=404, detail=f"alert {alert_id} not found or not authorized")
