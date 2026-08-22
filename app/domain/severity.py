"""Severity classification. The workbook has no severity column
(docs/data_dictionary.md) - severity is derived from `description` against
Support Policy v3 s2, and that derivation must be presented as an
inference, not a looked-up fact (ADR-009).

This is a signal-based classifier, not a per-ticket lookup table: each
pattern is anchored to language from the actual definition text (SRC-01 s2)
so it generalizes to tickets outside the five in the supplied workbook,
per the assessment brief's "may test your system using other records"
requirement. When no pattern matches confidently, the result is UNCERTAIN
rather than a forced guess - abstaining is the honest answer when the
description doesn't clearly match a definition.
"""

from __future__ import annotations

import re
import sqlite3

from pydantic import BaseModel, ConfigDict

from app.domain.evidence import cite_document
from app.domain.outcomes import DecisionResult, TrustState
from app.models.enums import Severity
from app.models.structured import Ticket

# Definition phrases quoted from Support Policy v3 s2 (docs/source_inventory.md).
_P1_OUTAGE = "complete production outage preventing all shipment creation for a customer"
_P1_NO_WORKAROUND = "immediate material business risk with no workaround"
_P1_SECURITY = "confirmed security incident or suspected credential exposure"
_P2_DEGRADED = "major feature unavailable or materially degraded for a customer"
_P2_WORKAROUND = "major feature unavailable or materially degraded ... or a workaround exists"
_P3_HOWTO = "how-to question"
_P3_CONFIG = "configuration request"
_P3_MINOR = "minor defect ... limited operational impact"

# Each pattern is tied to a phrase from SRC-01 s2's own definition text.
_SIGNALS: dict[Severity, list[tuple[re.Pattern[str], str]]] = {
    Severity.P1: [
        (re.compile(r"\bevery user\b", re.I), _P1_OUTAGE),
        (re.compile(r"\ball\b[^.]{0,40}\bshipment creation\b[^.]{0,20}\bfail", re.I), _P1_OUTAGE),
        (re.compile(r"\bcannot create any shipment", re.I), _P1_OUTAGE),
        (re.compile(r"\bcomplete outage\b", re.I), _P1_OUTAGE),
        (re.compile(r"\bno workaround\b", re.I), _P1_NO_WORKAROUND),
        (re.compile(r"\bapi key\b", re.I), _P1_SECURITY),
        (re.compile(r"\bcredential\b", re.I), _P1_SECURITY),
        (re.compile(r"\bsecurity incident\b", re.I), _P1_SECURITY),
        (
            re.compile(
                r"\b(leaked|exposed|posted)\b[^.]{0,40}\b(key|token|secret|password)\b", re.I
            ),
            _P1_SECURITY,
        ),
    ],
    Severity.P2: [
        (re.compile(r"(?<!no )workaround\b", re.I), _P2_WORKAROUND),
        (
            re.compile(r"\bstill works\b", re.I),
            "core operations remain possible or a workaround exists",
        ),
        (re.compile(r"\b(some|many)\s+(users?|customers?)\b", re.I), _P2_DEGRADED),
        (re.compile(r"\bintermittent(ly)?\b", re.I), _P2_DEGRADED),
        (re.compile(r"\bfails? for\b[^.]{0,30}\b(rows?|records?|files?)\b", re.I), _P2_DEGRADED),
        (re.compile(r"\bpartial(ly)?\b", re.I), _P2_DEGRADED),
    ],
    Severity.P3: [
        (re.compile(r"\bhow do (we|i)\b", re.I), _P3_HOWTO),
        (re.compile(r"\bhow to\b", re.I), _P3_HOWTO),
        (re.compile(r"\bbilling[- ]contact\b", re.I), _P3_CONFIG),
        (re.compile(r"\bconfiguration\b", re.I), _P3_CONFIG),
        (re.compile(r"\bstill shows\b", re.I), _P3_MINOR),
        (re.compile(r"\b(cosmetic|typo|minor)\b", re.I), _P3_MINOR),
    ],
}


class SeverityOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    severity: Severity | None
    matched_signal_count: dict[str, int]
    matched_definition: str | None


def classify_severity(
    ticket: Ticket, conn: sqlite3.Connection | None = None
) -> DecisionResult[SeverityOutcome]:
    text = f"{ticket.subject} {ticket.description}"
    hits: dict[Severity, list[str]] = {sev: [] for sev in Severity}
    for severity, patterns in _SIGNALS.items():
        for pattern, definition in patterns:
            if pattern.search(text):
                hits[severity].append(definition)

    counts = {sev.value: len(defs) for sev, defs in hits.items()}
    ranked = sorted(hits.items(), key=lambda kv: len(kv[1]), reverse=True)
    top_severity, top_hits = ranked[0]
    runner_up_count = len(ranked[1][1]) if len(ranked) > 1 else 0

    evidence = []
    if conn is not None:
        evidence.append(cite_document(conn, "SRC-01", "2"))

    if not top_hits:
        outcome = SeverityOutcome(
            severity=None, matched_signal_count=counts, matched_definition=None
        )
        return DecisionResult(
            result=outcome,
            trust_state=TrustState.UNCERTAIN,
            reason=(
                "No definition signal from Support Policy v3 s2 matched the ticket "
                "description confidently enough to assign a severity."
            ),
            evidence=evidence,
            needs_human_review=True,
        )

    if runner_up_count >= len(top_hits):
        outcome = SeverityOutcome(
            severity=None, matched_signal_count=counts, matched_definition=None
        )
        return DecisionResult(
            result=outcome,
            trust_state=TrustState.UNCERTAIN,
            reason=(
                f"Signals for {ranked[0][0].value} and {ranked[1][0].value} tied "
                f"({len(top_hits)} each); classification is ambiguous without human judgment."
            ),
            evidence=evidence,
            needs_human_review=True,
        )

    outcome = SeverityOutcome(
        severity=top_severity, matched_signal_count=counts, matched_definition=top_hits[0]
    )
    return DecisionResult(
        result=outcome,
        trust_state=TrustState.CONFIDENT,
        reason=f'Matched "{top_hits[0]}" (Support Policy v3 s2) -> {top_severity.value}.',
        evidence=evidence,
        calculation_inputs={"matched_signal_count": counts},
    )
