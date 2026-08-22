"""Builds build/parcelpilot.db from the external source pack.

Pipeline (Phase 1C): validate expected files exist -> verify checksums ->
parse PDFs (page-aware, section-aware) -> cross-check parsed metadata
against data/source_manifest.json -> extract SLA tables -> parse the
workbook -> validate account_id relationships -> write everything to a
freshly initialized SQLite database.

Every step fails loudly (raises a typed error from app.errors) rather than
skipping a bad source and continuing - AGENTS.md rule 20.

Usage:
    python scripts/ingest_sources.py --source-dir "<pack>/source-pack" [--db build/parcelpilot.db]
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.connection import init_db  # noqa: E402
from app.documents.chunker import build_chunks  # noqa: E402
from app.documents.pdf_parser import ParsedPage, parse_pdf  # noqa: E402
from app.documents.sla_table import parse_bullet_targets, parse_grid_table  # noqa: E402
from app.documents.source_metadata import (  # noqa: E402
    build_source_document,
    resolve_supersession,
    sha256_of,
)
from app.errors import (  # noqa: E402
    ChecksumMismatchError,
    MissingSourceFileError,
    SourceDirectoryNotFoundError,
)
from app.models.enums import ScopeKind  # noqa: E402
from app.models.source import DocumentChunk, SlaTarget, SourceDocument  # noqa: E402
from app.observability.logging_config import configure_logging  # noqa: E402
from app.observability.timing import Timings  # noqa: E402
from app.structured_data.workbook import WorkbookData, load_workbook  # noqa: E402

MANIFEST_PATH = Path(__file__).resolve().parents[1] / "data" / "source_manifest.json"
logger = logging.getLogger("ingest")


def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _validate_files_present(source_dir: Path, manifest: dict) -> None:
    if not source_dir.is_dir():
        raise SourceDirectoryNotFoundError(str(source_dir))
    for entry in manifest["sources"]:
        filepath = source_dir / entry["filename"]
        if not filepath.exists():
            raise MissingSourceFileError(entry["filename"], str(source_dir))


def _verify_checksum(filepath: Path, manifest_entry: dict) -> str:
    actual = sha256_of(filepath)
    expected = manifest_entry["checksum"].removeprefix("sha256:")
    if actual != expected:
        raise ChecksumMismatchError(filepath.name, expected, actual)
    return actual


def _extract_sla_targets(source: SourceDocument, pages: list[ParsedPage]) -> list[SlaTarget]:
    targets: list[SlaTarget] = []
    for page in pages:
        for section in page.sections:
            title_lower = section.title.lower()
            if "response targets" in title_lower:
                targets += parse_grid_table(section.body, source.source_id)
            elif section.title == "Support terms" and source.scope.kind is ScopeKind.ACCOUNT:
                assert source.scope.account_id is not None
                targets += parse_bullet_targets(
                    section.body, source.source_id, source.scope.account_id
                )
    return targets


def ingest(source_dir: Path, db_path: Path) -> dict:
    manifest = _load_manifest()
    manifest_by_id = {e["source_id"]: e for e in manifest["sources"]}
    pdf_entries = [e for e in manifest["sources"] if e["filename"].endswith(".pdf")]
    xlsx_entry = next(e for e in manifest["sources"] if e["filename"].endswith(".xlsx"))

    timings = Timings()
    with timings.measure():
        _validate_files_present(source_dir, manifest)

        pages_by_id: dict[str, list[ParsedPage]] = {}
        checksums: dict[str, str] = {}
        for entry in pdf_entries:
            filepath = source_dir / entry["filename"]
            checksums[entry["source_id"]] = _verify_checksum(filepath, entry)
            pages_by_id[entry["source_id"]] = parse_pdf(filepath)
            logger.info(
                "parsed source",
                extra={"event": "source.parsed", "source_id": entry["source_id"]},
            )

        sources: dict[str, SourceDocument] = {}
        for entry in pdf_entries:
            source_id = entry["source_id"]
            filepath = source_dir / entry["filename"]
            sources[source_id] = build_source_document(
                source_id=source_id,
                filename=entry["filename"],
                page=pages_by_id[source_id][0],
                checksum=checksums[source_id],
                size_bytes=filepath.stat().st_size,
                manifest_entry=entry,
            )
        first_pages = {sid: p[0] for sid, p in pages_by_id.items()}
        sources = resolve_supersession(sources, first_pages, manifest_by_id)

        chunks: list[DocumentChunk] = []
        sla_targets: list[SlaTarget] = []
        for source_id, source in sources.items():
            chunks += build_chunks(source, pages_by_id[source_id])
            sla_targets += _extract_sla_targets(source, pages_by_id[source_id])

        xlsx_path = source_dir / xlsx_entry["filename"]
        _verify_checksum(xlsx_path, xlsx_entry)
        workbook = load_workbook(xlsx_path)
        logger.info(
            "parsed workbook",
            extra={
                "event": "workbook.parsed",
                "snapshot": workbook.snapshot.isoformat(),
                "accounts": len(workbook.accounts),
                "orders": len(workbook.orders),
                "tickets": len(workbook.tickets),
            },
        )

        conn = init_db(db_path)
        _write_db(conn, sources, chunks, sla_targets, workbook)
        conn.close()

    summary = {
        "db_path": str(db_path),
        "sources": len(sources),
        "chunks": len(chunks),
        "sla_targets": len(sla_targets),
        "accounts": len(workbook.accounts),
        "orders": len(workbook.orders),
        "tickets": len(workbook.tickets),
        "snapshot": workbook.snapshot.isoformat(),
        "ingestion_latency_ms": round(timings.samples_ms[0], 2),
    }
    logger.info("ingestion complete", extra={"event": "ingest.completed", **summary})
    return summary


def _write_db(
    conn: sqlite3.Connection,
    sources: dict[str, SourceDocument],
    chunks: list[DocumentChunk],
    sla_targets: list[SlaTarget],
    workbook: WorkbookData,
) -> None:
    for source in sources.values():
        conn.execute(
            """INSERT INTO sources
               (source_id, filename, source_type, status, version, effective_date, expiry_date,
                supersedes, superseded_by, scope_kind, scope_account_id,
                authority_class, checksum, bytes, provenance)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                source.source_id, source.filename, source.source_type.value, source.status.value,
                source.version, source.effective_date.isoformat(),
                source.expiry_date.isoformat() if source.expiry_date else None,
                source.supersedes, source.superseded_by, source.scope.kind.value,
                source.scope.account_id, source.authority_class.value, source.checksum,
                source.bytes, source.provenance,
            ),
        )

    for chunk in chunks:
        cur = conn.execute(
            """INSERT INTO document_chunks
               (chunk_id, source_id, page, section, text, normalized_text, filename,
                status, source_type, account_scope, effective_date, authority_class)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                chunk.chunk_id, chunk.source_id, chunk.page, chunk.section, chunk.text,
                chunk.normalized_text, chunk.filename, chunk.status.value, chunk.source_type.value,
                chunk.account_scope, chunk.effective_date.isoformat(), chunk.authority_class.value,
            ),
        )
        conn.execute(
            "INSERT INTO document_chunks_fts (rowid, normalized_text) VALUES (?, ?)",
            (cur.lastrowid, chunk.normalized_text),
        )

    for target in sla_targets:
        conn.execute(
            """INSERT INTO sla_targets
               (source_id, scope_kind, plan, account_id, severity, target_text,
                target_minutes, is_24x7, requires_business_calendar)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                target.source_id, "account" if target.account_id else "plan", target.plan,
                target.account_id, target.severity, target.target_text, target.target_minutes,
                int(target.is_24x7), int(target.requires_business_calendar),
            ),
        )

    for account in workbook.accounts:
        conn.execute(
            """INSERT INTO accounts
               (account_id, account_name, plan, status, csm, contract_file, premium_support, notes)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                account.account_id, account.account_name, account.plan, account.status,
                account.csm, account.contract_file, int(account.premium_support), account.notes,
            ),
        )

    for order in workbook.orders:
        conn.execute(
            """INSERT INTO orders
               (order_id, account_id, carrier, status, booked_at, pickup_window_start,
                pickup_window_end, pickup_actual_at, shipment_fee_inr, carrier_fault,
                customer_fault, cancellation_requested_at, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                order.order_id, order.account_id, order.carrier, order.status.value,
                order.booked_at.isoformat(), order.pickup_window_start.isoformat(),
                order.pickup_window_end.isoformat(),
                order.pickup_actual_at.isoformat() if order.pickup_actual_at else None,
                order.shipment_fee_inr, int(order.carrier_fault), int(order.customer_fault),
                order.cancellation_requested_at.isoformat()
                if order.cancellation_requested_at
                else None,
                order.notes,
            ),
        )

    for ticket in workbook.tickets:
        conn.execute(
            """INSERT INTO tickets
               (ticket_id, account_id, created_at, status, subject, description,
                channel, assigned_to, last_customer_message_at, historical_resolution)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                ticket.ticket_id, ticket.account_id, ticket.created_at.isoformat(),
                ticket.status.value,
                ticket.subject, ticket.description, ticket.channel, ticket.assigned_to,
                ticket.last_customer_message_at.isoformat(), ticket.historical_resolution,
            ),
        )

    conn.executemany(
        "INSERT INTO meta (key, value) VALUES (?, ?)",
        [
            ("snapshot_time", workbook.snapshot.isoformat()),
            ("currency", workbook.currency),
            ("ingested_at", time.strftime("%Y-%m-%dT%H:%M:%S")),
        ],
    )
    conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--db", default=Path("build/parcelpilot.db"), type=Path)
    args = parser.parse_args()

    configure_logging()
    try:
        summary = ingest(args.source_dir, args.db)
    except Exception as exc:
        logger.error(
            "ingestion failed",
            extra={"event": "ingest.failed", "error": str(exc), "type": type(exc).__name__},
        )
        raise
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
