import sqlite3

import pytest

from app.documents.retrieval import DocumentSearchFilter, search_documents
from app.errors import InvalidFilterError
from app.models.enums import SourceStatus


def test_search_returns_the_relevant_agreement_first(conn: sqlite3.Connection):
    # Phrasing matches the illustrative brief question (golden case GC-001).
    results = search_documents(
        conn, "Can Northstar cancel ORD-1001 without a cancellation fee? Explain why.", top_k=5
    )
    assert results
    assert results[0].source_id == "SRC-05"


def test_search_respects_top_k(conn: sqlite3.Connection):
    results = search_documents(conn, "cancellation fee service credit policy agreement", top_k=2)
    assert len(results) <= 2


def test_search_ordering_is_deterministic(conn: sqlite3.Connection):
    first = search_documents(conn, "service credit carrier fault", top_k=5)
    second = search_documents(conn, "service credit carrier fault", top_k=5)
    assert [r.chunk_id for r in first] == [r.chunk_id for r in second]


def test_status_filter_excludes_deprecated_when_requested(conn: sqlite3.Connection):
    current_only = DocumentSearchFilter(statuses=[SourceStatus.CURRENT, SourceStatus.ACTIVE])
    results = search_documents(
        conn, "first response target one hour", filters=current_only, top_k=10
    )
    assert all(r.status != SourceStatus.DEPRECATED for r in results)


def test_deprecated_source_is_still_retrievable_by_default(conn: sqlite3.Connection):
    # Phase 1G: retrieval provides evidence, it does not resolve conflicts -
    # excluding DEPRECATED by default would be a policy decision, not a filter.
    results = search_documents(conn, "one hour first response Enterprise", top_k=10)
    assert any(r.source_id == "SRC-02" for r in results)


def test_account_scope_filter_hides_other_accounts_agreement(conn: sqlite3.Connection):
    unfiltered = search_documents(conn, "Northstar agreement cancellation waiver", top_k=10)
    scoped = DocumentSearchFilter(account_scope=["ACCT-002"])
    filtered = search_documents(
        conn, "Northstar agreement cancellation waiver", filters=scoped, top_k=10
    )
    assert any(r.source_id == "SRC-05" for r in unfiltered)
    assert not any(r.source_id == "SRC-05" for r in filtered)


def test_account_scope_filter_still_returns_global_sources(conn: sqlite3.Connection):
    scoped = DocumentSearchFilter(account_scope=["ACCT-002"])
    results = search_documents(conn, "cancellation service credit SOP", filters=scoped, top_k=10)
    assert any(r.source_id == "SRC-03" for r in results)  # global SOP, no account scope


def test_top_k_bounds_are_enforced(conn: sqlite3.Connection):
    with pytest.raises(InvalidFilterError):
        search_documents(conn, "policy", top_k=0)
    with pytest.raises(InvalidFilterError):
        search_documents(conn, "policy", top_k=1000)


def test_empty_query_raises_invalid_filter(conn: sqlite3.Connection):
    with pytest.raises(InvalidFilterError):
        search_documents(conn, "   ", top_k=5)


def test_no_matches_returns_empty_list_not_an_error(conn: sqlite3.Connection):
    assert search_documents(conn, "zzzznonexistentqueryterm12345", top_k=5) == []


def test_results_carry_full_provenance(conn: sqlite3.Connection):
    results = search_documents(conn, "cancellation fee", top_k=1)
    assert results
    result = results[0]
    assert result.page >= 1
    assert result.filename.endswith(".pdf")
    assert result.effective_date is not None
