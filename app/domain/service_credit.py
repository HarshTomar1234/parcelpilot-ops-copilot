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

Credit rules are declarative data (ServiceCreditRule), not one bespoke
Python function per real source_id - every rule in the pack is either
"percentage of fee, capped" or "a fixed amount", both parameterized by
threshold. overrides/defaults/credit_rules default to the real registries
and are swappable (Phase 3 pre-flight 2.6) - tests/fixture_backed/ proves
this against an entirely different, fabricated registry.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.authorization.context import AuthContext
from app.domain.evidence import cite_document, cite_structured
from app.domain.outcomes import Conflict, DecisionResult, TrustState, trust_from
from app.policy.applicability import (
    AGREEMENT_OVERRIDES,
    DEFAULT_SOURCE,
    AgreementOverride,
    ClauseTopic,
    resolve_applicability,
)
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


@dataclass(frozen=True)
class ServiceCreditRule:
    threshold_hours: float
    kind: Literal["percentage_with_cap", "fixed_amount"]
    cap_inr: float | None = None
    percentage: float | None = None
    fixed_amount_inr: float | None = None


def _apply_credit_rule(
    rule: ServiceCreditRule, delay_hours: float, shipment_fee_inr: float
) -> tuple[bool, float | None, str]:
    if delay_hours <= rule.threshold_hours:
        return False, None, f"delay is <= {rule.threshold_hours:g} hours; threshold not met"
    if rule.kind == "fixed_amount":
        assert rule.fixed_amount_inr is not None
        return True, rule.fixed_amount_inr, (
            f"delay > {rule.threshold_hours:g} hours with carrier fault and no customer "
            f"fault (fixed INR {rule.fixed_amount_inr:g})"
        )
    assert rule.cap_inr is not None and rule.percentage is not None
    credit = min(rule.cap_inr, rule.percentage * shipment_fee_inr)
    return True, credit, (
        f"delay > {rule.threshold_hours:g} hours with carrier fault and no customer fault "
        f"(default formula: lower of INR {rule.cap_inr:g} or {rule.percentage:.0%} of fee)"
    )


# Real pack rules (docs/initial_rules.md R3): default SOP percentage-with-cap,
# and LumenWorks' fixed-amount replacement.
DEFAULT_CREDIT_RULES: dict[str, ServiceCreditRule] = {
    "SRC-03": ServiceCreditRule(
        threshold_hours=2, kind="percentage_with_cap", cap_inr=500.0, percentage=0.10
    ),
    "SRC-06": ServiceCreditRule(threshold_hours=4, kind="fixed_amount", fixed_amount_inr=300.0),
}


def evaluate_service_credit(
    conn: sqlite3.Connection,
    order_id: str,
    auth: AuthContext,
    clock: SnapshotClock,
    *,
    credit_rules: dict[str, ServiceCreditRule] = DEFAULT_CREDIT_RULES,
    overrides: tuple[AgreementOverride, ...] = AGREEMENT_OVERRIDES,
    defaults: dict[ClauseTopic, tuple[str, str] | None] = DEFAULT_SOURCE,
) -> DecisionResult[ServiceCreditOutcome]:
    snapshot = clock.now()
    order = get_order(conn, order_id, auth, tz_of(clock))
    order_evidence = cite_structured("orders", order.order_id)

    default_source = defaults[ClauseTopic.SERVICE_CREDIT_THRESHOLD_AND_AMOUNT]
    assert default_source is not None
    default_source_id, default_section = default_source

    if not order.carrier_fault or order.customer_fault:
        reason = (
            "carrier_fault is False" if not order.carrier_fault else "customer_fault is True"
        )
        return DecisionResult(
            result=ServiceCreditOutcome(
                eligible=False, credit_inr=None,
                applicable_rule=f"{default_source_id}#{default_section}",
                delay_hours=None, delay_reference=None, manager_approval_required=False,
            ),
            trust_state=TrustState.CONFIDENT,
            reason=(
                f"Not eligible: {reason}. "
                "The SOP requires carrier fault and no customer-caused issue."
            ),
            evidence=[order_evidence, cite_document(conn, default_source_id, default_section)],
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
        conn, ClauseTopic.SERVICE_CREDIT_THRESHOLD_AND_AMOUNT, order.account_id, snapshot.date(),
        overrides=overrides, defaults=defaults,
    )
    rule = credit_rules[applicability.winning_source_id]
    eligible, credit, note = _apply_credit_rule(rule, delay_hours, order.shipment_fee_inr)

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
            f" Requires manager approval (individual credits above "
            f"INR {_MANAGER_APPROVAL_THRESHOLD_INR:g})."
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
