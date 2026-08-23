"""Deterministic alert IDs (Phase 5 s8). The same underlying evidence,
window, and rule version must always produce the same alert_id, so
calling detection repeatedly against unchanged data never creates
duplicate alerts.
"""

from __future__ import annotations

from app.detection.fingerprint import compute_alert_id
from app.detection.models import AlertType
from app.detection.rules import detect_recurring_severity, detect_sla_breaches
from tests.fixtures.seed_fixture_db import FIXTURE_AGREEMENT_OVERRIDES, FIXTURE_DEFAULT_SOURCE

_REGISTRY = {"overrides": FIXTURE_AGREEMENT_OVERRIDES, "defaults": FIXTURE_DEFAULT_SOURCE}


def test_same_inputs_produce_the_same_fingerprint():
    id1 = compute_alert_id(AlertType.SLA_BREACH, "point-in-time", "v1", ["FXT-501"])
    id2 = compute_alert_id(AlertType.SLA_BREACH, "point-in-time", "v1", ["FXT-501"])
    assert id1 == id2


def test_different_rule_version_changes_the_fingerprint():
    id_v1 = compute_alert_id(AlertType.SLA_BREACH, "point-in-time", "v1", ["FXT-501"])
    id_v2 = compute_alert_id(AlertType.SLA_BREACH, "point-in-time", "v2", ["FXT-501"])
    assert id_v1 != id_v2


def test_entity_set_order_does_not_change_the_fingerprint():
    id_a = compute_alert_id(AlertType.RECURRING_ISSUE, "30d", "v1", ["FXT-501", "FXT-505"])
    id_b = compute_alert_id(AlertType.RECURRING_ISSUE, "30d", "v1", ["FXT-505", "FXT-501"])
    assert id_a == id_b


def test_repeated_detection_runs_produce_identical_alert_ids(conn, auth, clock):
    run1 = [a.alert_id for a in detect_sla_breaches(conn, auth, clock, **_REGISTRY)]
    run2 = [a.alert_id for a in detect_sla_breaches(conn, auth, clock, **_REGISTRY)]
    run3 = [a.alert_id for a in detect_recurring_severity(conn, auth, clock, **_REGISTRY)]
    run4 = [a.alert_id for a in detect_recurring_severity(conn, auth, clock, **_REGISTRY)]
    assert run1 == run2
    assert run1  # non-vacuous: the fixture genuinely produces SLA breach alerts
    assert run3 == run4
    assert run3


def test_no_duplicate_alert_ids_within_a_single_run(conn, auth, clock):
    alerts = detect_sla_breaches(conn, auth, clock, **_REGISTRY)
    ids = [a.alert_id for a in alerts]
    assert len(ids) == len(set(ids))
