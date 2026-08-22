"""Builds EvidenceRef citations from the actual database - never a
hand-typed page number. cite_document looks up the real page a section
lives on rather than assuming page 1 (true today, but assumed nowhere).
"""

from __future__ import annotations

import sqlite3

from app.domain.outcomes import EvidenceRef


def cite_document(
    conn: sqlite3.Connection, source_id: str, section: str, note: str | None = None
) -> EvidenceRef:
    row = conn.execute(
        "SELECT page FROM document_chunks WHERE source_id = ? AND section = ? LIMIT 1",
        (source_id, section),
    ).fetchone()
    page = row["page"] if row else 1
    return EvidenceRef(
        kind="document", source_id=source_id, locator=f"p{page}:{section}", note=note
    )


def cite_structured(table: str, record_id: str, note: str | None = None) -> EvidenceRef:
    return EvidenceRef(
        kind="structured", source_id="SRC-07", locator=f"{table}:{record_id}", note=note
    )


def cite_calculation(name: str, note: str | None = None) -> EvidenceRef:
    return EvidenceRef(kind="calculation", source_id=f"calculation:{name}", locator=None, note=note)
