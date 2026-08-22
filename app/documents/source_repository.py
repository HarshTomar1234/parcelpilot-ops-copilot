"""Reads SourceDocument rows back out of the sources table - the read side
that pairs with app/documents/source_metadata.py's ingestion-time builder.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from app.errors import UnknownEntityError
from app.models.source import SourceDocument, SourceScope


def get_source(conn: sqlite3.Connection, source_id: str) -> SourceDocument:
    row = conn.execute("SELECT * FROM sources WHERE source_id = ?", (source_id,)).fetchone()
    if row is None:
        raise UnknownEntityError("source", source_id)
    return SourceDocument(
        source_id=row["source_id"],
        filename=row["filename"],
        source_type=row["source_type"],
        status=row["status"],
        version=row["version"],
        effective_date=date.fromisoformat(row["effective_date"]),
        expiry_date=date.fromisoformat(row["expiry_date"]) if row["expiry_date"] else None,
        supersedes=row["supersedes"],
        superseded_by=row["superseded_by"],
        scope=SourceScope(kind=row["scope_kind"], account_id=row["scope_account_id"]),
        authority_class=row["authority_class"],
        checksum=row["checksum"],
        bytes=row["bytes"],
        provenance=row["provenance"],
    )
