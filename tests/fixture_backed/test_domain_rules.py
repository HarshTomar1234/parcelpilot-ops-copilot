"""Every value here was independently computed for the fixture (not copied
from the real pack) and verified by actually running the code before being
written into an assertion - see the phase report for the exact smoke-test
session. Always runs; never needs the real source pack.
"""

from app.domain.cancellation import evaluate_cancellation
from app.domain.outcomes import DecisionResult, TrustState
from app.domain.service_credit import evaluate_service_credit
from tests.fixtures.seed_fixture_db import (
    FIXTURE_AGREEMENT_OVERRIDES,
    FIXTURE_CREDIT_RULES,
    FIXTURE_DEFAULT_SOURCE,
    FIXTURE_FEE_RULES,
)

_REGISTRY = {"overrides": FIXTURE_AGREEMENT_OVERRIDES, "defaults": FIXTURE_DEFAULT_SOURCE}


def _cancel(conn, auth, clock, order_id: str) -> DecisionResult:
    return evaluate_cancellation(
        conn, order_id, auth, clock, fee_rules=FIXTURE_FEE_RULES, **_REGISTRY
    )


def test_meridian_waiver_overrides_default_fee(conn, auth, clock):
    result = _cancel(conn, auth, clock, "FXO-1001")
    assert result.result is not None
    assert result.result.decision == "can_cancel"
    assert result.result.fee_inr == 0.0
    assert result.result.applicable_rule == "FIX-05#2"
    assert result.conflicts and result.conflicts[0].winner_source_id == "FIX-05"
    assert result.conflicts[0].loser_source_id == "FIX-03"


def test_picked_up_cannot_cancel_even_with_a_waiver_agreement(conn, auth, clock):
    result = _cancel(conn, auth, clock, "FXO-1002")
    assert result.result is not None
    assert result.result.decision == "cannot_cancel"


def test_cobalt_has_no_cancellation_waiver_default_fee_applies(conn, auth, clock):
    result = _cancel(conn, auth, clock, "FXO-2001")
    assert result.result is not None
    assert result.result.fee_inr == 150.0
    assert result.result.applicable_rule == "FIX-03#1"
    assert not result.conflicts


def test_within_threshold_no_fee(conn, auth, clock):
    result = _cancel(conn, auth, clock, "FXO-3001")
    assert result.result is not None
    assert result.result.fee_inr == 0.0


def test_delivered_cannot_cancel(conn, auth, clock):
    result = _cancel(conn, auth, clock, "FXO-4001")
    assert result.result is not None
    assert result.result.decision == "cannot_cancel"


def test_cobalt_service_credit_agreement_overrides_default_amount(conn, auth, clock):
    result = evaluate_service_credit(
        conn, "FXO-2002", auth, clock, credit_rules=FIXTURE_CREDIT_RULES, **_REGISTRY
    )
    assert result.result is not None
    assert result.result.eligible is True
    assert result.result.credit_inr == 250.0  # agreement; default fixture formula would give 240
    assert result.result.applicable_rule == "FIX-06#3"
    assert result.trust_state is TrustState.CONDITIONAL  # pickup still open, delay accruing
    assert result.assumptions
