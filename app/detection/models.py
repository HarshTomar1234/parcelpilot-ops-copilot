"""Typed models for Operations Radar (Phase 5 s3). An AlertCandidate is
produced only by a deterministic rule in app/detection/rules.py - never
by an LLM. count, threshold, severity, affected accounts, and evidence
are always code/data-derived; an optional LLM summary (app/detection/
summary.py) may only add explanatory prose, and cannot alter any of
those fields (it doesn't even receive write access to them - see
compose_alert_summary's signature).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.domain.outcomes import EvidenceRef, TrustState


class AlertType(StrEnum):
    SLA_BREACH = "sla_breach"
    SLA_APPROACHING = "sla_approaching"
    RECURRING_ISSUE = "recurring_issue"
    KNOWN_ISSUE_PATTERN = "known_issue_pattern"
    CARRIER_PATTERN = "carrier_pattern"
    OVERDUE_PICKUP = "overdue_pickup"


class AlertSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    alert_id: str  # deterministic fingerprint - see fingerprint.compute_alert_id
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    reason: str
    observed_count: int
    threshold: int
    time_window: str  # a config descriptor (e.g. "point-in-time", "14d"), not a resolved
    # absolute date range - so the same rule config always fingerprints the same way
    representative_records: list[str]
    affected_accounts: list[str]
    evidence: list[EvidenceRef]
    recommended_next_step: str
    trust_state: TrustState  # CONDITIONAL when the underlying calculation couldn't be
    # computed with full confidence (e.g. a business-hour SLA target) - never silently
    # promoted to CONFIDENT
    rule_version: str
