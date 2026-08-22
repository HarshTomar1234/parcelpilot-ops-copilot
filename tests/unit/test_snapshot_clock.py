from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.errors import InvalidSnapshotTimestampError
from app.time.clock import FixedSnapshotClock, parse_snapshot


def test_parses_readme_snapshot_exactly():
    dt = parse_snapshot("2026-08-16 11:00 Asia/Kolkata")
    assert dt == datetime(2026, 8, 16, 11, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def test_snapshot_date_is_a_sunday():
    dt = parse_snapshot("2026-08-16 11:00 Asia/Kolkata")
    assert dt.strftime("%A") == "Sunday"


def test_rejects_malformed_snapshot():
    with pytest.raises(InvalidSnapshotTimestampError):
        parse_snapshot("not a timestamp")


def test_rejects_unknown_timezone():
    with pytest.raises(InvalidSnapshotTimestampError):
        parse_snapshot("2026-08-16 11:00 Mars/Colony")


def test_fixed_clock_returns_constant_value():
    dt = parse_snapshot("2026-08-16 11:00 Asia/Kolkata")
    clock = FixedSnapshotClock(dt)
    assert clock.now() == dt
    assert clock.now() == dt  # repeated calls never drift


def test_fixed_clock_requires_timezone_aware_input():
    with pytest.raises(ValueError):
        FixedSnapshotClock(datetime(2026, 8, 16, 11, 0))
