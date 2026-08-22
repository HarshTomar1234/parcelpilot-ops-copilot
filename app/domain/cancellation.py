"""Deterministic cancellation-fee decisions.

docs/initial_rules.md R2: the SOP's per-status branches (DRAFT/BOOKED/
PICKED_UP/DELIVERED) drive the decision; a winning agreement only changes
the *fee calculation on the BOOKED branch* (R2.1) - it never extends past
pickup, never changes DELIVERED, never changes DRAFT. That is why the
per-status branches are handled directly here and only the BOOKED-and-
requested fee math is delegated to policy.applicability.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.authorization.context import AuthContext
from app.domain.evidence import cite_document, cite_structured
from app.domain.outcomes import Conflict, DecisionResult, TrustState, trust_from
from app.models.enums import OrderStatus
from app.models.structured import Order
from app.policy.applicability import ClauseTopic, resolve_applicability
from app.structured_data.repository import get_order
from app.time.clock import SnapshotClock, tz_of


class CancellationOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: Literal["can_cancel", "cannot_cancel", "no_action_needed"]
    fee_inr: float | None
    applicable_rule: str
    order_status: OrderStatus
    minutes_since_booking: float | None


def _default_sop_fee(order: Order, minutes: float) -> tuple[float, str]:
    if minutes <= 30:
        return 0.0, "within 30 minutes of booking, no fee applies (SOP s1)"
    return 250.0, "more than 30 minutes after booking, INR 250 fee applies (SOP s1)"


def _northstar_waiver_fee(order: Order, minutes: float) -> tuple[float, str]:
    return 0.0, (
        "Northstar's agreement waives the cancellation fee regardless of "
        "elapsed time (SRC-05 s2)"
    )


_FEE_RULES: dict[str, Callable[[Order, float], tuple[float, str]]] = {
    "SRC-03": _default_sop_fee,
    "SRC-05": _northstar_waiver_fee,
}


def evaluate_cancellation(
    conn: sqlite3.Connection, order_id: str, auth: AuthContext, clock: SnapshotClock
) -> DecisionResult[CancellationOutcome]:
    snapshot = clock.now()
    order = get_order(conn, order_id, auth, tz_of(clock))
    order_evidence = cite_structured("orders", order.order_id)

    if order.status is OrderStatus.DELIVERED:
        return DecisionResult(
            result=CancellationOutcome(
                decision="cannot_cancel", fee_inr=None, applicable_rule="SRC-03#1",
                order_status=order.status, minutes_since_booking=None,
            ),
            trust_state=TrustState.CONFIDENT,
            reason="Order status is DELIVERED; SOP s1 says delivered orders cannot be cancelled.",
            evidence=[order_evidence, cite_document(conn, "SRC-03", "1")],
        )

    if order.status is OrderStatus.PICKED_UP:
        return DecisionResult(
            result=CancellationOutcome(
                decision="cannot_cancel", fee_inr=None, applicable_rule="SRC-03#1",
                order_status=order.status, minutes_since_booking=None,
            ),
            trust_state=TrustState.CONFIDENT,
            reason=(
                "Order status is PICKED_UP; SOP s1 says use the return-to-origin workflow "
                "instead of cancellation. This applies even for Northstar - the agreement's "
                "waiver (SRC-05 s2) explicitly stops applying once a shipment is PICKED_UP."
            ),
            evidence=[order_evidence, cite_document(conn, "SRC-03", "1")],
        )

    if order.status is OrderStatus.DRAFT:
        return DecisionResult(
            result=CancellationOutcome(
                decision="can_cancel", fee_inr=0.0, applicable_rule="SRC-03#1",
                order_status=order.status, minutes_since_booking=None,
            ),
            trust_state=TrustState.CONFIDENT,
            reason="DRAFT orders may be cancelled with no fee (SOP s1).",
            evidence=[order_evidence, cite_document(conn, "SRC-03", "1")],
        )

    # BOOKED
    if order.cancellation_requested_at is None:
        return DecisionResult(
            result=CancellationOutcome(
                decision="no_action_needed", fee_inr=None, applicable_rule="SRC-03#1",
                order_status=order.status, minutes_since_booking=None,
            ),
            trust_state=TrustState.CONFIDENT,
            reason="No cancellation has been requested for this order.",
            evidence=[order_evidence],
        )

    minutes = (order.cancellation_requested_at - order.booked_at).total_seconds() / 60
    applicability = resolve_applicability(
        conn, ClauseTopic.CANCELLATION_FEE, order.account_id, snapshot.date()
    )
    rule_fn = _FEE_RULES[applicability.winning_source_id]
    fee, note = rule_fn(order, minutes)

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
        result=CancellationOutcome(
            decision="can_cancel", fee_inr=fee,
            applicable_rule=f"{applicability.winning_source_id}#{applicability.winning_section}",
            order_status=order.status, minutes_since_booking=minutes,
        ),
        trust_state=trust_from(
            review_required=applicability.needs_human_review, has_assumptions=False
        ),
        reason=f"{note}. {applicability.reason}",
        evidence=[
            order_evidence,
            cite_document(conn, applicability.winning_source_id, applicability.winning_section),
        ],
        calculation_inputs={
            "minutes_since_booking": minutes,
            "booked_at": order.booked_at.isoformat(),
            "cancellation_requested_at": order.cancellation_requested_at.isoformat(),
        },
        conflicts=conflicts,
        needs_human_review=applicability.needs_human_review,
    )
