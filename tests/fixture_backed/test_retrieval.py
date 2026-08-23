from app.documents.retrieval import DocumentSearchFilter, search_documents
from app.models.enums import SourceStatus


def test_search_finds_the_relevant_fixture_agreement(conn):
    results = search_documents(conn, "Meridian Freight cancellation fee waiver BOOKED", top_k=5)
    assert results
    assert results[0].source_id == "FIX-05"


def test_deprecated_fixture_source_is_retrievable_by_default(conn):
    results = search_documents(conn, "default first-response targets deprecated", top_k=10)
    assert any(r.source_id == "FIX-02" for r in results)


def test_status_filter_excludes_deprecated_when_requested(conn):
    current_only = DocumentSearchFilter(statuses=[SourceStatus.CURRENT, SourceStatus.ACTIVE])
    results = search_documents(
        conn, "default first-response targets deprecated", filters=current_only, top_k=10
    )
    assert all(r.status != SourceStatus.DEPRECATED for r in results)


def test_account_scope_filter_hides_other_accounts_agreement(conn):
    scoped = DocumentSearchFilter(account_scope=["FX-002"])
    query = "Meridian Freight cancellation waiver"
    results = search_documents(conn, query, filters=scoped, top_k=10)
    assert not any(r.source_id == "FIX-05" for r in results)


def test_no_matches_returns_empty_list(conn):
    assert search_documents(conn, "zzzznonexistentqueryterm12345", top_k=5) == []
