"""Deterministic first-response SLA deadline computation.

docs/architecture_decision_record.md ADR-007/ADR-008: only 24x7 targets are
exactly computable - a target requiring a business calendar returns
trust_state=CONDITIONAL with no numeric deadline, because the source pack
never defines business hours (gap G1). And because the workbook has no
first_response_at column, a "breach" here means "elapsed past the deadline
with no recorded response", never a confirmed missed response - that
distinction is stated in every breached reason string, not just in a code
comment.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta

from pydantic import BaseModel, ConfigDict

from app.authorization.context import AuthContext
from app.domain.evidence import cite_document, cite_structured
from app.domain.outcomes import Conflict, DecisionResult, TrustState
from app.domain.severity import classify_severity
from app.models.enums import Severity
from app.models.structured import Account
from app.policy.applicability import ClauseTopic, resolve_applicability
from app.structured_data.repository import get_account, get_ticket
from app.time.clock import SnapshotClock, tz_of


class SlaOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    severity: Severity
    applicable_source_id: str
    target_text: str
    target_minutes: int | None
    is_24x7: bool
    deadline: str | None
    elapsed_minutes_past_deadline: float | None
    breached: bool | None  # None when not computable (requires a business calendar)


def _lookup_sla_target(
    conn: sqlite3.Connection, source_id: str, account: Account, severity: Severity
) -> sqlite3.Row | None:
    """An account-specific row always wins over a plan-level default row for
    the same source_id. Without this ORDER BY, "which row wins" would depend
    on SQLite's query-planner choice of scan path for the OR clause - which
    happens to already favor the account-specific row on the current
    sla_targets unique index, but that is an incidental property of one
    index's column order, not a guarantee. Made explicit so the precedence
    holds regardless of the planner's choice, the SQLite version, or a
    future schema/index change - and is directly tested rather than assumed.
    In today's real data this is unreachable (a source_id is either wholly
    plan-scoped or wholly account-scoped, so at most one row can ever
    match); the test constructs the ambiguity synthetically.
    """
    return conn.execute(
        "SELECT * FROM sla_targets WHERE source_id = ? AND severity = ? "
        "AND (plan = ? OR account_id = ?) "
        "ORDER BY (account_id IS NOT NULL) DESC LIMIT 1",
        (source_id, severity.value, account.plan, account.account_id),
    ).fetchone()


def calculate_sla(
    conn: sqlite3.Connection, ticket_id: str, auth: AuthContext, clock: SnapshotClock
) -> DecisionResult[SlaOutcome]:
    snapshot = clock.now()
    ticket = get_ticket(conn, ticket_id, auth, tz_of(clock))
    account = get_account(conn, ticket.account_id, auth)
    ticket_evidence = cite_structured("tickets", ticket.ticket_id)

    severity_result = classify_severity(ticket, conn)
    if severity_result.result is None or severity_result.result.severity is None:
        return DecisionResult(
            result=None,
            trust_state=TrustState.UNCERTAIN,
            reason=f"Cannot compute an SLA target: {severity_result.reason}",
            evidence=[ticket_evidence, *severity_result.evidence],
            needs_human_review=True,
        )
    severity = severity_result.result.severity

    applicability = resolve_applicability(
        conn, ClauseTopic.SLA_FIRST_RESPONSE, account.account_id, snapshot.date()
    )
    target = _lookup_sla_target(conn, applicability.winning_source_id, account, severity)
    if target is None:
        return DecisionResult(
            result=None,
            trust_state=TrustState.UNCERTAIN,
            reason=(
                f"No SLA target found for {applicability.winning_source_id} / "
                f"{account.plan} / {severity.value}."
            ),
            evidence=[ticket_evidence],
            needs_human_review=True,
        )

    conflicts = []
    if applicability.overridden_source_id:
        conflicts.append(
            Conflict(
                winner_source_id=applicability.winning_source_id,
                loser_source_id=applicability.overridden_source_id,
                scope=account.account_id,
                reason=applicability.reason,
                needs_human_review=applicability.needs_human_review,
            )
        )
    evidence = [
        ticket_evidence,
        *severity_result.evidence,
        cite_document(conn, applicability.winning_source_id, applicability.winning_section),
    ]

    if target["requires_business_calendar"]:
        outcome = SlaOutcome(
            severity=severity, applicable_source_id=applicability.winning_source_id,
            target_text=target["target_text"], target_minutes=None, is_24x7=False,
            deadline=None, elapsed_minutes_past_deadline=None, breached=None,
        )
        return DecisionResult(
            result=outcome,
            trust_state=TrustState.CONDITIONAL,
            reason=(
                f'Target is "{target["target_text"]}"; the source pack never defines a business '
                "calendar (gap G1), so an exact deadline cannot be computed."
            ),
            evidence=evidence,
            assumptions=[
                "business-hour/business-day SLA targets are not computable without a "
                "defined business calendar"
            ],
            conflicts=conflicts,
            needs_human_review=applicability.needs_human_review,
        )

    target_minutes = target["target_minutes"]
    deadline = ticket.created_at + timedelta(minutes=target_minutes)
    elapsed = (snapshot - deadline).total_seconds() / 60
    breached = elapsed > 0

    reason = f'Target "{target["target_text"]}" -> deadline {deadline.isoformat()}. '
    if breached:
        reason += (
            f"Elapsed {elapsed:.0f} minutes past deadline with no recorded response "
            "(the workbook has no first_response_at column, so this is elapsed-time-past-"
            "deadline, not a confirmed missed response)."
        )
    else:
        reason += f"{-elapsed:.0f} minutes remain."
    if breached and severity is Severity.P1:
        reason += " Support Policy v3 s4: P1 breaches should be escalated immediately."

    outcome = SlaOutcome(
        severity=severity, applicable_source_id=applicability.winning_source_id,
        target_text=target["target_text"], target_minutes=target_minutes,
        is_24x7=bool(target["is_24x7"]),
        deadline=deadline.isoformat(), elapsed_minutes_past_deadline=elapsed, breached=breached,
    )
    return DecisionResult(
        result=outcome,
        trust_state=TrustState.CONFIDENT,
        reason=reason,
        evidence=evidence,
        calculation_inputs={
            "created_at": ticket.created_at.isoformat(),
            "target_minutes": target_minutes,
        },
        conflicts=conflicts,
        needs_human_review=(
            applicability.needs_human_review or (breached and severity is Severity.P1)
        ),
    )
