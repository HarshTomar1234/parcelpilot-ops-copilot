"""Every case here is cross-checked against docs/initial_rules.md R2's
verified table, not asserted from scratch - the numbers in this file are
not invented, they are the same numbers Phase 0 computed independently.
"""

import pytest

from app.authorization.context import AuthContext, Role
from app.domain.cancellation import evaluate_cancellation
from app.domain.outcomes import TrustState
from app.errors import NotAuthorizedError


def test_northstar_waiver_overrides_default_fee(conn, auth, clock):
    result = evaluate_cancellation(conn, "ORD-1001", auth, clock)
    assert result.result is not None
    assert result.result.decision == "can_cancel"
    assert result.result.fee_inr == 0.0
    assert result.result.applicable_rule == "SRC-05#2"
    assert result.trust_state is TrustState.CONFIDENT
    assert result.conflicts and result.conflicts[0].winner_source_id == "SRC-05"
    assert result.conflicts[0].loser_source_id == "SRC-03"


def test_picked_up_order_cannot_cancel_even_for_northstar(conn, auth, clock):
    result = evaluate_cancellation(conn, "ORD-1002", auth, clock)
    assert result.result is not None
    assert result.result.decision == "cannot_cancel"
    assert result.result.fee_inr is None
    assert "return-to-origin" in result.reason


def test_lumenworks_has_no_waiver_default_fee_applies(conn, auth, clock):
    result = evaluate_cancellation(conn, "ORD-2001", auth, clock)
    assert result.result is not None
    assert result.result.decision == "can_cancel"
    assert result.result.fee_inr == 250.0
    assert result.result.applicable_rule == "SRC-03#1"
    assert not result.conflicts


def test_no_cancellation_requested_is_no_action_needed(conn, auth, clock):
    result = evaluate_cancellation(conn, "ORD-2002", auth, clock)
    assert result.result is not None
    assert result.result.decision == "no_action_needed"
    assert result.result.fee_inr is None


def test_within_thirty_minutes_no_fee(conn, auth, clock):
    result = evaluate_cancellation(conn, "ORD-3001", auth, clock)
    assert result.result is not None
    assert result.result.decision == "can_cancel"
    assert result.result.fee_inr == 0.0
    assert result.result.minutes_since_booking == 15.0


def test_delivered_order_cannot_cancel(conn, auth, clock):
    result = evaluate_cancellation(conn, "ORD-4001", auth, clock)
    assert result.result is not None
    assert result.result.decision == "cannot_cancel"
    assert result.result.fee_inr is None


def test_evidence_includes_order_and_the_winning_document(conn, auth, clock):
    result = evaluate_cancellation(conn, "ORD-1001", auth, clock)
    kinds = {e.kind for e in result.evidence}
    assert kinds == {"structured", "document"}
    doc = next(e for e in result.evidence if e.kind == "document")
    assert doc.source_id == "SRC-05"


def test_scoped_context_blocks_cross_account_order(conn, clock):
    scoped = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["ACCT-002"])
    with pytest.raises(NotAuthorizedError):
        evaluate_cancellation(conn, "ORD-1001", scoped, clock)
