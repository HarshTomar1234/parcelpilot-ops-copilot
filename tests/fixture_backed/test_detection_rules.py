"""Deterministic Operations Radar detection rules (Phase 5 s4-7, s13).
Every fact asserted here was verified by actually running the rules
against the fixture DB first - see app/detection/rules.py.
"""

from __future__ import annotations

from app.detection.models import AlertType
from app.detection.rules import (
    detect_carrier_patterns,
    detect_known_issue_patterns,
    detect_overdue_pickups,
    detect_recurring_severity,
    detect_sla_approaching,
    detect_sla_breaches,
)
from app.domain.outcomes import TrustState
from tests.fixtures.seed_fixture_db import FIXTURE_AGREEMENT_OVERRIDES, FIXTURE_DEFAULT_SOURCE

_REGISTRY = {"overrides": FIXTURE_AGREEMENT_OVERRIDES, "defaults": FIXTURE_DEFAULT_SOURCE}


# ---------------------------------------------------------------------------
# SLA breach / approaching
# ---------------------------------------------------------------------------


def test_sla_breach_detects_confirmed_p1_breaches(conn, auth, clock):
    alerts = detect_sla_breaches(conn, auth, clock, **_REGISTRY)
    ids = {a.representative_records[0] for a in alerts}
    assert ids == {"FXT-501", "FXT-505"}
    for alert in alerts:
        assert alert.alert_type is AlertType.SLA_BREACH
        assert alert.trust_state is TrustState.CONFIDENT
        assert alert.threshold == 1
        assert alert.observed_count == 1
        assert alert.evidence


def test_sla_breach_omits_business_hour_targets_rather_than_guessing(conn, auth, clock):
    # FXT-502/503/504 are P2/P3 with business-hour targets (CONDITIONAL,
    # not exactly computable) - none should ever appear as a breach alert.
    alerts = detect_sla_breaches(conn, auth, clock, **_REGISTRY)
    ids = {a.representative_records[0] for a in alerts}
    assert "FXT-502" not in ids
    assert "FXT-503" not in ids
    assert "FXT-504" not in ids


def test_sla_approaching_finds_nothing_when_no_ticket_is_in_the_warning_window(conn, auth, clock):
    # Both real breach tickets are already past deadline (elapsed > 0),
    # not "approaching" - and no fixture ticket sits in the warning zone.
    alerts = detect_sla_approaching(conn, auth, clock, **_REGISTRY)
    assert alerts == []


# ---------------------------------------------------------------------------
# Recurring severity
# ---------------------------------------------------------------------------


def test_recurring_severity_fires_at_threshold(conn, auth, clock):
    alerts = detect_recurring_severity(conn, auth, clock, **_REGISTRY)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.alert_type is AlertType.RECURRING_ISSUE
    assert alert.observed_count == 2
    assert alert.threshold == 2
    assert set(alert.representative_records) == {"FXT-501", "FXT-505"}
    assert set(alert.affected_accounts) == {"FX-001", "FX-004"}


def test_recurring_severity_below_threshold_produces_no_alert(conn, auth, clock):
    alerts = detect_recurring_severity(conn, auth, clock, threshold=3, **_REGISTRY)
    assert alerts == []


def test_recurring_severity_outside_window_produces_no_alert(conn, auth, clock):
    alerts = detect_recurring_severity(conn, auth, clock, window_days=0, **_REGISTRY)
    assert alerts == []


# ---------------------------------------------------------------------------
# Known issue pattern
# ---------------------------------------------------------------------------


def _insert_known_issue_and_matching_ticket(conn) -> None:
    """Uncommitted, connection-local inserts - never persisted past this
    test's connection close (see conftest.py's function-scoped conn
    fixture), same pattern as the Phase 4 document-injection tests."""
    cur = conn.execute(
        "INSERT INTO document_chunks (chunk_id, source_id, page, section, text, "
        "normalized_text, filename, status, source_type, account_scope, "
        "effective_date, authority_class) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "FIX-04:p1:injected", "FIX-04", 1, "3",
            "Current known issues\nKI-901 - Label printing timeout\nOpened: 1 February 2026\n"
            "Status: Investigating\nSome customers report label printing requests timing out "
            "after 30 seconds during peak hours.",
            "label printing timeout",
            "fixture_product_guide.pdf", "CURRENT", "product_doc", None,
            "2026-01-20", "PRODUCT_DOC",
        ),
    )
    conn.execute(
        "INSERT INTO document_chunks_fts (rowid, normalized_text) VALUES (?, ?)",
        (cur.lastrowid, "label printing timeout"),
    )
    conn.execute(
        "INSERT INTO tickets (ticket_id, account_id, created_at, status, subject, "
        "description, channel, assigned_to, last_customer_message_at, "
        "historical_resolution) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "FXT-901", "FX-001", "2026-02-02T08:00:00+05:30", "open",
            "Label printing keeps timing out",
            "Every label print request has been timing out for the last hour during peak hours.",
            "chat", "Fixture Agent 1", "2026-02-02T08:05:00+05:30", None,
        ),
    )


def test_known_issue_pattern_links_active_issue_to_matching_open_ticket(conn, auth, clock):
    _insert_known_issue_and_matching_ticket(conn)
    alerts = detect_known_issue_patterns(conn, auth, clock)
    matching = [a for a in alerts if "FXT-901" in a.representative_records]
    assert len(matching) == 1
    alert = matching[0]
    assert alert.alert_type is AlertType.KNOWN_ISSUE_PATTERN
    assert "KI-901" in alert.title
    assert any(e.note == "KI-901" for e in alert.evidence)


def test_resolved_known_issue_never_produces_an_alert(conn, auth, clock):
    # FIX-04's own fixture text has no KI- reference at all in the base
    # seed, so this proves the negative path structurally: a resolved
    # issue's segment is excluded before matching is even attempted.
    cur = conn.execute(
        "INSERT INTO document_chunks (chunk_id, source_id, page, section, text, "
        "normalized_text, filename, status, source_type, account_scope, "
        "effective_date, authority_class) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "FIX-04:p1:resolved", "FIX-04", 1, "4",
            "Resolved issue\nKI-900 - Label printing timeout: Resolved 1 January 2026. "
            "Do not use this resolved issue to explain new incidents unless evidence "
            "specifically matches it.",
            "resolved label printing",
            "fixture_product_guide.pdf", "CURRENT", "product_doc", None,
            "2026-01-20", "PRODUCT_DOC",
        ),
    )
    conn.execute(
        "INSERT INTO document_chunks_fts (rowid, normalized_text) VALUES (?, ?)",
        (cur.lastrowid, "resolved label printing"),
    )
    conn.execute(
        "INSERT INTO tickets (ticket_id, account_id, created_at, status, subject, "
        "description, channel, assigned_to, last_customer_message_at, "
        "historical_resolution) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            "FXT-900", "FX-001", "2026-02-02T08:00:00+05:30", "open",
            "Label printing keeps timing out",
            "Every label print request has been timing out for the last hour.",
            "chat", "Fixture Agent 1", "2026-02-02T08:05:00+05:30", None,
        ),
    )
    alerts = detect_known_issue_patterns(conn, auth, clock)
    assert not any("KI-900" in a.title for a in alerts)


def test_unrelated_ticket_does_not_match_an_unrelated_known_issue(conn, auth, clock):
    _insert_known_issue_and_matching_ticket(conn)
    alerts = detect_known_issue_patterns(conn, auth, clock)
    ki_901_alert = next(a for a in alerts if "KI-901" in a.title)
    # FXT-503 (billing contact question, real fixture seed data) shares no
    # meaningful vocabulary with KI-901's label-printing description.
    assert "FXT-503" not in ki_901_alert.representative_records


# ---------------------------------------------------------------------------
# Carrier pattern
# ---------------------------------------------------------------------------


def test_carrier_pattern_below_threshold_produces_no_alert(conn, auth, clock):
    # Only FXO-2002 has carrier_fault=1 in the base fixture seed.
    alerts = detect_carrier_patterns(conn, auth, clock)
    assert alerts == []


def test_carrier_pattern_fires_once_threshold_is_reached(conn, auth, clock):
    # Same real data, a lower threshold - proves the mechanism fires
    # correctly once the count actually reaches it, without needing to
    # fabricate more fixture orders.
    alerts = detect_carrier_patterns(conn, auth, clock, threshold=1)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.alert_type is AlertType.CARRIER_PATTERN
    assert alert.observed_count == 1
    assert "FXO-2002" in alert.representative_records
    # Never claims causality.
    assert "caused" not in alert.reason.lower()
    assert "observed" in alert.reason.lower()


def test_overdue_pickup_detects_a_booked_order_past_its_window(conn, auth, clock):
    alerts = detect_overdue_pickups(conn, auth, clock)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.alert_type == AlertType.OVERDUE_PICKUP
    assert alert.representative_records == ["FXO-2002"]
    assert alert.affected_accounts == ["FX-002"]
    # carrier_fault=1 on FXO-2002 - severity reflects that.
    assert alert.severity.value == "high"
    assert "service credit" in alert.recommended_next_step.lower()


def test_overdue_pickup_excludes_orders_still_within_their_window(conn, auth, clock):
    alerts = detect_overdue_pickups(conn, auth, clock)
    ids = {a.representative_records[0] for a in alerts}
    # FXO-1001/2001/3001 all have a pickup_window_end after the snapshot.
    assert "FXO-1001" not in ids
    assert "FXO-2001" not in ids
    assert "FXO-3001" not in ids


def test_carrier_pattern_uses_a_documented_configurable_threshold(conn, auth, clock):
    from app.detection.rules import DEFAULT_CARRIER_FAULT_THRESHOLD

    assert DEFAULT_CARRIER_FAULT_THRESHOLD == 2
    default_alerts = detect_carrier_patterns(conn, auth, clock)
    custom_alerts = detect_carrier_patterns(
        conn, auth, clock, threshold=DEFAULT_CARRIER_FAULT_THRESHOLD
    )
    assert [a.alert_id for a in default_alerts] == [a.alert_id for a in custom_alerts]
