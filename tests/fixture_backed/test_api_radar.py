"""POST /api/radar/run, GET /api/radar/alerts/{id} against the fixture
corpus (Phase 6 s25). Unlike chat, radar's policy registry IS injected
here (via the client fixture's get_policy_registry override), so these
assert on real alert content, not just shape - the fixture corpus is
known to produce a real overdue_pickup alert (test_detection_rules.py
already proves this at the rule level; this proves the API wiring on top
of it doesn't lose or reshape it).
"""

from __future__ import annotations


def test_radar_run_returns_deterministic_alerts_for_an_unrestricted_caller(client):
    resp = client.post("/api/radar/run", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_alerts"] == len(body["alerts"])
    assert body["viewed_as"]["id"] == "ops_admin"
    assert any(a["alert_type"] == "overdue_pickup" for a in body["alerts"])


def test_radar_run_filters_to_the_requested_alert_type(client):
    resp = client.post("/api/radar/run", json={"alert_types": ["overdue_pickup"]})
    assert resp.status_code == 200
    types = {a["alert_type"] for a in resp.json()["alerts"]}
    assert types <= {"overdue_pickup"}


def test_restricted_support_is_denied_radar_entirely(client):
    resp = client.post(
        "/api/radar/run", json={}, headers={"X-Demo-User": "restricted_support"}
    )
    assert resp.status_code == 403
    assert "operations_admin" in resp.json()["detail"]


def test_scoped_support_agent_never_sees_another_accounts_alert(client):
    resp = client.post(
        "/api/radar/run", json={}, headers={"X-Demo-User": "support_agent"}
    )
    assert resp.status_code == 200
    for alert in resp.json()["alerts"]:
        assert set(alert["affected_accounts"]) <= {"FX-001"}


def test_group_by_account_is_omitted_unless_requested(client):
    resp = client.post("/api/radar/run", json={"group_by_account": False})
    assert resp.json()["grouped_by_account"] is None

    resp = client.post("/api/radar/run", json={"group_by_account": True})
    grouped = resp.json()["grouped_by_account"]
    assert grouped is not None
    assert set(grouped) <= {"FX-001", "FX-002", "FX-003", "FX-004"}


def test_get_alert_by_id_returns_404_for_an_unknown_alert(client):
    resp = client.get("/api/radar/alerts/ALERT-doesnotexist")
    assert resp.status_code == 404


def test_get_alert_by_id_returns_a_real_alert(client):
    listing = client.post("/api/radar/run", json={}).json()
    alert_id = listing["alerts"][0]["alert_id"]
    resp = client.get(f"/api/radar/alerts/{alert_id}")
    assert resp.status_code == 200
    assert resp.json()["alert_id"] == alert_id


def test_window_days_out_of_range_is_rejected(client):
    resp = client.post("/api/radar/run", json={"window_days": 0})
    assert resp.status_code == 422
