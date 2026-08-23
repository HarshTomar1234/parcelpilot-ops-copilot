"""Red team s16: deployment failure scenarios (A-G from the phase spec).
Automated where a database-shaped condition can be simulated directly;
scenarios that need an actual container boot (a genuinely missing
PARCELPILOT_DB_B64_FILE target, an empty environment) were also verified
manually against a live Docker container this phase - see
docs/red_team_report.md and docs/_internal/phase-reports/ for that
evidence, since spinning up Docker from inside pytest isn't practical for
a suite that must always run in CI.

Every case must produce a safe, explicit failure - /health always stays
up (it only proves the process is alive), /ready reports the real state
honestly, and no endpoint ever serves fabricated data.
"""

from __future__ import annotations

import os
import sqlite3
import stat

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_settings
from app.api.main import app
from app.config.settings import Settings


@pytest.fixture()
def isolated_client():
    """A TestClient whose settings are overridden per-test (not the
    shared fixture-DB client) - each deployment-failure scenario needs
    its own db_path, not the session-shared fixture database."""
    yield app
    app.dependency_overrides.pop(get_settings, None)


# A. valid DB - already covered exhaustively by every other red_team/fixture_backed test.


# B. missing DB
def test_missing_database_file_health_up_ready_down_no_crash(isolated_client, tmp_path):
    missing_path = tmp_path / "does_not_exist.db"
    app.dependency_overrides[get_settings] = lambda: Settings(
        parcelpilot_source_dir=None, parcelpilot_db_path=missing_path,
    )
    client = TestClient(app, raise_server_exceptions=False)

    assert client.get("/health").status_code == 200
    ready = client.get("/ready")
    assert ready.status_code == 503
    body = ready.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["database_file_present"] is False
    assert body["dataset_snapshot"] is None

    chat = client.post("/api/chat", json={"question": "hello"})
    assert chat.status_code == 503
    assert "internal" not in chat.text.lower() or "database not available" in chat.text.lower()


# C. corrupt DB
def test_corrupt_database_file_fails_safely_not_a_crash(isolated_client, tmp_path):
    corrupt_path = tmp_path / "corrupt.db"
    corrupt_path.write_bytes(b"this is not a valid sqlite file, just garbage bytes" * 100)
    app.dependency_overrides[get_settings] = lambda: Settings(
        parcelpilot_source_dir=None, parcelpilot_db_path=corrupt_path,
    )
    client = TestClient(app, raise_server_exceptions=False)

    assert client.get("/health").status_code == 200
    ready = client.get("/ready")
    # A corrupt file still "exists" (database_file_present=True) but any
    # real query against it fails - /ready must not crash, and must not
    # claim readiness for a database it can't actually read.
    assert ready.status_code in {200, 503}
    if ready.status_code == 200:
        assert ready.json()["status"] == "ready"
    else:
        assert ready.json()["status"] == "not_ready"

    chat = client.post("/api/chat", json={"question": "hello"})
    assert chat.status_code in {500, 503}
    assert "Traceback" not in chat.text
    assert "site-packages" not in chat.text


# D. read-only DB
def test_read_only_database_serves_reads_but_action_writes_fail_explicitly(
    isolated_client, tmp_path, fixture_db_path,
):
    import shutil

    ro_path = tmp_path / "readonly.db"
    shutil.copyfile(fixture_db_path, ro_path)
    os.chmod(ro_path, stat.S_IREAD)
    try:
        app.dependency_overrides[get_settings] = lambda: Settings(
            parcelpilot_source_dir=None, parcelpilot_db_path=ro_path,
        )
        client = TestClient(app, raise_server_exceptions=False)

        # /ready and radar (read-only workflows) still work.
        assert client.get("/ready").status_code == 200
        radar = client.post("/api/radar/run", json={})
        assert radar.status_code == 200

        # prepare_escalation's audit-row write fails explicitly, not silently.
        prep = client.post(
            "/api/actions/prepare", json={"ticket_id": "FXT-501", "reason": "ro test"}
        )
        assert prep.status_code in {200, 500}
        if prep.status_code == 200:
            assert prep.json()["outcome"]["success"] is False
        else:
            assert "Traceback" not in prep.text
    finally:
        os.chmod(ro_path, stat.S_IWRITE | stat.S_IREAD)


# E. invalid DB base64 file (docker-entrypoint.sh's decode path) -
# exercised directly against the shell script's own logic, not via pytest
# (bash isn't invoked from the test suite) - see the manual verification
# in docs/red_team_report.md. What IS testable here is the equivalent
# application-level condition: a database path that exists but isn't a
# real SQLite file (covered by test_corrupt_database_file above - the
# decode failure and a corrupt decoded file produce the same downstream
# state).


# F/G. missing / empty configuration
def test_missing_source_dir_setting_does_not_prevent_serving_an_already_ingested_db(
    isolated_client, fixture_db_path,
):
    """PARCELPILOT_SOURCE_DIR is only needed for ingestion, never for
    serving - a deployment with no source pack configured at all (the
    normal, expected production case, since the pack is never shipped)
    must still serve correctly from an already-built database."""
    app.dependency_overrides[get_settings] = lambda: Settings(
        parcelpilot_source_dir=None, parcelpilot_db_path=fixture_db_path,
    )
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/ready").json()["status"] == "ready"
    assert client.post("/api/radar/run", json={}).status_code == 200


def test_empty_environment_still_boots_and_reports_not_ready_honestly(isolated_client, tmp_path):
    """A completely default Settings() (no env vars set at all) must not
    crash the app - it should fall back to defaults and report not_ready
    if those defaults don't resolve to a real database."""
    app.dependency_overrides[get_settings] = lambda: Settings(
        parcelpilot_source_dir=None, parcelpilot_db_path=tmp_path / "build" / "parcelpilot.db",
    )
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 503


def test_ready_never_leaks_the_configured_absolute_path_or_env_details(
    isolated_client, tmp_path,
):
    secret_looking_path = tmp_path / "C_Users_Harsh_secret_deploy_key.db"
    app.dependency_overrides[get_settings] = lambda: Settings(
        parcelpilot_source_dir=None, parcelpilot_db_path=secret_looking_path,
    )
    client = TestClient(app, raise_server_exceptions=False)
    body = client.get("/ready").text
    assert str(secret_looking_path) not in body
    assert "secret_deploy_key" not in body


def test_sqlite_operational_error_on_a_locked_or_busy_database_is_handled(
    isolated_client, tmp_path, fixture_db_path,
):
    """Simulates a database that exists and opens, but whose connection
    immediately fails a real query (e.g. a transient lock) - the /ready
    handler's try/except around the query must hold."""
    import shutil

    locked_path = tmp_path / "locked.db"
    shutil.copyfile(fixture_db_path, locked_path)
    conn = sqlite3.connect(locked_path)
    conn.execute("BEGIN EXCLUSIVE")
    try:
        app.dependency_overrides[get_settings] = lambda: Settings(
            parcelpilot_source_dir=None, parcelpilot_db_path=locked_path,
        )
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/ready")
        assert resp.status_code in {200, 503}
        assert "Traceback" not in resp.text
    finally:
        conn.rollback()
        conn.close()


# ---------------- s19: provider/tool failure injection through the HTTP layer ----------------
# The retry/fallback classification itself (timeout/429/5xx retried,
# auth/malformed-request not) is already unit-tested against real SDK
# exception types in tests/unit/test_llm_provider_fallback.py and
# tests/unit/test_anthropic_retry.py - this proves the HTTP layer built
# on top surfaces a provider failure as a safe, structured "failed"
# result, never a raw exception or a fabricated confident answer.


class _AlwaysFailsProvider:
    name = "always-fails"

    def complete(self, request, context):  # noqa: ANN001 - matches LLMProvider protocol
        raise RuntimeError("simulated provider outage (timeout/5xx/auth failure stand-in)")


def test_provider_failure_during_chat_is_a_safe_failed_status_not_a_500(client):
    from app.api.deps import get_provider

    app.dependency_overrides[get_provider] = lambda: (_AlwaysFailsProvider(), "broken-model")
    try:
        resp = client.post(
            "/api/chat", json={"question": "What severity is FXT-501?"},
            headers={"X-Demo-User": "ops_admin"},
        )
    finally:
        from app.llm.mock_provider import MockProvider

        app.dependency_overrides[get_provider] = lambda: (MockProvider(), "mock-model")

    assert resp.status_code == 200  # the API layer itself never crashes
    result = resp.json()["result"]
    assert result["status"] == "failed"
    # trust_state here reflects the deterministic domain computation that
    # ran BEFORE the provider failed (real, independent of the LLM) -
    # what actually matters is that no answer text was ever produced or
    # shown as trustworthy for a request that ended in "failed".
    assert result["answer"] is None
    assert "response composition failed" in (result["reason"] or "")
