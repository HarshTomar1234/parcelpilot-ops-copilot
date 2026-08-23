"""Red team s12: invalid input and resource abuse at the HTTP request
boundary. Bounded validation only - no WAF, no rate limiter, nothing
beyond what pydantic's typed request models already enforce.
"""

from __future__ import annotations

import json

import pytest


def test_extremely_long_chat_question_is_rejected_at_the_boundary(client):
    resp = client.post("/api/chat", json={"question": "x" * 3000})
    assert resp.status_code == 422


def test_enormous_reason_is_rejected_at_the_boundary(client):
    resp = client.post(
        "/api/actions/prepare", json={"ticket_id": "FXT-501", "reason": "x" * 1000}
    )
    assert resp.status_code == 422


def test_invalid_json_body_is_a_clean_422_not_a_crash(client):
    resp = client.post(
        "/api/chat", content=b"{not valid json", headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 422


def test_invalid_enum_value_for_calculation_type_equivalent_alert_type(client):
    resp = client.post("/api/radar/run", json={"alert_types": ["not_a_real_type"]})
    assert resp.status_code == 422


def test_huge_radar_window_is_rejected_by_the_bound(client):
    resp = client.post("/api/radar/run", json={"window_days": 999999})
    assert resp.status_code == 422


def test_negative_radar_window_is_rejected(client):
    resp = client.post("/api/radar/run", json={"window_days": -1})
    assert resp.status_code == 422


def test_zero_radar_window_is_rejected(client):
    resp = client.post("/api/radar/run", json={"window_days": 0})
    assert resp.status_code == 422


def test_malformed_action_id_types_are_rejected_not_crashed_on(client):
    resp = client.post("/api/actions/execute", json={"action_id": 12345})
    assert resp.status_code == 422
    resp = client.post("/api/actions/execute", json={"action_id": None})
    assert resp.status_code == 422
    resp = client.post("/api/actions/execute", json={"action_id": ["ACT-1"]})
    assert resp.status_code == 422


def test_repeated_rapid_requests_do_not_crash_the_process(client):
    for _ in range(30):
        resp = client.get("/health")
        assert resp.status_code == 200


def test_empty_question_is_rejected(client):
    resp = client.post("/api/chat", json={"question": ""})
    assert resp.status_code == 422


def test_whitespace_only_question_passes_validation_but_resolves_to_no_evidence(client):
    """min_length=1 lets whitespace through pydantic - the agent itself
    is the real safety net here, and it must not crash or fabricate."""
    resp = client.post("/api/chat", json={"question": "   \n\t  "})
    assert resp.status_code == 200
    assert resp.json()["result"]["status"] == "insufficient_evidence"


def test_missing_required_fields_are_422_not_500(client):
    resp = client.post("/api/chat", json={})
    assert resp.status_code == 422
    resp = client.post("/api/actions/prepare", json={"reason": "only reason, no ticket_id"})
    assert resp.status_code == 422
    resp = client.post("/api/actions/confirm", json={"action_id": "ACT-1"})
    assert resp.status_code == 422


def test_unicode_and_control_characters_in_question_do_not_crash(client):
    resp = client.post(
        "/api/chat", json={"question": "What is \x00\x01\x02 the SLA ‮\U0001f600 for FXT-501?"}
    )
    assert resp.status_code == 200


def test_deeply_nested_or_oversized_json_body_is_rejected_cleanly(client):
    resp = client.post("/api/actions/prepare", json={"ticket_id": "x" * 200, "reason": "y"})
    assert resp.status_code == 422


@pytest.mark.parametrize("field", ["question"])
def test_wrong_type_for_string_field_is_a_validation_error(client, field):
    resp = client.post("/api/chat", json={field: 12345})
    assert resp.status_code == 422


def test_content_type_mismatch_is_handled_without_a_crash(client):
    resp = client.post(
        "/api/chat", content=json.dumps({"question": "hello"}),
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status_code in {200, 415, 422}
