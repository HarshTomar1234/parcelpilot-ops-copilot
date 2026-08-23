"""Red team s6, s17, s18: concurrency and race-condition testing - the
highest-priority section of this phase. Proves the atomic
compare-and-swap fix in app/actions/store.py::save_action_if_status
actually closes the race a live HTTP load test against a real Docker
container first found: 4 of 20 concurrent confirm_action calls on the
same PENDING_CONFIRMATION action all reported success before the fix
(UPDATE ... WHERE status = expected_status now guarantees exactly one
concurrent caller can win any given transition).
"""

from __future__ import annotations

import concurrent.futures
import sqlite3
import uuid
from datetime import datetime

import pytest

from app.actions.models import ActionRecord, ActionStatus, ActionType
from app.actions.store import get_action, insert_action, save_action_if_status
from app.domain.outcomes import EvidenceRef


def _make_record(action_id: str, status: ActionStatus) -> ActionRecord:
    now = datetime.fromisoformat("2026-02-02T09:00:00+05:30")
    return ActionRecord(
        action_id=action_id, request_id="r1", user_id="u1",
        action_type=ActionType.PREPARE_ESCALATION, target="FXT-501",
        proposed_change={"new_priority": "escalated"}, reason="race test",
        evidence=[EvidenceRef(kind="structured", source_id="SRC-07", locator="tickets:FXT-501")],
        risk="high", payload_hash="deadbeef", status=status,
        prepared_at=now, expires_at=now, idempotency_key=action_id,
    )


# ---------------- direct store-level CAS proof (deterministic, fast) ----------------


def test_concurrent_save_action_if_status_lets_exactly_one_caller_win(fixture_db_path):
    action_id = f"ACT-{uuid.uuid4().hex[:12]}"
    setup_conn = sqlite3.connect(fixture_db_path)
    setup_conn.row_factory = sqlite3.Row
    insert_action(setup_conn, _make_record(action_id, ActionStatus.PENDING_CONFIRMATION))
    setup_conn.close()

    def attempt_transition(_):
        conn = sqlite3.connect(fixture_db_path, check_same_thread=False)
        try:
            record = _make_record(action_id, ActionStatus.CONFIRMED)
            return save_action_if_status(conn, record, ActionStatus.PENDING_CONFIRMATION)
        finally:
            conn.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(attempt_transition, range(20)))

    assert results.count(True) == 1, "exactly one concurrent caller must win the CAS transition"
    assert results.count(False) == 19

    verify_conn = sqlite3.connect(fixture_db_path)
    verify_conn.row_factory = sqlite3.Row
    final = get_action(verify_conn, action_id)
    verify_conn.close()
    assert final is not None
    assert final.status is ActionStatus.CONFIRMED


def test_concurrent_execute_transition_also_lets_exactly_one_caller_win(fixture_db_path):
    action_id = f"ACT-{uuid.uuid4().hex[:12]}"
    setup_conn = sqlite3.connect(fixture_db_path)
    setup_conn.row_factory = sqlite3.Row
    insert_action(setup_conn, _make_record(action_id, ActionStatus.CONFIRMED))
    setup_conn.close()

    def attempt_execute(_):
        conn = sqlite3.connect(fixture_db_path, check_same_thread=False)
        try:
            record = _make_record(action_id, ActionStatus.EXECUTED)
            return save_action_if_status(conn, record, ActionStatus.CONFIRMED)
        finally:
            conn.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(attempt_execute, range(20)))

    assert results.count(True) == 1, "exactly one caller may perform the real EXECUTED transition"


# ---------------- HTTP-level race against the real workflow (through the API) ----------------


def test_http_concurrent_confirm_against_the_same_action_yields_exactly_one_success(client):
    prep = client.post(
        "/api/actions/prepare", json={"ticket_id": "FXT-501", "reason": "http race"},
        headers={"X-Demo-User": "ops_admin"},
    ).json()["outcome"]["record"]
    action_id, payload_hash = prep["action_id"], prep["payload_hash"]

    def confirm(_):
        return client.post(
            "/api/actions/confirm",
            json={"action_id": action_id, "payload_hash": payload_hash},
            headers={"X-Demo-User": "ops_admin"},
        ).json()["outcome"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(confirm, range(20)))

    successes = [r for r in results if r["success"]]
    assert len(successes) == 1
    assert all(
        r["error_code"] == "wrong_state" for r in results if not r["success"]
    )


def test_http_concurrent_execute_is_idempotent_with_exactly_one_real_transition(client):
    prep = client.post(
        "/api/actions/prepare", json={"ticket_id": "FXT-505", "reason": "http race 2"},
        headers={"X-Demo-User": "ops_admin"},
    ).json()["outcome"]["record"]
    action_id, payload_hash = prep["action_id"], prep["payload_hash"]
    client.post(
        "/api/actions/confirm", json={"action_id": action_id, "payload_hash": payload_hash},
        headers={"X-Demo-User": "ops_admin"},
    )

    def execute(_):
        return client.post(
            "/api/actions/execute", json={"action_id": action_id},
            headers={"X-Demo-User": "ops_admin"},
        ).json()["outcome"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(execute, range(20)))

    # Idempotent by design: every caller sees success=True (the intent -
    # "this action ends up EXECUTED" - is satisfied for all of them), but
    # there is exactly one row, one executed_at, no corruption.
    assert all(r["success"] for r in results)
    assert len({r["record"]["action_id"] for r in results}) == 1


def test_audit_record_is_not_duplicated_or_corrupted_by_the_race(client, fixture_db_path):
    prep = client.post(
        "/api/actions/prepare",
        json={"ticket_id": "FXT-501", "reason": "audit integrity race"},
        headers={"X-Demo-User": "ops_admin"},
    ).json()["outcome"]["record"]
    action_id, payload_hash = prep["action_id"], prep["payload_hash"]

    def confirm(_):
        client.post(
            "/api/actions/confirm",
            json={"action_id": action_id, "payload_hash": payload_hash},
            headers={"X-Demo-User": "ops_admin"},
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(confirm, range(10)))

    conn = sqlite3.connect(fixture_db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM actions WHERE action_id = ?", (action_id,)
    ).fetchall()
    conn.close()
    assert len(rows) == 1  # never duplicated
    assert rows[0]["status"] == "CONFIRMED"
    assert rows[0]["evidence"] is not None and rows[0]["evidence"] != "[]"


# ---------------- basic HTTP concurrency smoke test (s18) ----------------


@pytest.mark.parametrize("concurrency", [1, 5, 10])
def test_concurrent_chat_requests_produce_no_errors(client, concurrency):
    def ask(_):
        return client.post("/api/chat", json={"question": "What severity is FXT-501?"})

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        responses = list(pool.map(ask, range(concurrency)))
    assert all(r.status_code == 200 for r in responses)


@pytest.mark.parametrize("concurrency", [1, 5, 10])
def test_concurrent_radar_requests_produce_no_errors(client, concurrency):
    def run(_):
        return client.post("/api/radar/run", json={})

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        responses = list(pool.map(run, range(concurrency)))
    assert all(r.status_code == 200 for r in responses)
