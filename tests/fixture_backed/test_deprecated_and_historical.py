"""Guards the same traps tests/regression/test_source_traps.py guards for
the real pack, against fixture data instead."""


def test_deprecated_source_is_labeled_deprecated(conn):
    row = conn.execute(
        "SELECT status, authority_class FROM sources WHERE source_id = 'FIX-02'"
    ).fetchone()
    assert row["status"] == "DEPRECATED"
    assert row["authority_class"] == "DEPRECATED"


def test_current_source_is_not_deprecated(conn):
    row = conn.execute(
        "SELECT status, authority_class FROM sources WHERE source_id = 'FIX-01'"
    ).fetchone()
    assert row["status"] == "CURRENT"
    assert row["authority_class"] == "POLICY_CURRENT"


def test_fix01_records_that_it_supersedes_fix02(conn):
    row = conn.execute("SELECT supersedes FROM sources WHERE source_id = 'FIX-01'").fetchone()
    assert row["supersedes"] == "FIX-02"


def test_historical_resolutions_exist_only_on_tickets_never_as_a_document_source(conn):
    rows = conn.execute(
        "SELECT ticket_id FROM tickets WHERE historical_resolution IS NOT NULL"
    ).fetchall()
    assert {r["ticket_id"] for r in rows} == {"FXT-450", "FXT-451"}
    count = conn.execute(
        "SELECT COUNT(*) FROM document_chunks WHERE source_id NOT LIKE 'FIX-%'"
    ).fetchone()[0]
    assert count == 0


def test_meridian_agreement_is_scoped_to_fx001(conn):
    row = conn.execute(
        "SELECT scope_kind, scope_account_id FROM sources WHERE source_id = 'FIX-05'"
    ).fetchone()
    assert row["scope_kind"] == "account"
    assert row["scope_account_id"] == "FX-001"


def test_cobalt_agreement_is_scoped_to_fx002(conn):
    row = conn.execute(
        "SELECT scope_kind, scope_account_id FROM sources WHERE source_id = 'FIX-06'"
    ).fetchone()
    assert row["scope_kind"] == "account"
    assert row["scope_account_id"] == "FX-002"
