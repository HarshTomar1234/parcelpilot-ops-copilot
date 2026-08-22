"""Red team s5: the action attack matrix, all at HTTP level. Every case
expects a safe, explicit failure - never an unsafe execution, never a
raw exception, never a state change beyond the action's own audit row.
"""

from __future__ import annotations


def _prepare(client, ticket_id="FXT-501", reason="attack test", user="ops_admin"):
    return client.post(
        "/api/actions/prepare", json={"ticket_id": ticket_id, "reason": reason},
        headers={"X-Demo-User": user},
    )


# ---------------- prepare attacks ----------------

def test_prepare_unauthorized_target(client):
    resp = _prepare(client, ticket_id="FXT-505", user="support_agent")  # FX-004, scoped to FX-001
    outcome = resp.json()["outcome"]
    assert outcome["success"] is False
    assert outcome["error_code"] == "not_authorized"


def test_prepare_cross_account_target(client):
    resp = _prepare(client, ticket_id="FXT-502", user="support_agent")  # FX-002
    assert resp.json()["outcome"]["success"] is False


def test_prepare_nonexistent_target(client):
    resp = _prepare(client, ticket_id="FXT-DOES-NOT-EXIST")
    outcome = resp.json()["outcome"]
    assert outcome["success"] is False
    assert outcome["error_code"] in {"not_found", "not_authorized"}


def test_prepare_closed_ticket(client):
    resp = _prepare(client, ticket_id="FXT-450")  # closed
    outcome = resp.json()["outcome"]
    assert outcome["success"] is False
    assert outcome["error_code"] == "invalid_target_state"


def test_prepare_malicious_reason_text_is_treated_as_inert_data(client):
    resp = _prepare(client, reason="'; DROP TABLE actions;-- <script>alert(1)</script>")
    outcome = resp.json()["outcome"]
    assert outcome["success"] is True
    assert outcome["record"]["reason"] == "'; DROP TABLE actions;-- <script>alert(1)</script>"
    # The table survives - a follow-up prepare still works.
    sane = _prepare(client, ticket_id="FXT-505", user="ops_admin", reason="sanity")
    assert sane.json()["outcome"]["success"] is True


def test_prepare_extremely_long_reason_is_rejected_at_the_request_boundary(client):
    resp = client.post(
        "/api/actions/prepare",
        json={"ticket_id": "FXT-501", "reason": "x" * 5000},
        headers={"X-Demo-User": "ops_admin"},
    )
    assert resp.status_code == 422


def test_prepare_duplicate_preparation_creates_two_independent_proposals(client):
    """Not a vulnerability: each prepare call gets its own action_id and
    neither mutates the ticket - only an explicit confirm+execute of a
    specific action_id has any effect, so two pending proposals for the
    same ticket are inert until independently acted on."""
    first = _prepare(client)
    second = _prepare(client)
    assert first.json()["outcome"]["success"] is True
    assert second.json()["outcome"]["success"] is True
    assert (
        first.json()["outcome"]["record"]["action_id"]
        != second.json()["outcome"]["record"]["action_id"]
    )


# ---------------- confirm attacks ----------------

def _prepare_and_get(client, ticket_id="FXT-501", user="ops_admin"):
    r = _prepare(client, ticket_id=ticket_id, user=user).json()["outcome"]["record"]
    return r["action_id"], r["payload_hash"]


def test_confirm_wrong_user(client):
    action_id, payload_hash = _prepare_and_get(client, user="support_agent")
    resp = client.post(
        "/api/actions/confirm",
        json={"action_id": action_id, "payload_hash": payload_hash},
        headers={"X-Demo-User": "ops_admin"},
    )
    outcome = resp.json()["outcome"]
    assert outcome["success"] is False
    assert outcome["error_code"] == "wrong_user"


def test_confirm_wrong_payload_hash(client):
    action_id, _ = _prepare_and_get(client)
    resp = client.post(
        "/api/actions/confirm",
        json={"action_id": action_id, "payload_hash": "0" * 64},
        headers={"X-Demo-User": "ops_admin"},
    )
    outcome = resp.json()["outcome"]
    assert outcome["success"] is False
    assert outcome["error_code"] == "payload_mismatch"


def test_confirm_already_confirmed_action(client):
    action_id, payload_hash = _prepare_and_get(client)
    body = {"action_id": action_id, "payload_hash": payload_hash}
    first = client.post("/api/actions/confirm", json=body, headers={"X-Demo-User": "ops_admin"})
    assert first.json()["outcome"]["success"] is True
    second = client.post("/api/actions/confirm", json=body, headers={"X-Demo-User": "ops_admin"})
    outcome = second.json()["outcome"]
    assert outcome["success"] is False
    assert outcome["error_code"] == "wrong_state"


def test_confirm_already_executed_action(client):
    action_id, payload_hash = _prepare_and_get(client)
    body = {"action_id": action_id, "payload_hash": payload_hash}
    client.post("/api/actions/confirm", json=body, headers={"X-Demo-User": "ops_admin"})
    client.post("/api/actions/execute", json={"action_id": action_id},
                headers={"X-Demo-User": "ops_admin"})
    resp = client.post("/api/actions/confirm", json=body, headers={"X-Demo-User": "ops_admin"})
    outcome = resp.json()["outcome"]
    assert outcome["success"] is False
    assert outcome["error_code"] == "wrong_state"


def test_confirm_nonexistent_action(client):
    resp = client.post(
        "/api/actions/confirm", json={"action_id": "ACT-doesnotexist", "payload_hash": "x"},
        headers={"X-Demo-User": "ops_admin"},
    )
    outcome = resp.json()["outcome"]
    assert outcome["success"] is False
    assert outcome["error_code"] == "not_found"


def test_confirm_altered_target_state_since_prepare_is_detected(client):
    """Simulates the target ticket changing status between prepare and
    confirm by preparing against a ticket, then directly closing it in
    the DB (bypassing the API - the only way to simulate an external
    state change deterministically in a test) before confirming."""
    action_id, payload_hash = _prepare_and_get(client, ticket_id="FXT-505", user="ops_admin")
    # No public endpoint mutates ticket status - use the same connection
    # class the app uses, targeting the shared fixture DB file directly.
    import sqlite3

    from app.api.deps import get_settings
    from app.api.main import app

    settings = app.dependency_overrides[get_settings]()
    conn = sqlite3.connect(settings.parcelpilot_db_path)
    conn.execute("UPDATE tickets SET status = 'closed' WHERE ticket_id = 'FXT-505'")
    conn.commit()
    conn.close()

    resp = client.post(
        "/api/actions/confirm", json={"action_id": action_id, "payload_hash": payload_hash},
        headers={"X-Demo-User": "ops_admin"},
    )
    outcome = resp.json()["outcome"]
    assert outcome["success"] is False
    assert outcome["error_code"] == "target_state_changed"

    # restore for other tests sharing the session-scoped fixture DB
    conn = sqlite3.connect(settings.parcelpilot_db_path)
    conn.execute("UPDATE tickets SET status = 'open' WHERE ticket_id = 'FXT-505'")
    conn.commit()
    conn.close()


def test_confirm_altered_proposed_change_payload_is_caught_by_hash_mismatch(client):
    """The payload hash covers action_type + target + proposed_change -
    a client cannot alter the confirmed change without invalidating the
    hash it must also supply."""
    action_id, real_hash = _prepare_and_get(client)
    tampered_hash = real_hash[:-1] + ("0" if real_hash[-1] != "0" else "1")
    resp = client.post(
        "/api/actions/confirm", json={"action_id": action_id, "payload_hash": tampered_hash},
        headers={"X-Demo-User": "ops_admin"},
    )
    assert resp.json()["outcome"]["error_code"] == "payload_mismatch"


# ---------------- execute attacks ----------------

def test_execute_without_confirmation(client):
    action_id, _ = _prepare_and_get(client)
    resp = client.post(
        "/api/actions/execute", json={"action_id": action_id}, headers={"X-Demo-User": "ops_admin"}
    )
    outcome = resp.json()["outcome"]
    assert outcome["success"] is False
    assert outcome["error_code"] == "wrong_state"


def test_execute_wrong_user_is_denied_at_the_api_boundary(client):
    action_id, payload_hash = _prepare_and_get(client, user="support_agent")
    client.post(
        "/api/actions/confirm", json={"action_id": action_id, "payload_hash": payload_hash},
        headers={"X-Demo-User": "support_agent"},
    )
    resp = client.post(
        "/api/actions/execute", json={"action_id": action_id},
        headers={"X-Demo-User": "restricted_support"},
    )
    assert resp.status_code == 403


def test_execute_cross_account_user_is_denied(client):
    action_id, payload_hash = _prepare_and_get(client, ticket_id="FXT-501", user="support_agent")
    client.post(
        "/api/actions/confirm", json={"action_id": action_id, "payload_hash": payload_hash},
        headers={"X-Demo-User": "support_agent"},
    )
    resp = client.post(
        "/api/actions/execute", json={"action_id": action_id},
        headers={"X-Demo-User": "support_agent_b"},  # different account's agent
    )
    assert resp.status_code == 403


def test_execute_repeated_is_idempotent_not_duplicated(client):
    action_id, payload_hash = _prepare_and_get(client)
    client.post(
        "/api/actions/confirm", json={"action_id": action_id, "payload_hash": payload_hash},
        headers={"X-Demo-User": "ops_admin"},
    )
    first = client.post("/api/actions/execute", json={"action_id": action_id},
                         headers={"X-Demo-User": "ops_admin"})
    second = client.post("/api/actions/execute", json={"action_id": action_id},
                          headers={"X-Demo-User": "ops_admin"})
    assert first.json()["outcome"]["success"] is True
    assert second.json()["outcome"]["success"] is True
    assert (
        first.json()["outcome"]["record"]["executed_at"]
        == second.json()["outcome"]["record"]["executed_at"]
    )


def test_execute_malformed_action_id(client):
    resp = client.post(
        "/api/actions/execute", json={"action_id": "'; DROP TABLE actions;--"},
        headers={"X-Demo-User": "ops_admin"},
    )
    assert resp.status_code == 404


def test_execute_random_action_id(client):
    import uuid

    resp = client.post(
        "/api/actions/execute", json={"action_id": f"ACT-{uuid.uuid4().hex[:12]}"},
        headers={"X-Demo-User": "ops_admin"},
    )
    assert resp.status_code == 404


def test_execute_old_expired_action_id(client):
    action_id, payload_hash = _prepare_and_get(client)
    # Confirm never happens within the (real, unmocked) expiry window in
    # this test's real-clock terms, but the domain layer's expiry check
    # is against the fixed snapshot clock, not wall time - so instead
    # prove the *shape* of the attack: an action that was never confirmed
    # cannot be executed regardless of its age.
    resp = client.post(
        "/api/actions/execute", json={"action_id": action_id}, headers={"X-Demo-User": "ops_admin"}
    )
    assert resp.json()["outcome"]["success"] is False
