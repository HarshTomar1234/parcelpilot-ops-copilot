"""POST /api/actions/{prepare,confirm,execute}, GET /api/actions/{id}
against the fixture corpus (Phase 6 s25-26). Unlike chat, the actions
routes inject the fixture policy registry (client fixture's
get_policy_registry override), so FXT-501 - already proven P1/breached at
the workflow-function level in test_action_workflow.py - genuinely
reaches PENDING_CONFIRMATION here too, exercising the real
prepare -> confirm -> execute chain end to end through the HTTP layer.
"""

from __future__ import annotations


def test_prepare_confirm_execute_happy_path(client):
    prep = client.post(
        "/api/actions/prepare", json={"ticket_id": "FXT-501", "reason": "P1 breach via API test"}
    )
    assert prep.status_code == 200
    outcome = prep.json()["outcome"]
    assert outcome["success"] is True
    record = outcome["record"]
    assert record["status"] == "PENDING_CONFIRMATION"
    assert record["evidence"]

    confirm = client.post(
        "/api/actions/confirm",
        json={"action_id": record["action_id"], "payload_hash": record["payload_hash"]},
    )
    assert confirm.status_code == 200
    confirmed = confirm.json()["outcome"]
    assert confirmed["success"] is True
    assert confirmed["record"]["status"] == "CONFIRMED"

    execute = client.post("/api/actions/execute", json={"action_id": record["action_id"]})
    assert execute.status_code == 200
    executed = execute.json()["outcome"]
    assert executed["success"] is True
    assert executed["record"]["status"] == "EXECUTED"
    assert executed["record"]["executed_at"]

    # idempotent - calling execute again returns the same terminal state
    again = client.post("/api/actions/execute", json={"action_id": record["action_id"]})
    assert again.status_code == 200
    assert again.json()["outcome"]["record"]["status"] == "EXECUTED"


def test_prepare_rejects_a_closed_ticket_deterministically(client):
    resp = client.post(
        "/api/actions/prepare", json={"ticket_id": "FXT-450", "reason": "test"}
    )
    assert resp.status_code == 200  # a business outcome, not an HTTP error
    outcome = resp.json()["outcome"]
    assert outcome["success"] is False
    assert outcome["error_code"] == "invalid_target_state"


def test_prepare_denies_a_cross_account_ticket_for_a_scoped_caller(client):
    resp = client.post(
        "/api/actions/prepare",
        json={"ticket_id": "FXT-505", "reason": "test"},  # FX-004, not FX-001
        headers={"X-Demo-User": "support_agent"},
    )
    assert resp.status_code == 200
    outcome = resp.json()["outcome"]
    assert outcome["success"] is False
    assert outcome["error_code"] == "not_authorized"


def test_confirm_unknown_action_returns_not_found_outcome(client):
    resp = client.post(
        "/api/actions/confirm", json={"action_id": "ACT-doesnotexist", "payload_hash": "x"}
    )
    assert resp.status_code == 200
    outcome = resp.json()["outcome"]
    assert outcome["success"] is False
    assert outcome["error_code"] == "not_found"


def test_only_the_preparing_user_or_admin_can_execute(client):
    prep = client.post(
        "/api/actions/prepare",
        json={"ticket_id": "FXT-501", "reason": "ownership test"},
        headers={"X-Demo-User": "support_agent"},
    )
    action_id = prep.json()["outcome"]["record"]["action_id"]

    resp = client.post(
        "/api/actions/execute",
        json={"action_id": action_id},
        headers={"X-Demo-User": "restricted_support"},
    )
    assert resp.status_code == 403


def test_get_action_denies_a_non_owner_non_admin_caller(client):
    prep = client.post(
        "/api/actions/prepare",
        json={"ticket_id": "FXT-501", "reason": "read test"},
        headers={"X-Demo-User": "support_agent"},
    )
    action_id = prep.json()["outcome"]["record"]["action_id"]

    resp = client.get(
        f"/api/actions/{action_id}", headers={"X-Demo-User": "restricted_support"}
    )
    assert resp.status_code == 403

    resp = client.get(f"/api/actions/{action_id}", headers={"X-Demo-User": "ops_admin"})
    assert resp.status_code == 200


def test_get_unknown_action_is_404(client):
    resp = client.get("/api/actions/ACT-doesnotexist")
    assert resp.status_code == 404
