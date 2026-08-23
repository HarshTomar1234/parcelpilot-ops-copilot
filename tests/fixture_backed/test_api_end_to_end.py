"""One complete automated path through the API (Phase 6 s26): a support
question reaches the agent and comes back with evidence, and - as a
separate, explicit step, never automatic - a P1 ticket is escalated
through the full prepare -> confirm -> execute -> audit chain. Uses only
fixture data (FXT-501, from tests/fixtures/seed_fixture_db.py); nothing
here branches on being a real-pack assessment ID.
"""

from __future__ import annotations


def test_question_to_evidence_to_escalation_audit_trail(client):
    # 1. A support question reaches the bounded agent and gets a
    #    structured, evidence-carrying result back through the API.
    chat = client.post("/api/chat", json={"question": "Is FXT-501 within its SLA?"})
    assert chat.status_code == 200
    result = chat.json()["result"]
    assert result["status"] in {"completed", "escalated"}
    assert result["tool_calls"] > 0
    assert result["citations"]  # real evidence, not an empty answer

    # 2. Escalation is prepared - never automatic, and not derived from
    #    the chat call above (a separate, explicit action request).
    prep = client.post(
        "/api/actions/prepare",
        json={"ticket_id": "FXT-501", "reason": "confirmed P1 breach from Copilot investigation"},
    )
    assert prep.status_code == 200
    record = prep.json()["outcome"]["record"]
    assert record["status"] == "PENDING_CONFIRMATION"
    assert record["evidence"]

    # 3. Nothing happened yet - a second read of the same action shows
    #    it still pending, proving prepare alone has no side effect
    #    beyond its own audit row.
    still_pending = client.get(f"/api/actions/{record['action_id']}")
    assert still_pending.json()["outcome"]["record"]["status"] == "PENDING_CONFIRMATION"

    # 4. Explicit confirmation, then execution.
    confirm = client.post(
        "/api/actions/confirm",
        json={"action_id": record["action_id"], "payload_hash": record["payload_hash"]},
    )
    assert confirm.json()["outcome"]["record"]["status"] == "CONFIRMED"

    execute = client.post("/api/actions/execute", json={"action_id": record["action_id"]})
    executed = execute.json()["outcome"]["record"]
    assert executed["status"] == "EXECUTED"
    assert executed["confirmed_at"] is not None
    assert executed["executed_at"] is not None

    # 5. The final audit state is independently readable back.
    audit = client.get(f"/api/actions/{record['action_id']}")
    assert audit.json()["outcome"]["record"]["status"] == "EXECUTED"
