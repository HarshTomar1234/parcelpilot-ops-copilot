"""Core prepare/confirm/execute mechanics (Phase 4 s6-8). Every fact
asserted here was verified by actually running the workflow against the
fixture DB first - see app/actions/workflow.py.
"""

from __future__ import annotations

from app.actions.models import ActionStatus
from app.actions.store import get_action
from app.actions.workflow import confirm_action, execute_action, prepare_escalation
from app.authorization.context import INTERNAL_SYSTEM_CONTEXT
from tests.fixtures.seed_fixture_db import FIXTURE_AGREEMENT_OVERRIDES, FIXTURE_DEFAULT_SOURCE

_REGISTRY = {"overrides": FIXTURE_AGREEMENT_OVERRIDES, "defaults": FIXTURE_DEFAULT_SOURCE}


def test_prepare_escalation_succeeds_for_a_p1_breach(conn, clock):
    outcome = prepare_escalation(
        conn, "FXT-501", "P1 breach found via SLA check",
        INTERNAL_SYSTEM_CONTEXT, clock, "user-1", "req-1", **_REGISTRY,
    )
    assert outcome.success
    assert outcome.record is not None
    assert outcome.record.status is ActionStatus.PENDING_CONFIRMATION
    assert outcome.record.proposed_change["severity"] == "P1"
    assert outcome.record.proposed_change["sla_breached"] is True
    assert outcome.record.risk == "high"
    assert outcome.record.evidence  # real EvidenceRefs, not an empty list


def test_prepare_escalation_rejects_a_non_eligible_ticket(conn, clock):
    # FXT-502 is P2, not SLA-breached (business-hour target, conditional).
    outcome = prepare_escalation(
        conn, "FXT-502", "test", INTERNAL_SYSTEM_CONTEXT, clock, "u1", "r1", **_REGISTRY,
    )
    assert not outcome.success
    assert outcome.error_code == "not_escalation_eligible"


def test_prepare_escalation_rejects_a_closed_ticket(conn, clock):
    outcome = prepare_escalation(
        conn, "FXT-450", "test", INTERNAL_SYSTEM_CONTEXT, clock, "u1", "r1", **_REGISTRY,
    )
    assert not outcome.success
    assert outcome.error_code == "invalid_target_state"


def test_full_happy_path_prepare_confirm_execute(conn, clock):
    prepared = prepare_escalation(
        conn, "FXT-501", "P1 breach", INTERNAL_SYSTEM_CONTEXT, clock, "u1", "r1", **_REGISTRY,
    )
    assert prepared.record is not None
    action_id = prepared.record.action_id
    payload_hash = prepared.record.payload_hash

    confirmed = confirm_action(
        conn, action_id, payload_hash, INTERNAL_SYSTEM_CONTEXT, clock, "u1"
    )
    assert confirmed.success
    assert confirmed.record is not None
    assert confirmed.record.status is ActionStatus.CONFIRMED
    assert confirmed.record.confirmed_at is not None

    executed = execute_action(conn, action_id, clock)
    assert executed.success
    assert executed.record is not None
    assert executed.record.status is ActionStatus.EXECUTED
    assert executed.record.executed_at is not None

    # The actions table is the audit trail - verify the persisted row
    # directly, not just the in-memory return value.
    stored = get_action(conn, action_id)
    assert stored is not None
    assert stored.status is ActionStatus.EXECUTED
    assert stored.prepared_at == prepared.record.prepared_at
    assert stored.confirmed_at == confirmed.record.confirmed_at
    assert stored.executed_at == executed.record.executed_at


def test_execute_is_idempotent(conn, clock):
    prepared = prepare_escalation(
        conn, "FXT-501", "test", INTERNAL_SYSTEM_CONTEXT, clock, "u1", "r1", **_REGISTRY,
    )
    assert prepared.record is not None
    confirm_action(
        conn, prepared.record.action_id, prepared.record.payload_hash,
        INTERNAL_SYSTEM_CONTEXT, clock, "u1",
    )
    first = execute_action(conn, prepared.record.action_id, clock)
    second = execute_action(conn, prepared.record.action_id, clock)

    assert first.success and second.success
    assert first.record is not None
    assert second.record is not None
    assert first.record.executed_at == second.record.executed_at  # not re-executed
