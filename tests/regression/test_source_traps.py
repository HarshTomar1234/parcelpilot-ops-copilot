"""Guards against regressing the specific traps documented in
docs/initial_rules.md and docs/architecture_decision_record.md. Each test
name states the fact it protects.
"""

import sqlite3
from datetime import date


def test_deprecated_policy_remains_labeled_deprecated(conn: sqlite3.Connection):
    row = conn.execute(
        "SELECT status, authority_class FROM sources WHERE source_id = 'SRC-02'"
    ).fetchone()
    assert row["status"] == "DEPRECATED"
    assert row["authority_class"] == "DEPRECATED"


def test_current_policy_is_not_deprecated(conn: sqlite3.Connection):
    row = conn.execute(
        "SELECT status, authority_class FROM sources WHERE source_id = 'SRC-01'"
    ).fetchone()
    assert row["status"] == "CURRENT"
    assert row["authority_class"] == "POLICY_CURRENT"


def test_v3_records_that_it_supersedes_v2(conn: sqlite3.Connection):
    row = conn.execute("SELECT supersedes FROM sources WHERE source_id = 'SRC-01'").fetchone()
    assert row["supersedes"] == "SRC-02"
    row = conn.execute("SELECT superseded_by FROM sources WHERE source_id = 'SRC-02'").fetchone()
    assert row["superseded_by"] == "SRC-01"


def test_product_operations_guide_is_current(conn: sqlite3.Connection):
    row = conn.execute(
        "SELECT status, authority_class FROM sources WHERE source_id = 'SRC-04'"
    ).fetchone()
    assert row["status"] == "CURRENT"
    assert row["authority_class"] == "PRODUCT_DOC"


def test_northstar_agreement_is_scoped_to_acct_001(conn: sqlite3.Connection):
    row = conn.execute(
        "SELECT scope_kind, scope_account_id, authority_class "
        "FROM sources WHERE source_id = 'SRC-05'"
    ).fetchone()
    assert row["scope_kind"] == "account"
    assert row["scope_account_id"] == "ACCT-001"
    assert row["authority_class"] == "AGREEMENT"


def test_northstar_agreement_term_is_active_at_snapshot(conn: sqlite3.Connection):
    row = conn.execute(
        "SELECT effective_date, expiry_date FROM sources WHERE source_id = 'SRC-05'"
    ).fetchone()
    snapshot = date(2026, 8, 16)
    assert date.fromisoformat(row["effective_date"]) <= snapshot
    assert snapshot <= date.fromisoformat(row["expiry_date"])


def test_lumenworks_agreement_is_scoped_to_acct_002(conn: sqlite3.Connection):
    row = conn.execute(
        "SELECT scope_kind, scope_account_id, authority_class "
        "FROM sources WHERE source_id = 'SRC-06'"
    ).fetchone()
    assert row["scope_kind"] == "account"
    assert row["scope_account_id"] == "ACCT-002"
    assert row["authority_class"] == "AGREEMENT"


def test_lumenworks_agreement_term_is_active_at_snapshot(conn: sqlite3.Connection):
    row = conn.execute(
        "SELECT effective_date, expiry_date FROM sources WHERE source_id = 'SRC-06'"
    ).fetchone()
    snapshot = date(2026, 8, 16)
    assert date.fromisoformat(row["effective_date"]) <= snapshot
    assert snapshot <= date.fromisoformat(row["expiry_date"])


def test_historical_ticket_resolutions_exist_only_on_tickets_never_as_a_document_source(
    conn: sqlite3.Connection,
):
    rows = conn.execute(
        "SELECT ticket_id FROM tickets WHERE historical_resolution IS NOT NULL"
    ).fetchall()
    assert {r["ticket_id"] for r in rows} == {"TKT-450", "TKT-451"}
    # No document_chunks row (the only retrievable/citable evidence unit) is
    # ever sourced from a ticket - historical resolutions cannot become
    # document evidence with an authority_class of their own.
    count = conn.execute(
        "SELECT COUNT(*) FROM document_chunks WHERE source_id NOT LIKE 'SRC-%'"
    ).fetchone()[0]
    assert count == 0


def test_snapshot_time_is_the_exact_workbook_value(conn: sqlite3.Connection):
    row = conn.execute("SELECT value FROM meta WHERE key = 'snapshot_time'").fetchone()
    assert row["value"] == "2026-08-16T11:00:00+05:30"


def test_snapshot_date_is_a_sunday(conn: sqlite3.Connection):
    row = conn.execute("SELECT value FROM meta WHERE key = 'snapshot_time'").fetchone()
    snapshot_date = date.fromisoformat(row["value"][:10])
    assert snapshot_date.strftime("%A") == "Sunday"
