from pathlib import Path

import pytest

from app.errors import MissingSourceFileError
from app.structured_data.workbook import load_workbook


def test_load_workbook_snapshot_and_counts(source_dir: Path):
    wb = load_workbook(source_dir / "ParcelPilot_Assessment_Data.xlsx")
    assert wb.snapshot.isoformat() == "2026-08-16T11:00:00+05:30"
    assert wb.currency == "INR"
    assert len(wb.accounts) == 4
    assert len(wb.orders) == 6
    assert len(wb.tickets) == 7


def test_all_order_and_ticket_accounts_resolve(source_dir: Path):
    wb = load_workbook(source_dir / "ParcelPilot_Assessment_Data.xlsx")
    account_ids = {a.account_id for a in wb.accounts}
    assert all(o.account_id in account_ids for o in wb.orders)
    assert all(t.account_id in account_ids for t in wb.tickets)


def test_datetimes_localized_to_snapshot_timezone(source_dir: Path):
    wb = load_workbook(source_dir / "ParcelPilot_Assessment_Data.xlsx")
    for order in wb.orders:
        assert order.booked_at.tzinfo is not None
        assert order.booked_at.utcoffset() == wb.snapshot.utcoffset()


def test_boolean_fields_are_real_booleans(source_dir: Path):
    wb = load_workbook(source_dir / "ParcelPilot_Assessment_Data.xlsx")
    northstar = next(a for a in wb.accounts if a.account_id == "ACCT-001")
    assert northstar.premium_support is True
    order = next(o for o in wb.orders if o.order_id == "ORD-2002")
    assert order.carrier_fault is True
    assert order.customer_fault is False


def test_missing_workbook_raises(tmp_path):
    with pytest.raises(MissingSourceFileError):
        load_workbook(tmp_path / "does_not_exist.xlsx")
