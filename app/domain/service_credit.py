"""Deterministic failed-pickup service-credit decisions.

docs/initial_rules.md R3: eligibility requires carrier_fault AND NOT
customer_fault AND delay past the applicable threshold. SOP s3 forbids
promising a credit when fault or timing is unknown - the workbook models
fault as two plain booleans with no explicit "unknown" state
(docs/data_dictionary.md), so a non-eligible boolean combination is reported
as a confident denial, not silently treated as "fault unknown, escalate".
That is a data-model limitation worth restating in `reason`, not a case to
manufacture uncertainty for.

ADR-006: when pickup_actual_at is null the delay is measured from the
snapshot and is still accruing - that is always surfaced as an assumption.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.authorization.context import AuthContext
from app.domain.evidence import cite_document, cite_structured
from app.domain.outcomes import Conflict, DecisionResult, TrustState, trust_from
from app.models.structured import Order
from app.policy.applicability import ClauseTopic, resolve_applicability
from app.structured_data.repository import get_order
from app.time.clock import SnapshotClock, tz_of

_MANAGER_APPROVAL_THRESHOLD_INR = 1000.0


class ServiceCreditOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    eligible: bool
    credit_inr: float | None
    applicable_rule: str
    delay_hours: float | None
    delay_reference: Literal["pickup_actual_at", "snapshot"] | None
    manager_approval_required: bool


def _default_sop_credit(order: Order, delay_hours: float) -> tuple[bool, float | None, str]:
    if delay_hours <= 2:
        return False, None, (
            "delay is <= 2 hours; default SOP's 2-hour threshold is not met (SOP s2)"
        )
    credit = min(500.0, 0.10 * order.shipment_fee_inr)
    return True, credit, (
        "delay > 2 hours with carrier fault and no customer fault (SOP s2 default formula)"
    )


def _lumenworks_credit(order: Order, delay_hours: float) -> tuple[bool, float | None, str]:
    if delay_hours <= 4:
        return False, None, (
            "delay is <= 4 hours; LumenWorks' agreement threshold (SRC-06 s3) is not met"
        )
    return True, 300.0, (
        "delay > 4 hours with carrier fault and no customer fault "
        "(LumenWorks' fixed INR 300, SRC-06 s3)"
    )


_CREDIT_RULES: dict[str, Callable[[Order, float], tuple[bool, float | None, str]]] = {
    "SRC-03": _default_sop_credit,
    "SRC-06": _lumenworks_credit,
}


def evaluate_service_credit(
    conn: sqlite3.Connection, order_id: str, auth: AuthContext, clock: SnapshotClock
) -> DecisionResult[ServiceCreditOutcome]:
    snapshot = clock.now()
    order = get_order(conn, order_id, auth, tz_of(clock))
    order_evidence = cite_structured("orders", order.order_id)

    if not order.carrier_fault or order.customer_fault:
        reason = (
            "carrier_fault is False" if not order.carrier_fault else "customer_fault is True"
        )
        return DecisionResult(
            result=ServiceCreditOutcome(
                eligible=False, credit_inr=None, applicable_rule="SRC-03#2",
                delay_hours=None, delay_reference=None, manager_approval_required=False,
            ),
            trust_state=TrustState.CONFIDENT,
            reason=(
                f"Not eligible: {reason}. "
                "SOP s2 requires carrier fault and no customer-caused issue."
            ),
            evidence=[order_evidence, cite_document(conn, "SRC-03", "2")],
            calculation_inputs={
                "carrier_fault": order.carrier_fault,
                "customer_fault": order.customer_fault,
            },
        )

    reference_dt = order.pickup_actual_at or snapshot
    delay_reference: Literal["pickup_actual_at", "snapshot"] = (
        "pickup_actual_at" if order.pickup_actual_at else "snapshot"
    )
    delay_hours = (reference_dt - order.pickup_window_end).total_seconds() / 3600

    assumptions = []
    if order.pickup_actual_at is None:
        assumptions.append(
            "pickup_actual_at is null; delay is measured from the dataset snapshot and is "
            "still accruing (ADR-006) - this is not a final delay figure"
        )

    applicability = resolve_applicability(
        conn, ClauseTopic.SERVICE_CREDIT_THRESHOLD_AND_AMOUNT, order.account_id, snapshot.date()
    )
    rule_fn = _CREDIT_RULES[applicability.winning_source_id]
    eligible, credit, note = rule_fn(order, delay_hours)

    manager_approval = credit is not None and credit > _MANAGER_APPROVAL_THRESHOLD_INR
    review_required = applicability.needs_human_review or manager_approval

    conflicts = []
    if applicability.overridden_source_id:
        conflicts.append(
            Conflict(
                winner_source_id=applicability.winning_source_id,
                loser_source_id=applicability.overridden_source_id,
                scope=order.account_id,
                reason=applicability.reason,
                needs_human_review=applicability.needs_human_review,
            )
        )

    return DecisionResult(
        result=ServiceCreditOutcome(
            eligible=eligible, credit_inr=credit,
            applicable_rule=f"{applicability.winning_source_id}#{applicability.winning_section}",
            delay_hours=delay_hours, delay_reference=delay_reference,
            manager_approval_required=manager_approval,
        ),
        trust_state=trust_from(
            review_required=review_required, has_assumptions=bool(assumptions)
        ),
        reason=f"{note}. {applicability.reason}" + (
            " Requires manager approval (SOP s3: individual credits above INR 1,000)."
            if manager_approval
            else ""
        ),
        evidence=[
            order_evidence,
            cite_document(conn, applicability.winning_source_id, applicability.winning_section),
        ],
        assumptions=assumptions,
        calculation_inputs={
            "delay_hours": delay_hours,
            "shipment_fee_inr": order.shipment_fee_inr,
            "carrier_fault": order.carrier_fault,
            "customer_fault": order.customer_fault,
        },
        conflicts=conflicts,
        needs_human_review=review_required,
    )
