"""Typed models for the state-changing action workflow (Phase 4 s6-8).
Two phases, three calls: prepare_action() proposes (never mutates),
confirm_action() validates and locks in the proposal, execute_action()
performs the (mocked) external effect exactly once. ActionRecord is both
the in-memory result type and the shape persisted to the actions table -
one row per action_id, updated in place as it moves through its states,
so the table itself is the audit trail (app/actions/store.py).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.domain.outcomes import EvidenceRef


class ActionType(StrEnum):
    PREPARE_ESCALATION = "prepare_escalation"


class ActionStatus(StrEnum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ActionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_id: str
    request_id: str
    user_id: str
    action_type: ActionType
    target: str
    proposed_change: dict[str, object]
    reason: str
    evidence: list[EvidenceRef]
    risk: str
    payload_hash: str
    status: ActionStatus
    prepared_at: datetime
    expires_at: datetime
    confirmed_at: datetime | None = None
    executed_at: datetime | None = None
    idempotency_key: str
    failure_reason: str | None = None


class ActionOutcome(BaseModel):
    """The uniform return type for prepare/confirm/execute - never a raw
    exception for an expected business failure (unauthorized, expired, a
    manipulated payload, ...). success=False always carries an
    error_code/error_message; record is populated whenever one exists,
    even on failure, so a caller can see what state it's actually in."""

    model_config = ConfigDict(frozen=True)

    success: bool
    record: ActionRecord | None = None
    error_code: str | None = None
    error_message: str | None = None
