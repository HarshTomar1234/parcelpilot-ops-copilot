"""Operations Radar read model (Phase 5 s20). run_operations_radar() is
the single entry point - the only thing an API/UI/agent tool should ever
call, never the individual rule functions directly, so the detection
engine stays independently testable and swappable without touching
callers (app/agent/tools.py's detect_issues tool calls only
this).
"""

from __future__ import annotations

import sqlite3

from app.authorization.context import AuthContext, Role
from app.detection.models import AlertCandidate, AlertSeverity, AlertType
from app.detection.rules import (
    DEFAULT_WINDOW_DAYS,
    detect_carrier_patterns,
    detect_known_issue_patterns,
    detect_overdue_pickups,
    detect_recurring_severity,
    detect_sla_approaching,
    detect_sla_breaches,
)
from app.errors import NotAuthorizedError
from app.policy.applicability import (
    AGREEMENT_OVERRIDES,
    DEFAULT_SOURCE,
    AgreementOverride,
    ClauseTopic,
)
from app.time.clock import SnapshotClock

_POINT_IN_TIME_TYPES = frozenset({AlertType.SLA_BREACH, AlertType.SLA_APPROACHING})
_NO_EXTRA_ARGS_TYPES = frozenset({AlertType.OVERDUE_PICKUP})
_ALL_RULES = {
    AlertType.SLA_BREACH: detect_sla_breaches,
    AlertType.SLA_APPROACHING: detect_sla_approaching,
    AlertType.RECURRING_ISSUE: detect_recurring_severity,
    AlertType.KNOWN_ISSUE_PATTERN: detect_known_issue_patterns,
    AlertType.CARRIER_PATTERN: detect_carrier_patterns,
    AlertType.OVERDUE_PICKUP: detect_overdue_pickups,
}
_SEVERITY_RANK = {
    AlertSeverity.CRITICAL: 0, AlertSeverity.HIGH: 1,
    AlertSeverity.MEDIUM: 2, AlertSeverity.LOW: 3,
}


_SLA_DEPENDENT_TYPES = frozenset(
    {AlertType.SLA_BREACH, AlertType.SLA_APPROACHING, AlertType.RECURRING_ISSUE}
)


def run_operations_radar(
    conn: sqlite3.Connection,
    auth: AuthContext,
    clock: SnapshotClock,
    *,
    alert_types: list[AlertType] | None = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
    overrides: tuple[AgreementOverride, ...] = AGREEMENT_OVERRIDES,
    defaults: dict[ClauseTopic, tuple[str, str] | None] = DEFAULT_SOURCE,
) -> list[AlertCandidate]:
    """Runs every requested detection rule (or all of them) and returns a
    deduplicated list, most severe first. Authorization is already
    enforced inside each rule (they all read through search_orders()/
    search_tickets(), which filter by auth.account_scope) - this function
    does not filter again, but does guard against the same alert_id
    appearing twice if two rule runs ever overlap. overrides/defaults are
    forwarded only to the SLA-dependent rules (breach/approaching/
    recurring, which all call calculate_sla()) - production values by
    default, injectable for the fixture-backed test tier the same way
    app/actions/workflow.py's prepare_escalation already is.

    Role-based access (Phase 5 s18): Operations Radar is a cross-account
    detection surface even when scoped to one caller's accounts (its
    aggregates reason over multiple records at once) - a restricted_support
    caller is denied entirely, matching the golden dataset's own expected
    behavior (GC "[Operations Radar requested by a restricted_support
    user]": expected_status=rejected, denied_reason="cross-account
    detection requires operations_admin"). This is the only role check in
    the codebase beyond account-scope filtering - no field-level
    redaction exists because no field in this schema is more sensitive
    than the account-scoped records it already lives on (see
    docs/architecture_note.md)."""
    if auth.role is Role.RESTRICTED_SUPPORT:
        raise NotAuthorizedError("cross-account detection requires operations_admin")

    types_to_run = alert_types or list(_ALL_RULES)
    seen: dict[str, AlertCandidate] = {}
    for alert_type in types_to_run:
        rule = _ALL_RULES[alert_type]
        if alert_type in _NO_EXTRA_ARGS_TYPES:
            alerts = rule(conn, auth, clock)
        elif alert_type in _POINT_IN_TIME_TYPES:
            alerts = rule(conn, auth, clock, overrides=overrides, defaults=defaults)
        elif alert_type in _SLA_DEPENDENT_TYPES:
            alerts = rule(
                conn, auth, clock, window_days=window_days,
                overrides=overrides, defaults=defaults,
            )
        else:
            alerts = rule(conn, auth, clock, window_days=window_days)
        for alert in alerts:
            seen[alert.alert_id] = alert
    return sorted(seen.values(), key=lambda a: (_SEVERITY_RANK[a.severity], a.alert_id))


def group_by_account(alerts: list[AlertCandidate]) -> dict[str, list[str]]:
    """account_id -> sorted alert_ids affecting it. A pure, separate
    presentation helper - never used to decide what data was fetched, so
    it cannot itself introduce an authorization gap (the alerts passed in
    are already fully scoped by the time this runs)."""
    grouped: dict[str, set[str]] = {}
    for alert in alerts:
        for account_id in alert.affected_accounts:
            grouped.setdefault(account_id, set()).add(alert.alert_id)
    return {account_id: sorted(ids) for account_id, ids in sorted(grouped.items())}
