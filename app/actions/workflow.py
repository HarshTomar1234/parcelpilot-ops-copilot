"""State-changing action workflow (Phase 4 s6-10). prepare_action only
ever proposes - it is read-only against orders/tickets/accounts, the only
write it makes is inserting its own PENDING_CONFIRMATION audit row.
confirm_action validates and locks in the exact proposal that was
prepared. execute_action performs the (mocked) external effect exactly
once. The agent may recommend/prepare an action; nothing between prepare
and execute happens without a separate, explicit confirm_action call -
this module has no function an LLM's text output can reach on its own,
and app/agent/orchestrator.py never imports confirm_action or
execute_action at all (see Phase 4 s10 / tests/fixture_backed/
test_action_security.py).

Only one action type is implemented (prepare_escalation) per the "do not
invent a large workflow engine" instruction - prepare_ticket_update was
explicitly optional and is not built this phase.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import timedelta

from app.actions.models import ActionOutcome, ActionRecord, ActionStatus, ActionType
from app.actions.store import get_action, insert_action, save_action_if_status
from app.authorization.context import AuthContext
from app.domain.evidence import cite_structured
from app.domain.sla import calculate_sla
from app.errors import NotAuthorizedError, UnknownEntityError
from app.models.enums import Severity, TicketStatus
from app.policy.applicability import (
    AGREEMENT_OVERRIDES,
    DEFAULT_SOURCE,
    AgreementOverride,
    ClauseTopic,
)
from app.structured_data.repository import get_ticket
from app.time.clock import SnapshotClock, tz_of

ACTION_EXPIRY_MINUTES = 15


def _payload_hash(action_type: ActionType, target: str, proposed_change: dict) -> str:
    payload = json.dumps(
        {"action_type": action_type.value, "target": target, "proposed_change": proposed_change},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def prepare_escalation(
    conn: sqlite3.Connection,
    ticket_id: str,
    reason: str,
    auth: AuthContext,
    clock: SnapshotClock,
    user_id: str,
    request_id: str,
    *,
    overrides: tuple[AgreementOverride, ...] = AGREEMENT_OVERRIDES,
    defaults: dict[ClauseTopic, tuple[str, str] | None] = DEFAULT_SOURCE,
) -> ActionOutcome:
    """Non-mutating: validates authorization, target existence, current
    state, and a deterministic escalation-eligibility rule (P1 or SLA-
    breached - never an LLM judgment call), then writes exactly one
    PENDING_CONFIRMATION row. Never touches the tickets table itself."""
    try:
        ticket = get_ticket(conn, ticket_id, auth, tz_of(clock))
    except NotAuthorizedError as exc:
        return ActionOutcome(success=False, error_code="not_authorized", error_message=str(exc))
    except UnknownEntityError as exc:
        return ActionOutcome(success=False, error_code="not_found", error_message=str(exc))

    if ticket.status is not TicketStatus.OPEN:
        return ActionOutcome(
            success=False, error_code="invalid_target_state",
            error_message=(
                f"ticket {ticket_id} is {ticket.status.value}, not open - nothing to escalate"
            ),
        )

    sla_result = calculate_sla(conn, ticket_id, auth, clock, overrides=overrides, defaults=defaults)
    severity = sla_result.result.severity if sla_result.result else None
    breached = sla_result.result.breached if sla_result.result else None
    if severity is None:
        return ActionOutcome(
            success=False, error_code="cannot_determine_eligibility",
            error_message=(
                f"severity for {ticket_id} could not be determined confidently enough "
                "to justify escalation"
            ),
        )
    if severity is not Severity.P1 and not breached:
        return ActionOutcome(
            success=False, error_code="not_escalation_eligible",
            error_message=(
                f"{ticket_id} is {severity.value} and not SLA-breached - does not meet "
                "the deterministic escalation bar (P1 or breached)"
            ),
        )

    proposed_change = {
        "new_priority": "escalated",
        "previous_status": ticket.status.value,
        "severity": severity.value,
        "sla_breached": bool(breached),
    }
    evidence = [cite_structured("tickets", ticket_id), *sla_result.evidence]
    risk = "high" if severity is Severity.P1 else "medium"
    payload_hash = _payload_hash(ActionType.PREPARE_ESCALATION, ticket_id, proposed_change)
    now = clock.now()
    action_id = f"ACT-{uuid.uuid4().hex[:12]}"

    record = ActionRecord(
        action_id=action_id, request_id=request_id, user_id=user_id,
        action_type=ActionType.PREPARE_ESCALATION, target=ticket_id,
        proposed_change=proposed_change, reason=reason, evidence=evidence, risk=risk,
        payload_hash=payload_hash, status=ActionStatus.PENDING_CONFIRMATION,
        prepared_at=now, expires_at=now + timedelta(minutes=ACTION_EXPIRY_MINUTES),
        idempotency_key=action_id,
    )
    insert_action(conn, record)
    return ActionOutcome(success=True, record=record)


def confirm_action(
    conn: sqlite3.Connection,
    action_id: str,
    payload_hash: str,
    auth: AuthContext,
    clock: SnapshotClock,
    user_id: str,
) -> ActionOutcome:
    """Validates: same authorized user, action not already confirmed/
    executed/cancelled, not expired, the caller's payload hash matches
    exactly what was prepared (catches a manipulated payload), and the
    target's state has not changed since prepare - re-checking
    authorization against the CURRENT caller's auth, never the original
    preparer's, so a caller whose access has since narrowed cannot
    confirm an action outside their current scope."""
    record = get_action(conn, action_id)
    if record is None:
        return ActionOutcome(
            success=False, error_code="not_found", error_message=f"no action {action_id}"
        )

    if record.status is not ActionStatus.PENDING_CONFIRMATION:
        return ActionOutcome(
            success=False, record=record, error_code="wrong_state",
            error_message=(
                f"action {action_id} is {record.status.value}, not PENDING_CONFIRMATION - "
                "cannot confirm"
            ),
        )

    now = clock.now()
    if now > record.expires_at:
        expired = record.model_copy(
            update={"status": ActionStatus.EXPIRED, "failure_reason": "confirmation window expired"}
        )
        if not save_action_if_status(conn, expired, ActionStatus.PENDING_CONFIRMATION):
            # A concurrent caller already transitioned this row - report
            # its real current state rather than the stale one this call
            # read, never a stale "expired" result for a row that has
            # actually moved on.
            return _wrong_state_outcome(conn, action_id, "confirm")
        return ActionOutcome(
            success=False, record=expired, error_code="expired",
            error_message="action expired before confirmation",
        )

    if record.user_id != user_id:
        return ActionOutcome(
            success=False, record=record, error_code="wrong_user",
            error_message="only the user who prepared this action may confirm it",
        )

    if payload_hash != record.payload_hash:
        return ActionOutcome(
            success=False, record=record, error_code="payload_mismatch",
            error_message="the confirmed payload does not match what was prepared - refusing",
        )

    try:
        ticket = get_ticket(conn, record.target, auth, tz_of(clock))
    except NotAuthorizedError as exc:
        return ActionOutcome(
            success=False, record=record, error_code="not_authorized", error_message=str(exc)
        )
    except UnknownEntityError as exc:
        return ActionOutcome(
            success=False, record=record, error_code="target_invalid", error_message=str(exc)
        )
    if ticket.status.value != record.proposed_change["previous_status"]:
        return ActionOutcome(
            success=False, record=record, error_code="target_state_changed",
            error_message=f"ticket {record.target}'s status changed since this action was prepared",
        )

    confirmed = record.model_copy(update={"status": ActionStatus.CONFIRMED, "confirmed_at": now})
    if not save_action_if_status(conn, confirmed, ActionStatus.PENDING_CONFIRMATION):
        # Lost a race against another concurrent confirm_action call on
        # the same action_id - report the real state, never a false
        # success (see save_action_if_status's docstring for the
        # concurrency test that found this).
        return _wrong_state_outcome(conn, action_id, "confirm")
    return ActionOutcome(success=True, record=confirmed)


def _wrong_state_outcome(conn: sqlite3.Connection, action_id: str, verb: str) -> ActionOutcome:
    current = get_action(conn, action_id)
    assert current is not None  # the row existed moments ago in the same call
    return ActionOutcome(
        success=False, record=current, error_code="wrong_state",
        error_message=(
            f"action {action_id} is {current.status.value} - cannot {verb} "
            "(a concurrent request already changed its state)"
        ),
    )


def execute_action(conn: sqlite3.Connection, action_id: str, clock: SnapshotClock) -> ActionOutcome:
    """Only proceeds from CONFIRMED. Idempotent: calling this again on an
    already-EXECUTED action returns the same record without repeating the
    (mocked) effect - executing the same action twice never duplicates
    it, including under real concurrency (the state transition itself is
    an atomic conditional UPDATE, not a read-then-write - see
    save_action_if_status). The external effect itself is mocked: this
    never claims a real external system call was made, only that the
    audit row was updated."""
    record = get_action(conn, action_id)
    if record is None:
        return ActionOutcome(
            success=False, error_code="not_found", error_message=f"no action {action_id}"
        )

    if record.status is ActionStatus.EXECUTED:
        return ActionOutcome(success=True, record=record)  # idempotent no-op

    if record.status is not ActionStatus.CONFIRMED:
        return ActionOutcome(
            success=False, record=record, error_code="wrong_state",
            error_message=f"action {action_id} is {record.status.value}, not CONFIRMED",
        )

    executed = record.model_copy(
        update={"status": ActionStatus.EXECUTED, "executed_at": clock.now()}
    )
    if not save_action_if_status(conn, executed, ActionStatus.CONFIRMED):
        # Another concurrent execute_action call won the CAS race and
        # already transitioned this row to EXECUTED (the only other
        # state this UPDATE's WHERE clause could have missed against,
        # since CONFIRMED->EXECUTED is the only transition this function
        # ever performs) - re-read and return that real, already-executed
        # record so this call is idempotent-safe rather than falsely
        # reporting success for an effect it never actually triggered.
        current = get_action(conn, action_id)
        assert current is not None
        return ActionOutcome(success=True, record=current)
    return ActionOutcome(success=True, record=executed)
