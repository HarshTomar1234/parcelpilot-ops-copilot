"""POST /api/chat against the fixture corpus (Phase 6 s25). Scope note:
app/agent/tools.py always uses production policy registries (never the
fixture ones) - the same documented, deliberate decision
tests/fixture_backed/test_agent_orchestrator.py already relies on - so
these assert on architecture-level behavior (status, shape, propagated
identity/snapshot), not exact fee/SLA outcomes.
"""

from __future__ import annotations


def test_chat_returns_a_structured_result_with_request_and_trace_ids(client):
    resp = client.post("/api/chat", json={"question": "What severity is FXT-501?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["status"] in {
        "completed", "needs_clarification", "insufficient_evidence",
        "escalated", "failed", "evidence_validation_failed",
    }
    assert body["result"]["request_id"]
    assert body["result"]["trace_id"]
    assert body["viewed_as"]["id"] == "ops_admin"
    assert body["dataset_snapshot"]


def test_chat_propagates_the_selected_demo_identity(client):
    resp = client.post(
        "/api/chat", json={"question": "hello"}, headers={"X-Demo-User": "support_agent"}
    )
    assert resp.status_code == 200
    assert resp.json()["viewed_as"]["id"] == "support_agent"
    assert resp.json()["viewed_as"]["account_scope"] == ["FX-001"]


def test_chat_rejects_an_empty_question_at_the_request_boundary(client):
    resp = client.post("/api/chat", json={"question": ""})
    assert resp.status_code == 422  # pydantic min_length, never reaches run_agent()


def test_chat_response_never_leaks_a_raw_exception(client):
    resp = client.post("/api/chat", json={"question": "   "})
    assert resp.status_code == 200
    body = resp.json()["result"]
    assert body["status"] == "insufficient_evidence"
    assert "Traceback" not in str(body)
