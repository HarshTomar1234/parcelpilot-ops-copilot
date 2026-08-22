import sqlite3


def test_ingest_produces_expected_row_counts(conn: sqlite3.Connection):
    assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0] == 18
    assert conn.execute("SELECT COUNT(*) FROM sla_targets").fetchone()[0] == 24
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 7


def test_meta_snapshot_matches_readme(conn: sqlite3.Connection):
    row = conn.execute("SELECT value FROM meta WHERE key = 'snapshot_time'").fetchone()
    assert row["value"] == "2026-08-16T11:00:00+05:30"
    row = conn.execute("SELECT value FROM meta WHERE key = 'currency'").fetchone()
    assert row["value"] == "INR"


def test_fts_index_has_one_row_per_chunk(conn: sqlite3.Connection):
    chunks = conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
    fts_rows = conn.execute("SELECT COUNT(*) FROM document_chunks_fts").fetchone()[0]
    assert fts_rows == chunks


def test_every_chunk_has_page_and_section_provenance(conn: sqlite3.Connection):
    rows = conn.execute("SELECT chunk_id, page, source_id FROM document_chunks").fetchall()
    assert rows
    for row in rows:
        assert row["page"] >= 1
        assert row["chunk_id"].startswith(row["source_id"] + ":p")


def test_reingesting_is_reproducible(source_dir, tmp_path):
    from scripts.ingest_sources import ingest

    summary_a = ingest(source_dir, tmp_path / "a.db")
    summary_b = ingest(source_dir, tmp_path / "b.db")
    for key in ("sources", "chunks", "sla_targets", "accounts", "orders", "tickets", "snapshot"):
        assert summary_a[key] == summary_b[key]
