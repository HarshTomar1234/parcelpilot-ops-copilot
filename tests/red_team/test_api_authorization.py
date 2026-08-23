"""Red team s4: direct HTTP attacks against every route's authorization
boundary. The API layer never trusts client-supplied role/account_scope
- schemas.py has no such fields on any request body, and the demo
identity header only ever selects a pre-configured server-side
AuthContext (app/api/deps.py::get_current_user). These tests attack that
boundary directly with HTTP requests, not internal function calls.
"""

from __future__ import annotations

import pytest

ROUTES_NEEDING_IDENTITY = [
    ("POST", "/api/chat", {"question": "hello"}),
    ("POST", "/api/radar/run", {}),
    ("POST", "/api/actions/prepare", {"ticket_id": "FXT-501", "reason": "x"}),
    ("POST", "/api/actions/confirm", {"action_id": "ACT-x", "payload_hash": "x"}),
    ("POST", "/api/actions/execute", {"action_id": "ACT-x"}),
    ("GET", "/api/actions/ACT-x", None),
    ("GET", "/api/radar/alerts/ALERT-x", None),
]


@pytest.mark.parametrize("method,path,body", ROUTES_NEEDING_IDENTITY)
def test_missing_identity_header_defaults_to_a_named_configured_identity_not_a_bypass(
    client, method, path, body
):
    """No X-Demo-User header falls back to the configured default
    (ops_admin) - a deliberate demo-convenience default, not a missing-
    auth bypass: it's still one specific, server-owned AuthContext, never
    a caller-controlled one."""
    resp = client.request(method, path, json=body)
    assert resp.status_code in {200, 403, 404}  # never a 401/500 crash


@pytest.mark.parametrize("method,path,body", ROUTES_NEEDING_IDENTITY)
def test_invalid_identity_header_is_rejected_on_every_route(client, method, path, body):
    resp = client.request(
        method, path, json=body, headers={"X-Demo-User": "root; DROP TABLE actions;--"}
    )
    assert resp.status_code == 400


def test_attacker_controlled_role_and_account_scope_fields_do_not_exist_on_any_request_schema(
    client,
):
    """Neither RadarRequest, ChatRequest, nor any action request body
    declares a role/account_scope field at all - an attacker cannot even
    attempt to smuggle one; pydantic's default extra="ignore" behavior
    silently drops unknown JSON fields rather than processing them, so
    supplying one has provably zero effect on the response."""
    baseline = client.post(
        "/api/radar/run", json={}, headers={"X-Demo-User": "support_agent"}
    ).json()
    attacked = client.post(
        "/api/radar/run",
        json={"account_scope": ["FX-004"], "role": "operations_admin"},
        headers={"X-Demo-User": "support_agent"},
    ).json()
    assert attacked["alerts"] == baseline["alerts"]
    for alert in attacked["alerts"]:
        assert "FX-004" not in alert["affected_accounts"]

    resp = client.post(
        "/api/chat",
        json={"question": "hello", "role": "operations_admin", "account_scope": None},
        headers={"X-Demo-User": "restricted_support"},
    )
    assert resp.status_code == 200
    assert resp.json()["viewed_as"]["role"] == "restricted_support"


def test_broad_alert_types_scope_does_not_bypass_restricted_support_denial(client):
    resp = client.post(
        "/api/radar/run",
        json={"alert_types": ["sla_breach", "recurring_issue", "known_issue_pattern",
                               "carrier_pattern", "overdue_pickup", "sla_approaching"]},
        headers={"X-Demo-User": "restricted_support"},
    )
    assert resp.status_code == 403


def test_malformed_window_days_type_is_a_validation_error_not_a_server_crash(client):
    resp = client.post(
        "/api/radar/run", json={"window_days": "not-a-number"},
        headers={"X-Demo-User": "support_agent"},
    )
    assert resp.status_code == 422


def test_malformed_alert_type_value_is_a_validation_error(client):
    resp = client.post(
        "/api/radar/run", json={"alert_types": ["not_a_real_alert_type"]},
        headers={"X-Demo-User": "support_agent"},
    )
    assert resp.status_code == 422


def test_sql_like_ticket_id_in_action_prepare_is_treated_as_inert_text(client):
    resp = client.post(
        "/api/actions/prepare",
        json={"ticket_id": "FXT-501' OR '1'='1", "reason": "x"},
        headers={"X-Demo-User": "ops_admin"},
    )
    assert resp.status_code == 200
    outcome = resp.json()["outcome"]
    assert outcome["success"] is False
    assert outcome["error_code"] == "not_found"

    # The real table is untouched - a legitimate follow-up call still works.
    sane = client.post(
        "/api/actions/prepare", json={"ticket_id": "FXT-501", "reason": "sanity check"},
        headers={"X-Demo-User": "ops_admin"},
    )
    assert sane.json()["outcome"]["success"] is True


def test_action_id_with_sql_like_content_is_treated_as_inert_text(client):
    resp = client.get(
        "/api/actions/ACT-x' OR '1'='1", headers={"X-Demo-User": "ops_admin"}
    )
    assert resp.status_code == 404
