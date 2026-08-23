"""Operations Radar authorization (Phase 5 s9). Authorization is enforced
structurally: every rule reads through search_orders()/search_tickets(),
which filter by auth.account_scope before any aggregation happens - so
these tests prove the property, they don't implement a second filtering
layer on top of it. Specifically covers the spec's named attack: "how
many P1 tickets does another account have" must never be answerable
through an aggregate, even a partial one.

Every test that checks "no leakage" first proves the alert genuinely
exists in the unrestricted view - an assertion that a scoped view has no
alert is meaningless if there was never going to be one at all.
"""

from __future__ import annotations

import pytest

from app.authorization.context import AuthContext, Role
from app.detection.service import group_by_account, run_operations_radar
from app.errors import NotAuthorizedError
from tests.fixtures.seed_fixture_db import FIXTURE_AGREEMENT_OVERRIDES, FIXTURE_DEFAULT_SOURCE

_REGISTRY = {"overrides": FIXTURE_AGREEMENT_OVERRIDES, "defaults": FIXTURE_DEFAULT_SOURCE}
_UNRESTRICTED = AuthContext(role=Role.OPERATIONS_ADMIN)


def _scoped(*account_ids: str) -> AuthContext:
    return AuthContext(role=Role.SUPPORT_AGENT, account_scope=list(account_ids))


def test_scoped_caller_never_sees_another_accounts_sla_breach(conn, clock):
    # FXT-501 (FX-001) and FXT-505 (FX-004) both breach - confirmed
    # present in the unrestricted view first, so the scoped assertion
    # below is proving something real, not a vacuous empty-either-way.
    unrestricted = run_operations_radar(conn, _UNRESTRICTED, clock, **_REGISTRY)
    assert any(a.alert_type.value == "sla_breach" for a in unrestricted)

    # FX-002 has no P1/P2 breach of its own, but does have its own
    # legitimate overdue_pickup alert (FXO-2002) - only the leaked
    # cross-account SLA breach type is what this test checks for.
    alerts = run_operations_radar(conn, _scoped("FX-002"), clock, **_REGISTRY)
    assert not any(a.alert_type.value == "sla_breach" for a in alerts)
    assert not any(a.alert_type.value == "recurring_issue" for a in alerts)


def test_scoped_caller_sees_only_their_own_accounts_alert(conn, clock):
    alerts = run_operations_radar(conn, _scoped("FX-001"), clock, window_days=30, **_REGISTRY)
    assert alerts
    for alert in alerts:
        assert set(alert.affected_accounts) <= {"FX-001"}


def test_recurring_alert_does_not_leak_a_partial_cross_account_count(conn, clock):
    # Global (unrestricted) view: 2 open P1 tickets, threshold 2, fires.
    unrestricted = run_operations_radar(conn, _UNRESTRICTED, clock, **_REGISTRY)
    global_recurring = [a for a in unrestricted if a.alert_type.value == "recurring_issue"]
    assert global_recurring and global_recurring[0].observed_count == 2

    # A caller scoped to only ONE of the two P1 accounts must never see a
    # "count=2" recurring alert - that would leak that another account
    # also has a P1 ticket. It must see no recurring alert at all, because
    # from what they're authorized to see, only 1 ticket qualifies -
    # below the threshold of 2.
    scoped = run_operations_radar(conn, _scoped("FX-001"), clock, **_REGISTRY)
    scoped_recurring = [a for a in scoped if a.alert_type.value == "recurring_issue"]
    assert scoped_recurring == []


def test_aggregate_query_for_another_accounts_p1_count_is_denied(conn, clock):
    """The spec's named attack: "How many P1 tickets does another account
    have?" - answered here by proving the aggregate rule itself, scoped to
    an account the caller cannot see, produces nothing, not a filtered-down
    number that still confirms the other account's ticket exists."""
    unrestricted = run_operations_radar(conn, _UNRESTRICTED, clock, **_REGISTRY)
    assert any("FX-001" in a.affected_accounts for a in unrestricted)
    assert any("FX-004" in a.affected_accounts for a in unrestricted)

    scoped = _scoped("FX-002")
    alerts = run_operations_radar(conn, scoped, clock, alert_types=None, **_REGISTRY)
    assert not any("FX-001" in a.affected_accounts for a in alerts)
    assert not any("FX-004" in a.affected_accounts for a in alerts)


def test_widening_account_scope_via_request_field_is_ignored(conn, clock):
    """Mirrors the tool boundary's intersection logic (app/agent/tools.py
    detect_issues_tool) at the service layer directly: even if a
    caller's own AuthContext were (incorrectly) constructed with an
    account outside their real access, run_operations_radar only ever
    trusts the AuthContext it's given - there is no separate "requested
    accounts" parameter here to smuggle a widening value through."""
    unrestricted = run_operations_radar(conn, _UNRESTRICTED, clock, **_REGISTRY)
    assert any("FX-001" in a.affected_accounts for a in unrestricted)

    scoped = _scoped("FX-002")
    alerts = run_operations_radar(conn, scoped, clock, **_REGISTRY)
    assert not any("FX-001" in a.affected_accounts for a in alerts)


def test_group_by_account_never_introduces_a_new_account_not_in_the_alerts(conn, clock):
    alerts = run_operations_radar(conn, _scoped("FX-002"), clock, **_REGISTRY)
    grouped = group_by_account(alerts)
    assert set(grouped) <= {"FX-002"}


def test_restricted_support_is_denied_operations_radar_entirely(conn, clock):
    """Matches the golden dataset's own expected behavior for "Operations
    Radar requested by a restricted_support user": denied outright,
    regardless of their own account_scope - not silently filtered down to
    zero alerts, but a real NotAuthorizedError."""
    restricted = AuthContext(role=Role.RESTRICTED_SUPPORT, account_scope=["FX-003"])
    with pytest.raises(NotAuthorizedError, match="operations_admin"):
        run_operations_radar(conn, restricted, clock, **_REGISTRY)


def test_support_agent_and_operations_admin_are_not_denied(conn, clock):
    support_agent = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["FX-002"])
    admin = AuthContext(role=Role.OPERATIONS_ADMIN)
    # Neither raises - the denial is specific to restricted_support.
    run_operations_radar(conn, support_agent, clock, **_REGISTRY)
    run_operations_radar(conn, admin, clock, **_REGISTRY)


def test_detection_module_has_no_import_of_the_action_workflow() -> None:
    """Phase 5 s19: no direct alert -> action execution path. An alert's
    recommended_next_step may *mention* prepare_escalation in advisory
    prose (e.g. "review for escalation"), but the detection module can
    never import app.actions or actually call prepare_escalation/
    confirm_action/execute_action - proven structurally, the same way
    Phase 4 proved the agent orchestrator can't reach confirm/execute."""
    import inspect

    from app.detection import models, rules, service, summary

    for module in (models, rules, service, summary):
        source = inspect.getsource(module)
        assert "app.actions" not in source
        assert "confirm_action(" not in source
        assert "execute_action(" not in source
        # prepare_escalation as a real call, not just named in prose -
        # a call always has an opening paren immediately after the name.
        assert "prepare_escalation(" not in source
