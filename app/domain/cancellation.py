"""Deterministic cancellation-fee decisions.

docs/initial_rules.md R2: the SOP's per-status branches (DRAFT/BOOKED/
PICKED_UP/DELIVERED) drive the decision; a winning agreement only changes
the *fee calculation on the BOOKED branch* (R2.1) - it never extends past
pickup, never changes DELIVERED, never changes DRAFT. That is why the
per-status branches are handled directly here and only the BOOKED-and-
requested fee math is delegated to policy.applicability.

Fee rules are declarative data (CancellationFeeRule), not one bespoke
Python function per real source_id - a source's rule is either "waive
within N minutes, else a fixed fee" or "waive unconditionally", both
parameterized. overrides/defaults/fee_rules all default to the real
registries and are swappable, the same way resolve_applicability's are
(Phase 3 pre-flight 2.6) - tests/fixture_backed/ proves this function is
generic over an entirely different (fabricated) registry, not just the
one real agreement pair.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.authorization.context import AuthContext
from app.domain.evidence import cite_document, cite_structured
from app.domain.outcomes import Conflict, DecisionResult, TrustState, trust_from
from app.models.enums import OrderStatus
from app.policy.applicability import (
    AGREEMENT_OVERRIDES,
    DEFAULT_SOURCE,
    AgreementOverride,
    ClauseTopic,
    resolve_applicability,
)
from app.structured_data.repository import get_order
from app.time.clock import SnapshotClock, tz_of


class CancellationOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: Literal["can_cancel", "cannot_cancel", "no_action_needed"]
    fee_inr: float | None
    applicable_rule: str
    order_status: OrderStatus
    minutes_since_booking: float | None


@dataclass(frozen=True)
class CancellationFeeRule:
    kind: Literal["threshold_fee", "full_waiver"]
    threshold_minutes: int | None = None
    fee_inr: float | None = None


def _apply_fee_rule(rule: CancellationFeeRule, minutes: float) -> tuple[float, str]:
    if rule.kind == "full_waiver":
        return 0.0, "the agreement waives the cancellation fee regardless of elapsed time"
    assert rule.threshold_minutes is not None and rule.fee_inr is not None
    if minutes <= rule.threshold_minutes:
        return 0.0, f"within {rule.threshold_minutes} minutes of booking, no fee applies"
    return rule.fee_inr, (
        f"more than {rule.threshold_minutes} minutes after booking, "
        f"INR {rule.fee_inr:g} fee applies"
    )


# Real pack rules (docs/initial_rules.md R2): default SOP threshold, and
# Northstar's unconditional waiver.
DEFAULT_FEE_RULES: dict[str, CancellationFeeRule] = {
    "SRC-03": CancellationFeeRule(kind="threshold_fee", threshold_minutes=30, fee_inr=250.0),
    "SRC-05": CancellationFeeRule(kind="full_waiver"),
}


def evaluate_cancellation(
    conn: sqlite3.Connection,
    order_id: str,
    auth: AuthContext,
    clock: SnapshotClock,
    *,
    fee_rules: dict[str, CancellationFeeRule] = DEFAULT_FEE_RULES,
    overrides: tuple[AgreementOverride, ...] = AGREEMENT_OVERRIDES,
    defaults: dict[ClauseTopic, tuple[str, str] | None] = DEFAULT_SOURCE,
) -> DecisionResult[CancellationOutcome]:
    snapshot = clock.now()
    order = get_order(conn, order_id, auth, tz_of(clock))
    order_evidence = cite_structured("orders", order.order_id)

    default_source = defaults[ClauseTopic.CANCELLATION_FEE]
    assert default_source is not None
    default_source_id, default_section = default_source

    if order.status is OrderStatus.DELIVERED:
        return DecisionResult(
            result=CancellationOutcome(
                decision="cannot_cancel", fee_inr=None,
                applicable_rule=f"{default_source_id}#{default_section}",
                order_status=order.status, minutes_since_booking=None,
            ),
            trust_state=TrustState.CONFIDENT,
            reason="Order status is DELIVERED; the SOP says delivered orders cannot be cancelled.",
            evidence=[order_evidence, cite_document(conn, default_source_id, default_section)],
        )

    if order.status is OrderStatus.PICKED_UP:
        return DecisionResult(
            result=CancellationOutcome(
                decision="cannot_cancel", fee_inr=None,
                applicable_rule=f"{default_source_id}#{default_section}",
                order_status=order.status, minutes_since_booking=None,
            ),
            trust_state=TrustState.CONFIDENT,
            reason=(
                "Order status is PICKED_UP; the SOP says use the return-to-origin workflow "
                "instead of cancellation. This applies even under an agreement's waiver - a "
                "cancellation-fee waiver explicitly stops applying once a shipment is PICKED_UP."
            ),
            evidence=[order_evidence, cite_document(conn, default_source_id, default_section)],
        )

    if order.status is OrderStatus.DRAFT:
        return DecisionResult(
            result=CancellationOutcome(
                decision="can_cancel", fee_inr=0.0,
                applicable_rule=f"{default_source_id}#{default_section}",
                order_status=order.status, minutes_since_booking=None,
            ),
            trust_state=TrustState.CONFIDENT,
            reason="DRAFT orders may be cancelled with no fee.",
            evidence=[order_evidence, cite_document(conn, default_source_id, default_section)],
        )

    # BOOKED
    if order.cancellation_requested_at is None:
        return DecisionResult(
            result=CancellationOutcome(
                decision="no_action_needed", fee_inr=None,
                applicable_rule=f"{default_source_id}#{default_section}",
                order_status=order.status, minutes_since_booking=None,
            ),
            trust_state=TrustState.CONFIDENT,
            reason="No cancellation has been requested for this order.",
            evidence=[order_evidence],
        )

    minutes = (order.cancellation_requested_at - order.booked_at).total_seconds() / 60
    applicability = resolve_applicability(
        conn, ClauseTopic.CANCELLATION_FEE, order.account_id, snapshot.date(),
        overrides=overrides, defaults=defaults,
    )
    rule = fee_rules[applicability.winning_source_id]
    fee, note = _apply_fee_rule(rule, minutes)

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
