"""Runs golden_cases.json's own Operations Radar expectations through the
real detection engine (Phase 5). These four cases (GC-029..032, tagged
"radar") were already present in the golden dataset before this phase's
detection code was written - this file is what makes them the regression
suite for the numbers that matter, not hand-picked assertions.
"""

from __future__ import annotations

import pytest

from app.authorization.context import AuthContext, Role
from app.detection.service import run_operations_radar
from app.errors import NotAuthorizedError


def test_sla_breach_alert_matches_the_golden_case_exactly(conn, auth, clock):
    alerts = run_operations_radar(conn, auth, clock, alert_types=None)
    breaches = [a for a in alerts if a.alert_type.value == "sla_breach"]
    assert len(breaches) == 2
    records = sorted(r for a in breaches for r in a.representative_records)
    assert records == ["TKT-501", "TKT-505"]
    accounts = sorted({acct for a in breaches for acct in a.affected_accounts})
    assert accounts == ["ACCT-001", "ACCT-004"]
    assert all(a.trust_state.value == "CONFIDENT" for a in breaches)


def test_known_issue_pattern_matches_the_golden_case_exactly(conn, auth, clock):
    """Golden case: known_issue=KI-208, linked_tickets=[TKT-502, TKT-451],
    distinct_accounts=1, honest_scope_note about a single-account repeat -
    both the closed ticket (TKT-451) and the open one (TKT-502) count as
    evidence, since the issue document's own status is what makes it
    current, not any one ticket's status."""
    alerts = run_operations_radar(conn, auth, clock, alert_types=None)
    ki208 = next(a for a in alerts if "KI-208" in a.title)
    assert sorted(ki208.representative_records) == ["TKT-451", "TKT-502"]
    assert ki208.affected_accounts == ["ACCT-002"]
    assert "one account" in ki208.reason


def test_overdue_pickup_matches_the_golden_case_exactly(conn, auth, clock):
    """Golden case: alert_type=overdue_pickup, count=1, ORD-2002,
    hours_overdue=4.5, linked_entitlement points at a possible service
    credit."""
    alerts = run_operations_radar(conn, auth, clock, alert_types=None)
    overdue = [a for a in alerts if a.alert_type.value == "overdue_pickup"]
    assert len(overdue) == 1
    alert = overdue[0]
    assert alert.representative_records == ["ORD-2002"]
    assert "4.5" in alert.reason
    assert "service credit" in alert.recommended_next_step.lower()


def test_restricted_support_request_matches_the_golden_case_exactly(conn, clock):
    """Golden case: role=restricted_support, expected_status=rejected,
    expected_trust=ESCALATE, expected_tools=[] (no detection tool ever
    invoked), denied_reason="cross-account detection requires
    operations_admin", must_not return alerts referencing any account."""
    restricted = AuthContext(role=Role.RESTRICTED_SUPPORT, account_scope=["ACCT-003"])
    with pytest.raises(NotAuthorizedError, match="operations_admin"):
        run_operations_radar(conn, restricted, clock)
