"""POST /api/actions/{prepare,confirm,execute}, GET /api/actions/{id}
(Phase 6 s11-12). Every route calls straight into app/actions/workflow.py
- prepare/confirm/execute, three separate calls, exactly as designed in
Phase 4. There is no POST /execute that skips confirmation: execute_action
only ever succeeds against a CONFIRMED record, and confirm_action only
ever succeeds against a PENDING_CONFIRMATION one prepared by the same
user - both already enforced inside app/actions/workflow.py.

execute_action() itself takes no auth/user_id (Phase 4 design: it is the
final, already-gated step of a flow confirm_action has already locked to
one user). The ownership check below is the one piece of hardening this
phase adds at the API boundary specifically because execute is now a
reachable HTTP endpoint: only the user who prepared the action (or an
operations_admin) may call execute or read it back.

GET /api/actions/{id} normalizes a non-owner's denial to 404, same as a
truly unknown ID (final release hardening, finding F5) - enumeration
cannot distinguish "never existed" from "exists but isn't yours" through
this endpoint. POST /api/actions/execute keeps a distinct 403 for a
non-owner: unlike a passive GET, the caller reaching execute already has
the action_id from their own prepare/confirm flow, so a mutating-action
denial being explicit is more useful than it is revealing.
"""

from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.actions.models import ActionOutcome
from app.actions.store import get_action
from app.actions.workflow import confirm_action, execute_action, prepare_escalation
from app.api.demo_users import DemoUser
from app.api.deps import (
    PolicyRegistry,
    get_clock,
    get_conn,
    get_current_user,
    get_policy_registry,
    get_request_context,
)
from app.api.schemas import (
    ActionResponse,
    ConfirmActionRequest,
    ExecuteActionRequest,
    PrepareEscalationRequest,
)
from app.authorization.context import Role
from app.observability.tracing import RequestContext
from app.time.clock import SnapshotClock

router = APIRouter(tags=["actions"])
logger = logging.getLogger("api.actions")


def _require_owner_or_admin(conn: sqlite3.Connection, action_id: str, user: DemoUser) -> None:
    record = get_action(conn, action_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"no action {action_id}")
    if user.role is not Role.OPERATIONS_ADMIN and record.user_id != user.id:
        raise HTTPException(status_code=403, detail="not authorized to access this action")


def _get_owned_action_or_404(
    conn: sqlite3.Connection, action_id: str, user: DemoUser
) -> ActionOutcome:
    """A non-owner and a nonexistent action_id are indistinguishable
    here - both a plain 404 with the same generic detail message, so a
    caller who already knows/guesses an action_id can't use this
    endpoint to confirm another user's action exists."""
    record = get_action(conn, action_id)
    if record is None or (user.role is not Role.OPERATIONS_ADMIN and record.user_id != user.id):
        raise HTTPException(status_code=404, detail=f"no action {action_id}")
    return ActionOutcome(success=True, record=record)


@router.post("/api/actions/prepare", response_model=ActionResponse)
def prepare(
    body: PrepareEscalationRequest,
    user: DemoUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: SnapshotClock = Depends(get_clock),
    request_context: RequestContext = Depends(get_request_context),
    registry: PolicyRegistry = Depends(get_policy_registry),
) -> ActionResponse:
    overrides, defaults = registry
    outcome = prepare_escalation(
        conn, body.ticket_id, body.reason, user.to_auth_context(), clock,
        user.id, request_context.request_id, overrides=overrides, defaults=defaults,
    )
    logger.info(
        "action_prepared",
        extra={
            "demo_user": user.id, "target": body.ticket_id, "success": outcome.success,
            "error_code": outcome.error_code,
        },
    )
    return ActionResponse(outcome=outcome, viewed_as=user)


@router.post("/api/actions/confirm", response_model=ActionResponse)
def confirm(
    body: ConfirmActionRequest,
    user: DemoUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: SnapshotClock = Depends(get_clock),
) -> ActionResponse:
    outcome = confirm_action(
        conn, body.action_id, body.payload_hash, user.to_auth_context(), clock, user.id
    )
    logger.info(
        "action_confirmed",
        extra={
            "demo_user": user.id, "action_id": body.action_id, "success": outcome.success,
            "error_code": outcome.error_code,
        },
    )
    return ActionResponse(outcome=outcome, viewed_as=user)


@router.post("/api/actions/execute", response_model=ActionResponse)
def execute(
    body: ExecuteActionRequest,
    user: DemoUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: SnapshotClock = Depends(get_clock),
) -> ActionResponse:
    _require_owner_or_admin(conn, body.action_id, user)
    outcome = execute_action(conn, body.action_id, clock)
    logger.info(
        "action_executed",
        extra={
            "demo_user": user.id, "action_id": body.action_id, "success": outcome.success,
            "error_code": outcome.error_code,
        },
    )
    return ActionResponse(outcome=outcome, viewed_as=user)


@router.get("/api/actions/{action_id}", response_model=ActionResponse)
def get_action_route(
    action_id: str,
    user: DemoUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
) -> ActionResponse:
    outcome = _get_owned_action_or_404(conn, action_id, user)
    return ActionResponse(outcome=outcome, viewed_as=user)
