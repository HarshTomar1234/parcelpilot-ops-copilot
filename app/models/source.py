"""Typed models for document sources and their chunks.

Field lists match the Phase 0 spec exactly (docs/architecture_decision_record.md,
tests/evaluation/golden_cases.json citation format). SourceDocument mirrors
data/source_manifest.json; DocumentChunk mirrors what ingestion writes to the
document_chunks table.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict

from app.models.enums import AuthorityClass, ScopeKind, SourceStatus, SourceType


class SourceScope(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ScopeKind
    account_id: str | None = None

    def covers(self, account_id: str | None) -> bool:
        """True if this source applies given a caller's account scope.
        account_id=None means "no account restriction" (internal/global caller)."""
        if self.kind is ScopeKind.GLOBAL:
            return True
        return account_id is None or account_id == self.account_id


class SourceDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str
    filename: str
    source_type: SourceType
    status: SourceStatus
    version: str | None = None
    effective_date: date
    expiry_date: date | None = None  # agreements only; parsed from 'Term: X to Y'
    supersedes: str | None = None
    superseded_by: str | None = None
    scope: SourceScope
    authority_class: AuthorityClass
    checksum: str
    bytes: int
    provenance: str

    def is_active_at(self, instant: date) -> bool:
        if self.effective_date > instant:
            return False
        return self.expiry_date is None or instant <= self.expiry_date


class DocumentChunk(BaseModel):
    """One retrievable unit of document text, always attributable to a
    (source_id, page, section)."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    source_id: str
    filename: str
    page: int
    section: str | None
    text: str
    normalized_text: str
    status: SourceStatus
    source_type: SourceType
    account_scope: str | None
    effective_date: date
    authority_class: AuthorityClass


class SlaTarget(BaseModel):
    """One (scope, severity) -> first-response target row, extracted from a
    plan x severity grid (Support Policy) or a per-account bullet list
    (agreements). See docs/initial_rules.md R5 and ADR note on table flattening.
    """

    model_config = ConfigDict(frozen=True)

    source_id: str
    plan: str | None  # set when scope_kind == "plan"
    account_id: str | None  # set when scope_kind == "account"
    severity: str
    target_text: str
    target_minutes: int | None  # only set when the text is an unambiguous clock duration
    is_24x7: bool
    requires_business_calendar: bool
