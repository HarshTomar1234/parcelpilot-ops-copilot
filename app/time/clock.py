"""Authoritative time source for domain logic.

ADR-005: the reference "now" for dataset reasoning is the workbook README
snapshot, never the machine clock. Domain code must depend on SnapshotClock,
never call datetime.now() or time.time() directly.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from app.errors import InvalidSnapshotTimestampError

_SNAPSHOT_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2})\s+(?P<tz>[A-Za-z_]+/[A-Za-z_]+)$"
)


class SnapshotClock(Protocol):
    def now(self) -> datetime: ...


class FixedSnapshotClock:
    """The only clock implementation used in this codebase. now() always
    returns the same timezone-aware instant it was constructed with."""

    def __init__(self, snapshot: datetime) -> None:
        if snapshot.tzinfo is None:
            raise ValueError("FixedSnapshotClock requires a timezone-aware datetime")
        self._snapshot = snapshot

    def now(self) -> datetime:
        return self._snapshot

    def __repr__(self) -> str:
        return f"FixedSnapshotClock({self._snapshot.isoformat()})"


def parse_snapshot(raw: str) -> datetime:
    """Parse the README 'Dataset snapshot' cell, e.g.
    '2026-08-16 11:00 Asia/Kolkata', into a timezone-aware datetime.
    """
    match = _SNAPSHOT_PATTERN.match(raw.strip())
    if not match:
        raise InvalidSnapshotTimestampError(
            raw, "expected format 'YYYY-MM-DD HH:MM Area/Location'"
        )
    try:
        tz = ZoneInfo(match["tz"])
    except Exception as exc:
        raise InvalidSnapshotTimestampError(raw, f"unknown timezone {match['tz']!r}") from exc
    try:
        naive = datetime.fromisoformat(f"{match['date']}T{match['time']}")
    except ValueError as exc:
        raise InvalidSnapshotTimestampError(raw, f"unparseable date/time: {exc}") from exc
    return naive.replace(tzinfo=tz)
