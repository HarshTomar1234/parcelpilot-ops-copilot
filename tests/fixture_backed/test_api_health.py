"""API health/readiness and demo-identity listing (Phase 6 s16, s25).
"""

from __future__ import annotations


def test_health_returns_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_reports_database_and_snapshot_present(client):
    resp = client.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database_file_present": True, "dataset_snapshot_present": True}
    assert body["dataset_snapshot"] is not None


def test_demo_users_lists_all_three_roles(client):
    resp = client.get("/api/demo-users")
    assert resp.status_code == 200
    ids = {u["id"] for u in resp.json()}
    assert ids == {"ops_admin", "support_agent", "restricted_support"}


def test_root_serves_the_ui_shell(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_unknown_demo_identity_is_rejected(client):
    # /api/demo-users itself doesn't resolve an identity (it lists them);
    # use a route that does, e.g. radar.
    resp = client.post(
        "/api/radar/run", json={}, headers={"X-Demo-User": "nonexistent"}
    )
    assert resp.status_code == 400
