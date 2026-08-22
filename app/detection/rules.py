"""Deterministic detection rules (Phase 5 s4-7). Every rule here is a pure
function of (conn, auth, clock, config) -> list[AlertCandidate] - no LLM
call anywhere in this module. Authorization is enforced structurally, not
as an afterthought: every rule fetches its source rows through
search_orders()/search_tickets(), which already filter by
auth.account_scope (app/structured_data/repository.py) - so an
aggregate count computed here can never include a record the caller
isn't authorized to see in the first place.

Rule versions are bumped whenever a rule's *logic* changes in a way that
would change which alerts it produces for the same data - this is what
app/detection/fingerprint.py mixes into the alert_id, so a logic change
naturally produces new alert IDs rather than silently reusing stale ones.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import timedelta

from app.authorization.context import AuthContext
from app.detection.fingerprint import compute_alert_id
from app.detection.models import AlertCandidate, AlertSeverity, AlertType
from app.domain.evidence import cite_document, cite_structured
from app.domain.outcomes import TrustState
from app.domain.sla import calculate_sla
from app.models.enums import OrderStatus, Severity, TicketStatus
from app.policy.applicability import (
    AGREEMENT_OVERRIDES,
    DEFAULT_SOURCE,
    AgreementOverride,
    ClauseTopic,
)
from app.structured_data.repository import search_orders, search_tickets
from app.time.clock import SnapshotClock, tz_of

_SLA_RULE_VERSION = "v1"
_RECURRING_RULE_VERSION = "v1"
_KNOWN_ISSUE_RULE_VERSION = "v1"
_CARRIER_RULE_VERSION = "v1"
_OVERDUE_PICKUP_RULE_VERSION = "v1"

# Severities this phase alerts on for SLA breach/approaching - P3 is
# lower urgency and intentionally excluded (matches Support Policy v3's
# own escalation framing, which only calls out P1 breaches explicitly).
_SLA_ALERT_SEVERITIES = (Severity.P1, Severity.P2)

# Fraction of the SLA target window remaining that counts as "approaching"
# (e.g. 0.25 = the last quarter of the window, not yet breached). This is
# a configurable, documented threshold - not tuned to make any particular
# ticket appear.
DEFAULT_APPROACHING_WARNING_RATIO = 0.25

# A ticket-severity volume this high, currently open, counts as a
# recurring high-severity pattern worth flagging on its own (independent
# of any single ticket's SLA status). 2 is the natural minimum for
# "multiple"/"recurring" - not chosen to inflate alert counts.
DEFAULT_RECURRING_SEVERITY_THRESHOLD = 2

# How many of a carrier's orders must show carrier_fault=1 within the
# window before it counts as a pattern rather than an isolated incident.
DEFAULT_CARRIER_FAULT_THRESHOLD = 2

# A known issue needs at least this many *open* tickets whose text
# overlaps its description before it is surfaced as a current pattern -
# one real match is already documented, code-verified evidence (the
# known-issue doc itself), distinct from "recurring" (which needs a
# count independent of any external document).
DEFAULT_KNOWN_ISSUE_MIN_OCCURRENCES = 1
_MIN_SHARED_TOKENS = 2

# Default snapshot-relative lookback for recurring/known-issue/carrier
# detection - wide enough to cover this corpus's few-day span without
# being so wide it stops meaning anything. Configurable per call.
DEFAULT_WINDOW_DAYS = 30

_KI_ID = re.compile(r"\bKI-\d+\b")
_TOKEN = re.compile(r"[a-z]{4,}")
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "at", "is", "are",
        "was", "were", "be", "this", "that", "with", "by", "as", "it", "its", "opened",
        "status", "investigating", "current", "known", "issue", "issues", "some", "even",
        "though", "remains", "product", "limit", "customers", "experience", "above",
        "approximately", "customer", "while", "still", "before", "arrive", "telling",
        # Generic domain nouns that appear across nearly every ticket regardless
        # of topic - not diagnostic of any one known issue. Found via a real
        # false positive: "shipment"/"creation" incidentally appear in KI-208's
        # own unaffected-scope caveat sentence and matched an unrelated ticket
        # (a plain API 500 error) purely on that vocabulary overlap.
        "shipment", "shipments", "creation", "creating", "order", "orders",
        "account", "accounts", "user", "users",
    }
)


def _significant_tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS}


def detect_sla_breaches(
    conn: sqlite3.Connection,
    auth: AuthContext,
    clock: SnapshotClock,
    *,
    overrides: tuple[AgreementOverride, ...] = AGREEMENT_OVERRIDES,
    defaults: dict[ClauseTopic, tuple[str, str] | None] = DEFAULT_SOURCE,
) -> list[AlertCandidate]:
    """A P1/P2 open ticket whose deadline has confidently passed. Business-
    hour targets (trust_state != CONFIDENT, i.e. not computable without an
    undefined business calendar) are omitted, never guessed - see ADR-007/
    008 and app/domain/sla.py."""
    tz = tz_of(clock)
    alerts: list[AlertCandidate] = []
    for ticket in search_tickets(conn, auth, tz, status=TicketStatus.OPEN):
        result = calculate_sla(
            conn, ticket.ticket_id, auth, clock, overrides=overrides, defaults=defaults
        )
        outcome = result.result
        if outcome is None or outcome.severity not in _SLA_ALERT_SEVERITIES:
            continue
        if result.trust_state is not TrustState.CONFIDENT:
            continue  # not safely computable - omit rather than guess
        if not outcome.breached:
            continue

        evidence = [
            cite_structured("tickets", ticket.ticket_id, ticket.subject),
            *result.evidence,
        ]
        alert_id = compute_alert_id(
            AlertType.SLA_BREACH, "point-in-time", _SLA_RULE_VERSION, [ticket.ticket_id]
        )
        elapsed = outcome.elapsed_minutes_past_deadline or 0.0
        alerts.append(
            AlertCandidate(
                alert_id=alert_id,
                alert_type=AlertType.SLA_BREACH,
                severity=(
                    AlertSeverity.CRITICAL if outcome.severity is Severity.P1
                    else AlertSeverity.HIGH
                ),
                title=f"{outcome.severity.value} SLA breach: {ticket.ticket_id}",
                reason=(
                    f"{ticket.ticket_id} ({outcome.severity.value}) is {elapsed:.0f} minutes "
                    f"past its first-response deadline ({outcome.target_text})."
                ),
                observed_count=1,
                threshold=1,
                time_window="point-in-time (dataset snapshot)",
                representative_records=[ticket.ticket_id],
                affected_accounts=[ticket.account_id],
                evidence=evidence,
                recommended_next_step=(
                    "Review for immediate escalation (prepare_escalation requires separate "
                    "confirmation before anything is actually escalated)."
                ),
                trust_state=result.trust_state,
                rule_version=_SLA_RULE_VERSION,
            )
        )
    return alerts


def detect_sla_approaching(
    conn: sqlite3.Connection,
    auth: AuthContext,
    clock: SnapshotClock,
    *,
    warning_ratio: float = DEFAULT_APPROACHING_WARNING_RATIO,
    overrides: tuple[AgreementOverride, ...] = AGREEMENT_OVERRIDES,
    defaults: dict[ClauseTopic, tuple[str, str] | None] = DEFAULT_SOURCE,
) -> list[AlertCandidate]:
    """A P1/P2 open ticket not yet breached, but within the last
    `warning_ratio` of its target window - only for 24x7-computable
    targets (trust_state == CONFIDENT); a business-hour target is omitted
    entirely rather than guessed at."""
    tz = tz_of(clock)
    alerts: list[AlertCandidate] = []
    for ticket in search_tickets(conn, auth, tz, status=TicketStatus.OPEN):
        result = calculate_sla(
            conn, ticket.ticket_id, auth, clock, overrides=overrides, defaults=defaults
        )
        outcome = result.result
        if outcome is None or outcome.severity not in _SLA_ALERT_SEVERITIES:
            continue
        if result.trust_state is not TrustState.CONFIDENT:
            continue
        if outcome.breached or outcome.target_minutes is None:
            continue
        elapsed = outcome.elapsed_minutes_past_deadline
        if elapsed is None:
            continue
        remaining = -elapsed
        if remaining > outcome.target_minutes * warning_ratio:
            continue

        evidence = [
            cite_structured("tickets", ticket.ticket_id, ticket.subject),
            *result.evidence,
        ]
        alert_id = compute_alert_id(
            AlertType.SLA_APPROACHING, "point-in-time", _SLA_RULE_VERSION, [ticket.ticket_id]
        )
        alerts.append(
            AlertCandidate(
                alert_id=alert_id,
                alert_type=AlertType.SLA_APPROACHING,
                severity=(
                    AlertSeverity.HIGH if outcome.severity is Severity.P1
                    else AlertSeverity.MEDIUM
                ),
                title=f"{outcome.severity.value} SLA approaching: {ticket.ticket_id}",
                reason=(
                    f"{ticket.ticket_id} ({outcome.severity.value}) has {remaining:.0f} of "
                    f"{outcome.target_minutes} minutes remaining before its first-response "
                    "deadline."
                ),
                observed_count=1,
                threshold=1,
                time_window="point-in-time (dataset snapshot)",
                representative_records=[ticket.ticket_id],
                affected_accounts=[ticket.account_id],
                evidence=evidence,
                recommended_next_step="Prioritize a first response before the deadline passes.",
                trust_state=result.trust_state,
                rule_version=_SLA_RULE_VERSION,
            )
        )
    return alerts


def detect_recurring_severity(
    conn: sqlite3.Connection,
    auth: AuthContext,
    clock: SnapshotClock,
    *,
    threshold: int = DEFAULT_RECURRING_SEVERITY_THRESHOLD,
    window_days: int = DEFAULT_WINDOW_DAYS,
    overrides: tuple[AgreementOverride, ...] = AGREEMENT_OVERRIDES,
    defaults: dict[ClauseTopic, tuple[str, str] | None] = DEFAULT_SOURCE,
) -> list[AlertCandidate]:
    """Multiple open tickets classified at the same high severity within
    the window - a volume pattern independent of any single ticket's SLA
    status. Only CONFIDENT severity classifications count; a severity the
    classifier couldn't determine confidently is excluded, not guessed."""
    tz = tz_of(clock)
    snapshot = clock.now()
    cutoff = snapshot - timedelta(days=window_days)
    alerts: list[AlertCandidate] = []

    by_severity: dict[Severity, list[str]] = {Severity.P1: [], Severity.P2: []}
    accounts: dict[Severity, set[str]] = {Severity.P1: set(), Severity.P2: set()}
    for ticket in search_tickets(conn, auth, tz, status=TicketStatus.OPEN):
        if ticket.created_at < cutoff:
            continue
        result = calculate_sla(
            conn, ticket.ticket_id, auth, clock, overrides=overrides, defaults=defaults
        )
        outcome = result.result
        if outcome is None or outcome.severity not in (Severity.P1, Severity.P2):
            continue
        if result.trust_state not in (TrustState.CONFIDENT, TrustState.CONDITIONAL):
            continue  # UNCERTAIN severity - don't count it either way
        by_severity[outcome.severity].append(ticket.ticket_id)
        accounts[outcome.severity].add(ticket.account_id)

    window_desc = f"{window_days}d"
    for severity, ticket_ids in by_severity.items():
        if len(ticket_ids) < threshold:
            continue
        alert_id = compute_alert_id(
            AlertType.RECURRING_ISSUE, window_desc, _RECURRING_RULE_VERSION, ticket_ids
        )
        alerts.append(
            AlertCandidate(
                alert_id=alert_id,
                alert_type=AlertType.RECURRING_ISSUE,
                severity=AlertSeverity.HIGH if severity is Severity.P1 else AlertSeverity.MEDIUM,
                title=f"{len(ticket_ids)} open {severity.value} tickets",
                reason=(
                    f"{len(ticket_ids)} tickets currently open and classified {severity.value} "
                    f"within the last {window_days} days - at or above the threshold of "
                    f"{threshold} for a recurring high-severity pattern."
                ),
                observed_count=len(ticket_ids),
                threshold=threshold,
                time_window=window_desc,
                representative_records=sorted(ticket_ids),
                affected_accounts=sorted(accounts[severity]),
                evidence=[cite_structured("tickets", tid) for tid in sorted(ticket_ids)],
                recommended_next_step=(
                    "Review open high-severity tickets for a common root cause or staffing gap."
                ),
                trust_state=TrustState.CONFIDENT,
                rule_version=_RECURRING_RULE_VERSION,
            )
        )
    return alerts


def _parse_known_issues(conn: sqlite3.Connection) -> list[dict]:
    """Extracts each individual known-issue entry from CURRENT product-doc
    chunks - segmented per KI-<n> mention (not per whole chunk, which can
    contain several issues), so each issue's token set only reflects its
    own text. A "Resolved" marker anywhere in an issue's own segment
    excludes it - see docs' own instruction not to explain new incidents
    with a resolved issue."""
    rows = conn.execute(
        "SELECT chunk_id, source_id, section, text FROM document_chunks "
        "WHERE source_type = 'product_doc' AND status = 'CURRENT' AND text LIKE '%KI-%'"
    ).fetchall()
    issues: list[dict] = []
    for row in rows:
        text = row["text"]
        matches = list(_KI_ID.finditer(text))
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            segment = text[start:end]
            issues.append(
                {
                    "ki_id": match.group(0),
                    "source_id": row["source_id"],
                    "section": row["section"],
                    "resolved": "resolved" in segment.lower(),
                    "tokens": _significant_tokens(segment),
                }
            )
    return issues


def detect_known_issue_patterns(
    conn: sqlite3.Connection,
    auth: AuthContext,
    clock: SnapshotClock,
    *,
    min_occurrences: int = DEFAULT_KNOWN_ISSUE_MIN_OCCURRENCES,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[AlertCandidate]:
    """Connects each currently-active known issue (product doc, status
    CURRENT, not marked Resolved in its own text) to tickets - open or
    closed - whose subject/description shares enough significant
    vocabulary with the issue's own description. A ticket being closed
    does not disqualify it as evidence: the issue *document's own status*
    (Investigating/Monitoring, not Resolved) is what makes the pattern
    current, not whether any one customer's individual ticket was
    resolved. A resolved issue (e.g. KI-176) never produces an alert,
    regardless of ticket text - the source's own status is authoritative,
    not a text-similarity guess.

    The alert is explicit about whether the matched tickets span one
    account or several - "recurring for one account" and "a cross-
    customer pattern" are different findings, and collapsing them into a
    single count would overstate the latter."""
    tz = tz_of(clock)
    snapshot = clock.now()
    cutoff = snapshot - timedelta(days=window_days)
    window_desc = f"{window_days}d"

    known_issues = [i for i in _parse_known_issues(conn) if not i["resolved"]]
    if not known_issues:
        return []

    candidate_tickets = [
        t for t in search_tickets(conn, auth, tz) if t.created_at >= cutoff
    ]

    alerts: list[AlertCandidate] = []
    for issue in known_issues:
        matches = [
            t for t in candidate_tickets
            if len(_significant_tokens(f"{t.subject} {t.description}") & issue["tokens"])
            >= _MIN_SHARED_TOKENS
        ]
        if len(matches) < min_occurrences:
            continue

        ticket_ids = [t.ticket_id for t in matches]
        distinct_accounts = sorted({t.account_id for t in matches})
        alert_id = compute_alert_id(
            AlertType.KNOWN_ISSUE_PATTERN, window_desc, _KNOWN_ISSUE_RULE_VERSION,
            [issue["ki_id"], *ticket_ids],
        )
        evidence = [
            cite_document(conn, issue["source_id"], issue["section"], note=issue["ki_id"]),
            *[cite_structured("tickets", tid) for tid in ticket_ids],
        ]
        scope_note = (
            f"both/all matching tickets belong to {distinct_accounts[0]} - a repeat for "
            "one account, not yet a cross-customer pattern" if len(distinct_accounts) == 1
            else f"matching tickets span {len(distinct_accounts)} distinct accounts - a "
            "cross-customer pattern"
        )
        alerts.append(
            AlertCandidate(
                alert_id=alert_id,
                alert_type=AlertType.KNOWN_ISSUE_PATTERN,
                severity=AlertSeverity.MEDIUM,
                title=f"Active known issue {issue['ki_id']} matches {len(matches)} ticket(s)",
                reason=(
                    f"{issue['ki_id']} is a currently active known issue with {len(matches)} "
                    f"ticket(s) whose description overlaps its documented symptoms ({scope_note})."
                ),
                observed_count=len(matches),
                threshold=min_occurrences,
                time_window=window_desc,
                representative_records=sorted(ticket_ids),
                affected_accounts=distinct_accounts,
                evidence=evidence,
                recommended_next_step=(
                    f"Cross-reference {issue['ki_id']}'s documented workaround with affected "
                    "customers."
                ),
                trust_state=TrustState.CONFIDENT,
                rule_version=_KNOWN_ISSUE_RULE_VERSION,
            )
        )
    return alerts


def detect_carrier_patterns(
    conn: sqlite3.Connection,
    auth: AuthContext,
    clock: SnapshotClock,
    *,
    threshold: int = DEFAULT_CARRIER_FAULT_THRESHOLD,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[AlertCandidate]:
    """Multiple orders with carrier_fault=1 for the same carrier within
    the window. Never claims causality - the reason states only that
    multiple carrier-fault orders were observed for that carrier, not
    that the carrier caused anything."""
    tz = tz_of(clock)
    snapshot = clock.now()
    cutoff = snapshot - timedelta(days=window_days)
    window_desc = f"{window_days}d"

    by_carrier: dict[str, list[str]] = {}
    accounts: dict[str, set[str]] = {}
    for order in search_orders(conn, auth, tz):
        if not order.carrier_fault or order.booked_at < cutoff:
            continue
        by_carrier.setdefault(order.carrier, []).append(order.order_id)
        accounts.setdefault(order.carrier, set()).add(order.account_id)

    alerts: list[AlertCandidate] = []
    for carrier, order_ids in by_carrier.items():
        if len(order_ids) < threshold:
            continue
        alert_id = compute_alert_id(
            AlertType.CARRIER_PATTERN, window_desc, _CARRIER_RULE_VERSION, order_ids
        )
        alerts.append(
            AlertCandidate(
                alert_id=alert_id,
                alert_type=AlertType.CARRIER_PATTERN,
                severity=AlertSeverity.MEDIUM,
                title=f"Multiple carrier-fault orders for {carrier}",
                reason=(
                    f"{len(order_ids)} orders associated with carrier {carrier} were observed "
                    "with carrier_fault recorded, at or above the threshold of "
                    f"{threshold} within {window_days} days."
                ),
                observed_count=len(order_ids),
                threshold=threshold,
                time_window=window_desc,
                representative_records=sorted(order_ids),
                affected_accounts=sorted(accounts[carrier]),
                evidence=[cite_structured("orders", oid) for oid in sorted(order_ids)],
                recommended_next_step=f"Review {carrier}'s recent pickup performance with ops.",
                trust_state=TrustState.CONFIDENT,
                rule_version=_CARRIER_RULE_VERSION,
            )
        )
    return alerts


def detect_overdue_pickups(
    conn: sqlite3.Connection, auth: AuthContext, clock: SnapshotClock
) -> list[AlertCandidate]:
    """A BOOKED order whose pickup window has already ended with no
    recorded pickup and no cancellation - a point-in-time operational
    anomaly, one alert per affected order (same shape as detect_sla_
    breaches). Flags that a service credit may be owed without computing
    the entitlement itself - that determination belongs to calculate_
    support_outcome's service_credit calculation, not to detection."""
    tz = tz_of(clock)
    snapshot = clock.now()
    alerts: list[AlertCandidate] = []
    for order in search_orders(conn, auth, tz, status=OrderStatus.BOOKED):
        if order.pickup_actual_at is not None:
            continue
        if order.pickup_window_end >= snapshot:
            continue  # window hasn't elapsed yet
        hours_overdue = (snapshot - order.pickup_window_end).total_seconds() / 3600

        alert_id = compute_alert_id(
            AlertType.OVERDUE_PICKUP, "point-in-time", _OVERDUE_PICKUP_RULE_VERSION,
            [order.order_id],
        )
        alerts.append(
            AlertCandidate(
                alert_id=alert_id,
                alert_type=AlertType.OVERDUE_PICKUP,
                severity=AlertSeverity.HIGH if order.carrier_fault else AlertSeverity.MEDIUM,
                title=f"Overdue pickup: {order.order_id}",
                reason=(
                    f"{order.order_id}'s pickup window ended {hours_overdue:.1f} hours ago "
                    "with no recorded pickup and no cancellation."
                ),
                observed_count=1,
                threshold=1,
                time_window="point-in-time (dataset snapshot)",
                representative_records=[order.order_id],
                affected_accounts=[order.account_id],
                evidence=[cite_structured("orders", order.order_id)],
                recommended_next_step=(
                    "A service credit may be due - check via calculate_support_outcome "
                    "(service_credit)."
                ),
                trust_state=TrustState.CONFIDENT,
                rule_version=_OVERDUE_PICKUP_RULE_VERSION,
            )
        )
    return alerts
