"""Typed errors for the data foundation. Nothing here is swallowed silently -
every failure mode in AGENTS.md rule 20 ("never claim completion without
verification") starts with the caller actually seeing what broke.
"""

from __future__ import annotations


class ParcelPilotError(Exception):
    """Base class for all application errors."""


class SourceDirectoryNotFoundError(ParcelPilotError):
    def __init__(self, path: str) -> None:
        super().__init__(f"source directory not found: {path}")
        self.path = path


class MissingSourceFileError(ParcelPilotError):
    def __init__(self, filename: str, source_dir: str) -> None:
        super().__init__(f"expected source file missing: {filename} (in {source_dir})")
        self.filename = filename
        self.source_dir = source_dir


class ChecksumMismatchError(ParcelPilotError):
    def __init__(self, filename: str, expected: str, actual: str) -> None:
        super().__init__(
            f"checksum mismatch for {filename}: expected {expected[:12]}..., "
            f"got {actual[:12]}... (source pack differs from the one Phase 0 analyzed)"
        )
        self.filename = filename
        self.expected = expected
        self.actual = actual


class SourceMetadataDriftError(ParcelPilotError):
    """Raised when a fact parsed fresh from a document disagrees with
    data/source_manifest.json (the recorded Phase 0 classification)."""

    def __init__(
        self, source_id: str, field: str, manifest_value: object, parsed_value: object
    ) -> None:
        super().__init__(
            f"{source_id}: manifest says {field}={manifest_value!r} but the document "
            f"text parses to {field}={parsed_value!r}"
        )
        self.source_id = source_id
        self.field = field


class DocumentParseError(ParcelPilotError):
    def __init__(self, filename: str, reason: str) -> None:
        super().__init__(f"failed to parse {filename}: {reason}")
        self.filename = filename


class MalformedWorkbookError(ParcelPilotError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"malformed workbook: {reason}")


class InvalidSnapshotTimestampError(ParcelPilotError):
    def __init__(self, raw: str, reason: str) -> None:
        super().__init__(f"invalid snapshot timestamp {raw!r}: {reason}")
        self.raw = raw


class UnknownEntityError(ParcelPilotError):
    def __init__(self, entity_type: str, entity_id: str) -> None:
        super().__init__(f"unknown {entity_type}: {entity_id}")
        self.entity_type = entity_type
        self.entity_id = entity_id


class NotAuthorizedError(ParcelPilotError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"not authorized: {reason}")


class InvalidFilterError(ParcelPilotError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"invalid filter: {reason}")
