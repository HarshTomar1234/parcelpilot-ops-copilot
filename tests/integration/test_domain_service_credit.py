"""Cross-checked against docs/initial_rules.md R3's verified table -
ORD-2002 is the only credit-eligible order in the pack."""

from app.domain.outcomes import TrustState
from app.domain.service_credit import evaluate_service_credit


def test_only_ord_2002_is_eligible(conn, auth, clock):
    for order_id in ("ORD-1001", "ORD-1002", "ORD-2001", "ORD-3001", "ORD-4001"):
        result = evaluate_service_credit(conn, order_id, auth, clock)
        assert result.result is not None
        assert result.result.eligible is False, order_id


def test_lumenworks_agreement_replaces_threshold_and_amount(conn, auth, clock):
    result = evaluate_service_credit(conn, "ORD-2002", auth, clock)
    assert result.result is not None
    assert result.result.eligible is True
    assert result.result.credit_inr == 300.0
    assert result.result.applicable_rule == "SRC-06#3"
    assert result.conflicts and result.conflicts[0].winner_source_id == "SRC-06"


def test_still_open_pickup_accrues_delay_from_snapshot(conn, auth, clock):
    result = evaluate_service_credit(conn, "ORD-2002", auth, clock)
    assert result.result is not None
    assert result.result.delay_reference == "snapshot"
    assert result.result.delay_hours == 4.5
    assert result.trust_state is TrustState.CONDITIONAL
    assert result.assumptions


def test_manager_approval_not_required_under_threshold(conn, auth, clock):
    result = evaluate_service_credit(conn, "ORD-2002", auth, clock)
    assert result.result is not None
    assert result.result.manager_approval_required is False


def test_not_carrier_fault_is_confident_denial(conn, auth, clock):
    result = evaluate_service_credit(conn, "ORD-1001", auth, clock)
    assert result.result is not None
    assert result.result.eligible is False
    assert result.trust_state is TrustState.CONFIDENT
    assert "carrier_fault" in result.reason
