"""Deterministic document retrieval over the FTS5 index.

Phase 1G: this layer returns evidence, ranked by BM25, with full metadata
attached. It does not decide which of several relevant-but-conflicting
chunks is "correct" - that is a future policy layer's job. The only filters
applied here are structural (source type, status, authority class, account
scope), never "pick the winning source".

include_deprecated defaults to True for the same reason: excluding
DEPRECATED by default would be a policy decision smuggled into retrieval.
Callers who want current-only evidence pass statuses=[CURRENT, ACTIVE].
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date

from pydantic import BaseModel, ConfigDict

from app.errors import InvalidFilterError
from app.models.enums import AuthorityClass, SourceStatus, SourceType

_TOKEN = re.compile(r"[A-Za-z0-9]+")
_MAX_TOP_K = 50


class DocumentSearchFilter(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_types: list[SourceType] | None = None
    authority_classes: list[AuthorityClass] | None = None
    statuses: list[SourceStatus] | None = None
    # None = no account restriction (Phase 1 permissive / operations_admin caller).
    # A list restricts to chunks that are global OR scoped to one of these accounts.
    account_scope: list[str] | None = None


class DocumentSearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    source_id: str
    filename: str
    page: int
    section: str | None
    snippet: str
    score: float
    status: SourceStatus
    source_type: SourceType
    authority_class: AuthorityClass
    effective_date: date
    account_scope: str | None


def _normalize_query(query: str) -> str:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN.findall(query.lower()):
        if token not in seen:
            seen.add(token)
            tokens.append(token)
    if not tokens:
        raise InvalidFilterError("query has no searchable terms")
    return " OR ".join(f'"{t}"' for t in tokens)


def search_documents(
    conn: sqlite3.Connection,
    query: str,
    filters: DocumentSearchFilter | None = None,
    top_k: int = 5,
) -> list[DocumentSearchResult]:
    if not (1 <= top_k <= _MAX_TOP_K):
        raise InvalidFilterError(f"top_k must be between 1 and {_MAX_TOP_K}, got {top_k}")
    filters = filters or DocumentSearchFilter()

    fts_query = _normalize_query(query)
    clauses = ["document_chunks_fts MATCH ?"]
    params: list[object] = [fts_query]

    if filters.source_types:
        clauses.append(_in_clause("document_chunks.source_type", len(filters.source_types)))
        params += [t.value for t in filters.source_types]
    if filters.authority_classes:
        count = len(filters.authority_classes)
        clauses.append(_in_clause("document_chunks.authority_class", count))
        params += [a.value for a in filters.authority_classes]
    if filters.statuses:
        clauses.append(_in_clause("document_chunks.status", len(filters.statuses)))
        params += [s.value for s in filters.statuses]
    if filters.account_scope is not None:
        placeholders = ", ".join("?" for _ in filters.account_scope)
        clauses.append(
            "(document_chunks.account_scope IS NULL"
            f" OR document_chunks.account_scope IN ({placeholders}))"
        )
        params += filters.account_scope

    where = " AND ".join(clauses)
    sql = f"""
        SELECT
            document_chunks.chunk_id,
            document_chunks.source_id,
            document_chunks.filename,
            document_chunks.page,
            document_chunks.section,
            snippet(document_chunks_fts, 0, '[', ']', '...', 12) AS snippet,
            bm25(document_chunks_fts) AS score,
            document_chunks.status,
            document_chunks.source_type,
            document_chunks.authority_class,
            document_chunks.effective_date,
            document_chunks.account_scope
        FROM document_chunks_fts
        JOIN document_chunks ON document_chunks.id = document_chunks_fts.rowid
        WHERE {where}
        ORDER BY score ASC, document_chunks.chunk_id ASC
        LIMIT ?
    """
    params.append(top_k)

    rows = conn.execute(sql, params).fetchall()
    return [
        DocumentSearchResult(
            chunk_id=row["chunk_id"],
            source_id=row["source_id"],
            filename=row["filename"],
            page=row["page"],
            section=row["section"],
            snippet=row["snippet"],
            score=row["score"],
            status=row["status"],
            source_type=row["source_type"],
            authority_class=row["authority_class"],
            effective_date=row["effective_date"],
            account_scope=row["account_scope"],
        )
        for row in rows
    ]


def _in_clause(column: str, count: int) -> str:
    return f"{column} IN ({', '.join('?' for _ in range(count))})"
