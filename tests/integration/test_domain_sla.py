"""Cross-checked against docs/initial_rules.md R5's verified table. TKT-501
is the sharpest source-selection test in the pack: the same ticket reads as
breached, exactly on the line, or comfortably fine depending on which of
three sources (agreement / current policy / deprecated policy) is used -
only the agreement is the correct answer.
"""

from app.domain.outcomes import TrustState
from app.domain.sla import _lookup_sla_target, calculate_sla
from app.models.enums import Severity
from app.structured_data.repository import get_account


def test_northstar_p1_breaches_under_the_agreement_not_the_default(conn, auth, clock):
    result = calculate_sla(conn, "TKT-501", auth, clock)
    assert result.result is not None
    assert result.result.applicable_source_id == "SRC-05"
    assert result.result.severity.value == "P1"
    assert result.result.breached is True
    assert result.result.elapsed_minutes_past_deadline == 15.0
    assert result.trust_state is TrustState.CONFIDENT
    assert result.needs_human_review is True  # P1 breach -> escalate
    assert result.conflicts and result.conflicts[0].winner_source_id == "SRC-05"
    assert result.conflicts[0].loser_source_id == "SRC-01"


def test_axis_labs_p1_breaches_under_default_policy_no_agreement(conn, auth, clock):
    result = calculate_sla(conn, "TKT-505", auth, clock)
    assert result.result is not None
    assert result.result.applicable_source_id == "SRC-01"
    assert result.result.severity.value == "P1"
    assert result.result.breached is True
    assert result.result.elapsed_minutes_past_deadline == 120.0
    assert not result.conflicts  # ACCT-004 has no agreement


def test_business_hour_targets_are_conditional_not_breached_or_clear(conn, auth, clock):
    for ticket_id in ("TKT-502", "TKT-503", "TKT-504"):
        result = calculate_sla(conn, ticket_id, auth, clock)
        assert result.result is not None, ticket_id
        assert result.result.breached is None, ticket_id
        assert result.result.deadline is None, ticket_id
        assert result.trust_state is TrustState.CONDITIONAL, ticket_id
        assert result.assumptions, ticket_id


def test_deprecated_policy_is_never_the_applicable_source(conn, auth, clock):
    for ticket_id in ("TKT-501", "TKT-502", "TKT-503", "TKT-504", "TKT-505"):
        result = calculate_sla(conn, ticket_id, auth, clock)
        assert result.result is not None
        assert result.result.applicable_source_id != "SRC-02"


def test_account_specific_target_wins_over_plan_default_even_when_both_match(conn, auth):
    """Real data never produces this ambiguity (a source_id is either wholly
    plan-scoped or wholly account-scoped), so this constructs it directly:
    insert a synthetic account-specific SRC-01/P1 row alongside the real
    Enterprise plan row, and confirm the lookup does not depend on which one
    SQLite happens to return first.
    """
    account = get_account(conn, "ACCT-004", auth)  # Axis Labs, plan=Enterprise
    assert account.plan == "Enterprise"

    conn.execute(
        "INSERT INTO sla_targets "
        "(source_id, scope_kind, plan, account_id, severity, target_text, "
        " target_minutes, is_24x7, requires_business_calendar) "
        "VALUES ('SRC-01', 'account', NULL, 'ACCT-004', 'P1', "
        " '5 minutes, 24x7 (synthetic test row)', 5, 1, 0)"
    )

    row = _lookup_sla_target(conn, "SRC-01", account, Severity.P1)
    assert row is not None
    assert row["account_id"] == "ACCT-004"
    assert row["target_minutes"] == 5
