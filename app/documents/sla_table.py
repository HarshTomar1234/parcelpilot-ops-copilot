"""Structured extraction of first-response SLA targets.

data/source_manifest.json flags that PyMuPDF flattens the Support Policy's
plan x severity grid to one line per cell, and the manifest requires that the
plan/severity/target association survive ingestion rather than being lost in
free text (docs/architecture_decision_record.md Phase 1D). This module
recovers that structure from the flattened line sequence.

Two shapes exist in the pack:
  - a Plan x P1/P2/P3 grid (Support Policy v3 s3, deprecated v2's single
    section) covering Enterprise/Growth/Standard;
  - a per-account bullet list ('- P1: 15 minutes, 24x7', ...) in each
    agreement's Support terms section.

Whether a target is a usable clock deadline is a parsing-quality fact (does
the text say "business"? does it say "24x7"?), not a business decision -
docs/architecture_decision_record.md ADR-007 makes the business-calendar
interpretation itself a later-phase decision.
"""

from __future__ import annotations

import re

from app.errors import DocumentParseError
from app.models.source import SlaTarget

_PLANS = ("Enterprise", "Growth", "Standard")
_SEVERITIES = ("P1", "P2", "P3")

_DURATION = re.compile(r"(?P<num>\d+)\s*(?P<unit>hour|hours|minute|minutes)\b")
_BULLET_TARGET = re.compile(r"P(?P<sev>[123]):\s*(?P<text>.+)")


def _parse_duration(text: str) -> tuple[int | None, bool, bool]:
    lower = text.lower()
    is_24x7 = "24x7" in lower
    requires_business_calendar = "business" in lower
    target_minutes = None
    if not requires_business_calendar:
        match = _DURATION.search(lower)
        if match:
            n = int(match["num"])
            target_minutes = n * 60 if match["unit"].startswith("hour") else n
    return target_minutes, is_24x7, requires_business_calendar


def parse_grid_table(body: str, source_id: str) -> list[SlaTarget]:
    """Parse a 'Plan / P1 / P2 / P3' grid flattened to one line per cell."""
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    try:
        header = lines.index("Plan")
    except ValueError as exc:
        raise DocumentParseError(source_id, "SLA grid header 'Plan' not found") from exc
    if lines[header : header + 4] != ["Plan", *_SEVERITIES]:
        raise DocumentParseError(source_id, "SLA grid header is not 'Plan/P1/P2/P3'")

    cursor = header + 4
    targets: list[SlaTarget] = []
    for plan in _PLANS:
        group = lines[cursor : cursor + 4]
        if len(group) < 4 or group[0] != plan:
            raise DocumentParseError(
                source_id, f"expected plan row {plan!r} at line {cursor}, got {group!r}"
            )
        for severity, text in zip(_SEVERITIES, group[1:], strict=True):
            minutes, is_247, biz = _parse_duration(text)
            targets.append(
                SlaTarget(
                    source_id=source_id,
                    plan=plan,
                    account_id=None,
                    severity=severity,
                    target_text=text,
                    target_minutes=minutes,
                    is_24x7=is_247,
                    requires_business_calendar=biz,
                )
            )
        cursor += 4
    return targets


def parse_bullet_targets(body: str, source_id: str, account_id: str) -> list[SlaTarget]:
    """Parse a per-account 'P1: ...' / 'P2: ...' / 'P3: ...' bullet list."""
    targets: list[SlaTarget] = []
    for line in body.splitlines():
        match = _BULLET_TARGET.search(line)
        if not match:
            continue
        text = match["text"].strip()
        minutes, is_247, biz = _parse_duration(text)
        targets.append(
            SlaTarget(
                source_id=source_id,
                plan=None,
                account_id=account_id,
                severity=f"P{match['sev']}",
                target_text=text,
                target_minutes=minutes,
                is_24x7=is_247,
                requires_business_calendar=biz,
            )
        )
    if len(targets) != len(_SEVERITIES):
        raise DocumentParseError(
            source_id, f"expected {len(_SEVERITIES)} bullet SLA targets, found {len(targets)}"
        )
    return targets
