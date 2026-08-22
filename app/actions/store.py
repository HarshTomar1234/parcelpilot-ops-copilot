"""SQLite-backed persistence for the actions audit trail (Phase 4 s8). The
`actions` table (app/db/schema.sql) IS the audit log - insert_action()
writes the initial PENDING_CONFIRMATION row, save_action_if_status()
overwrites it in place on every state transition, so there is exactly one
row per action_id whose current fields always reflect its real current
state, and whose history is fully reconstructable from
prepared_at/confirmed_at/executed_at. Every state transition after insert
is an atomic conditional UPDATE (WHERE status = expected), not a
read-then-write, so concurrent callers can never both "win" the same
transition (see save_action_if_status's docstring).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from app.actions.models import ActionRecord, ActionStatus, ActionType
from app.domain.outcomes import EvidenceRef


def _row_to_record(row: sqlite3.Row) -> ActionRecord:
    return ActionRecord(
        action_id=row["action_id"],
        request_id=row["request_id"],
        user_id=row["user_id"],
        action_type=ActionType(row["action_type"]),
        target=row["target"],
        proposed_change=json.loads(row["proposed_change"]),
        reason=row["reason"],
        evidence=[EvidenceRef(**e) for e in json.loads(row["evidence"])],
        risk=row["risk"],
        payload_hash=row["payload_hash"],
        status=ActionStatus(row["status"]),
        prepared_at=datetime.fromisoformat(row["prepared_at"]),
        expires_at=datetime.fromisoformat(row["expires_at"]),
        confirmed_at=datetime.fromisoformat(row["confirmed_at"]) if row["confirmed_at"] else None,
        executed_at=datetime.fromisoformat(row["executed_at"]) if row["executed_at"] else None,
        idempotency_key=row["idempotency_key"],
        failure_reason=row["failure_reason"],
    )


def insert_action(conn: sqlite3.Connection, record: ActionRecord) -> None:
    conn.execute(
        "INSERT INTO actions (action_id, request_id, user_id, action_type, target, "
        "proposed_change, reason, evidence, risk, payload_hash, status, prepared_at, "
        "expires_at, confirmed_at, executed_at, idempotency_key, failure_reason) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            record.action_id, record.request_id, record.user_id, record.action_type.value,
            record.target, json.dumps(record.proposed_change), record.reason,
            json.dumps([e.model_dump(mode="json") for e in record.evidence]), record.risk,
            record.payload_hash, record.status.value, record.prepared_at.isoformat(),
            record.expires_at.isoformat(),
            record.confirmed_at.isoformat() if record.confirmed_at else None,
            record.executed_at.isoformat() if record.executed_at else None,
            record.idempotency_key, record.failure_reason,
        ),
    )
    conn.commit()


def save_action_if_status(
    conn: sqlite3.Connection, record: ActionRecord, expected_status: ActionStatus
) -> bool:
    """Atomic compare-and-swap: the WHERE clause re-checks status = expected
    inside the same UPDATE statement, so the check and the write are one
    SQL operation - not a separate read-then-write. Closes a real race
    found via a red-team concurrency test (Phase "final red team"):
    app/actions/workflow.py previously did a Python-level `if status ==
    ...` check followed by an unconditional save_action(), so N
    concurrent confirm_action (or execute_action) calls against the same
    row could all read the pre-transition status before any of their
    writes landed, and all report success - a live test measured 4/20
    concurrent confirm_action calls on one PENDING_CONFIRMATION action
    each returning success=True. Returns True iff this call's write is
    the one that actually landed (rowcount == 1); False means another
    concurrent caller won the race first - the caller must re-read the
    record and report the real current state, never assume success."""
    cursor = conn.execute(
        "UPDATE actions SET status = ?, confirmed_at = ?, executed_at = ?, failure_reason = ? "
        "WHERE action_id = ? AND status = ?",
        (
            record.status.value,
            record.confirmed_at.isoformat() if record.confirmed_at else None,
            record.executed_at.isoformat() if record.executed_at else None,
            record.failure_reason,
            record.action_id,
            expected_status.value,
        ),
    )
    conn.commit()
    return cursor.rowcount == 1


def get_action(conn: sqlite3.Connection, action_id: str) -> ActionRecord | None:
    row = conn.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,)).fetchone()
    return _row_to_record(row) if row else None
