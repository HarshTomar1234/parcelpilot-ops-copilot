"""Builds a SourceDocument by parsing facts fresh from each PDF's own text
and cross-checking them against data/source_manifest.json.

Split of responsibility:
  - Parsed from the PDF, every ingestion run (status, effective/updated date,
    version, supersedes/superseded-by, account scope for agreements).
  - Loaded from the manifest (an engineering classification the PDF text
    itself never states): source_type, authority_class, provenance.

A mismatch between the two is not "malformed data" - it means the manifest
has drifted from the actual source pack, which is exactly the kind of
silent staleness AGENTS.md rule 20 exists to catch. It fails loudly.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from app.documents.pdf_parser import ParsedPage
from app.errors import DocumentParseError, SourceMetadataDriftError
from app.models.enums import ScopeKind, SourceStatus
from app.models.source import SourceDocument, SourceScope

_VERSION = re.compile(r"\bv(\d+)\b", re.IGNORECASE)
_DATE_FORMAT = "%d %B %Y"


def sha256_of(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_date(raw: str, *, source_id: str) -> date:
    try:
        return datetime.strptime(raw.strip(), _DATE_FORMAT).date()
    except ValueError as exc:
        raise DocumentParseError(source_id, f"unparseable date {raw!r}") from exc


def parse_status(raw: str, *, source_id: str) -> SourceStatus:
    head = raw.split(" - ")[0].strip().upper()
    try:
        return SourceStatus(head)
    except ValueError as exc:
        raise DocumentParseError(source_id, f"unrecognized status {raw!r}") from exc


def parse_version(title: str) -> str | None:
    match = _VERSION.search(title)
    return f"v{match[1]}" if match else None


def _term_start(term: str | None) -> str | None:
    """'1 January 2026 to 31 December 2026' -> '1 January 2026'."""
    if term is None:
        return None
    return term.split(" to ")[0].strip()


def _term_end(term: str | None) -> str | None:
    """'1 January 2026 to 31 December 2026' -> '31 December 2026'."""
    if term is None or " to " not in term:
        return None
    return term.split(" to ")[1].strip()


def build_source_document(
    *,
    source_id: str,
    filename: str,
    page: ParsedPage,
    checksum: str,
    size_bytes: int,
    manifest_entry: dict,
) -> SourceDocument:
    if "Status" not in page.preamble_fields:
        raise DocumentParseError(source_id, "no 'Status:' field in preamble")
    status = parse_status(page.preamble_fields["Status"], source_id=source_id)

    effective_raw = (
        page.preamble_fields.get("Effective")
        or page.preamble_fields.get("Updated")
        or _term_start(page.preamble_fields.get("Term"))
    )
    if effective_raw is None:
        raise DocumentParseError(
            source_id, "no 'Effective:'/'Updated:'/'Term:' field in preamble"
        )
    effective_date = parse_date(effective_raw, source_id=source_id)

    version = parse_version(page.title)

    expiry_raw = _term_end(page.preamble_fields.get("Term"))
    expiry_date = parse_date(expiry_raw, source_id=source_id) if expiry_raw else None

    if manifest_entry["status"] != status.value:
        raise SourceMetadataDriftError(source_id, "status", manifest_entry["status"], status.value)
    parsed_effective = effective_date.isoformat()
    if manifest_entry["effective_date"] != parsed_effective:
        raise SourceMetadataDriftError(
            source_id, "effective_date", manifest_entry["effective_date"], parsed_effective
        )
    manifest_expiry = manifest_entry.get("expiry_date")
    parsed_expiry = expiry_date.isoformat() if expiry_date else None
    if manifest_expiry != parsed_expiry:
        raise SourceMetadataDriftError(source_id, "expiry_date", manifest_expiry, parsed_expiry)

    scope_kind = ScopeKind(manifest_entry["scope"]["kind"])
    account_id = page.preamble_fields.get("Account")
    if scope_kind is ScopeKind.ACCOUNT:
        if not account_id:
            raise DocumentParseError(source_id, "account-scoped source has no 'Account:' field")
        manifest_account_ids = manifest_entry["scope"].get("account_ids") or []
        if manifest_account_ids and account_id not in manifest_account_ids:
            raise SourceMetadataDriftError(
                source_id, "scope.account_id", manifest_account_ids, account_id
            )

    expected_checksum = manifest_entry["checksum"].removeprefix("sha256:")
    if expected_checksum != checksum:
        from app.errors import ChecksumMismatchError

        raise ChecksumMismatchError(filename, expected_checksum, checksum)

    return SourceDocument(
        source_id=source_id,
        filename=filename,
        source_type=manifest_entry["source_type"],
        status=status,
        version=version,
        effective_date=effective_date,
        expiry_date=expiry_date,
        supersedes=None,  # resolved across all sources by resolve_supersession()
        superseded_by=None,
        scope=SourceScope(
            kind=scope_kind, account_id=account_id if scope_kind is ScopeKind.ACCOUNT else None
        ),
        authority_class=manifest_entry["authority_class"],
        checksum=checksum,
        bytes=size_bytes,
        provenance=manifest_entry["provenance"],
    )


def resolve_supersession(
    sources: dict[str, SourceDocument],
    pages: dict[str, ParsedPage],
    manifest_by_id: dict[str, dict],
) -> dict[str, SourceDocument]:
    """Resolve 'Supersedes: Support Policy v2' / 'Superseded by: ... v3 ...'
    text to actual source_ids by matching version numbers across the parsed
    set, then cross-check against the manifest.
    """
    version_to_id = {doc.version: sid for sid, doc in sources.items() if doc.version}
    resolved: dict[str, SourceDocument] = {}

    for source_id, doc in sources.items():
        page = pages[source_id]
        supersedes_id = _resolve_reference(
            page.preamble_fields.get("Supersedes"), version_to_id, source_id
        )
        superseded_by_id = _resolve_reference(
            page.preamble_fields.get("Superseded by"), version_to_id, source_id
        )

        expected_supersedes = manifest_by_id[source_id].get("supersedes")
        expected_superseded_by = manifest_by_id[source_id].get("superseded_by")
        if expected_supersedes != supersedes_id:
            raise SourceMetadataDriftError(
                source_id, "supersedes", expected_supersedes, supersedes_id
            )
        if expected_superseded_by != superseded_by_id:
            raise SourceMetadataDriftError(
                source_id, "superseded_by", expected_superseded_by, superseded_by_id
            )

        resolved[source_id] = doc.model_copy(
            update={"supersedes": supersedes_id, "superseded_by": superseded_by_id}
        )
    return resolved


def _resolve_reference(
    raw: str | None, version_to_id: dict[str, str], source_id: str
) -> str | None:
    if raw is None:
        return None
    match = _VERSION.search(raw)
    if not match:
        raise DocumentParseError(source_id, f"cannot resolve version reference in {raw!r}")
    target_id = version_to_id.get(f"v{match[1]}")
    if target_id is None:
        raise DocumentParseError(
            source_id, f"reference {raw!r} does not match any parsed source version"
        )
    return target_id
