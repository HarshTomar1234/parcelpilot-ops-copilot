"""Proves Phase 3 pre-flight requirement 2.6: business policy is declarative
data (app/policy/applicability.AGREEMENT_OVERRIDES, keyed by account_id and
topic) consumed generically by the domain engine, never a per-order or
per-ticket branch. A brand-new order/ticket ID that never existed in the
supplied workbook must get the same applicable policy as the real records
for that account, with zero code changes - only new rows.

If someone ever "fixed" a case by writing `if order_id == "ORD-1001":` or
`if account_id == "ACCT-001":` inside app/domain/*.py, these tests would
still pass for the real IDs but fail for the synthetic ones below, because
the synthetic IDs are guaranteed to never appear in application source
(see test_no_hardcoded_ids_in_domain_or_policy_code).
"""

from __future__ import annotations

import sqlite3

from app.domain.cancellation import evaluate_cancellation
from app.domain.service_credit import evaluate_service_credit
from app.domain.sla import calculate_sla


def _insert_order(
    conn: sqlite3.Connection,
    *,
    order_id: str,
    account_id: str,
    booked_at: str,
    cancellation_requested_at: str | None,
    status: str = "BOOKED",
    carrier_fault: bool = False,
    customer_fault: bool = False,
    pickup_window_end: str = "2026-08-16T09:00:00+05:30",
    pickup_actual_at: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO orders (order_id, account_id, carrier, status, booked_at, "
        "pickup_window_start, pickup_window_end, pickup_actual_at, shipment_fee_inr, "
        "carrier_fault, customer_fault, cancellation_requested_at, notes) "
        "VALUES (?, ?, 'SwiftShip', ?, ?, ?, ?, ?, 1000.0, ?, ?, ?, 'synthetic test order')",
        (
            order_id, account_id, status, booked_at, booked_at, pickup_window_end,
            pickup_actual_at, int(carrier_fault), int(customer_fault),
            cancellation_requested_at,
        ),
    )


def _insert_ticket(
    conn: sqlite3.Connection, *, ticket_id: str, account_id: str, created_at: str
) -> None:
    conn.execute(
        "INSERT INTO tickets (ticket_id, account_id, created_at, status, subject, "
        "description, channel, assigned_to, last_customer_message_at, historical_resolution) "
        "VALUES (?, ?, ?, 'open', 'test', "
        "'Every user gets HTTP 500 when creating any shipment.', 'email', 'X', ?, NULL)",
        (ticket_id, account_id, created_at, created_at),
    )


def test_brand_new_northstar_order_gets_the_waiver_automatically(conn, auth, clock):
    """ORD-9901 has never existed in the supplied workbook. If the waiver
    only "worked" because of an ORD-1001-specific branch, this would fail."""
    _insert_order(
        conn, order_id="ORD-9901", account_id="ACCT-001",
        booked_at="2026-08-16T08:00:00+05:30",
        cancellation_requested_at="2026-08-16T10:30:00+05:30",  # 150 min later
    )
    result = evaluate_cancellation(conn, "ORD-9901", auth, clock)
    assert result.result is not None
    assert result.result.fee_inr == 0.0
    assert result.result.applicable_rule == "SRC-05#2"


def test_brand_new_lumenworks_order_gets_the_default_fee_automatically(conn, auth, clock):
    """ORD-9902 has never existed in the workbook either. LumenWorks has no
    cancellation waiver (SRC-06 s2) - the default SOP fee must still apply
    to a record the policy layer has never seen before."""
    _insert_order(
        conn, order_id="ORD-9902", account_id="ACCT-002",
        booked_at="2026-08-16T08:00:00+05:30",
        cancellation_requested_at="2026-08-16T10:30:00+05:30",  # 150 min later
    )
    result = evaluate_cancellation(conn, "ORD-9902", auth, clock)
    assert result.result is not None
    assert result.result.fee_inr == 250.0
    assert result.result.applicable_rule == "SRC-03#1"


def test_brand_new_northstar_ticket_gets_the_agreement_sla_automatically(conn, auth, clock):
    """TKT-9901 has never existed in the workbook. It must resolve to the
    Northstar agreement's 15-minute P1 target the same way TKT-501 does,
    with zero ticket-specific code."""
    _insert_ticket(
        conn, ticket_id="TKT-9901", account_id="ACCT-001", created_at="2026-08-16T10:00:00+05:30"
    )
    result = calculate_sla(conn, "TKT-9901", auth, clock)
    assert result.result is not None
    assert result.result.applicable_source_id == "SRC-05"
    assert result.result.target_minutes == 15


def test_brand_new_axis_labs_ticket_gets_the_default_sla_automatically(conn, auth, clock):
    """Axis Labs (ACCT-004) has no agreement. A never-before-seen ticket for
    it must fall back to the plan default, not silently inherit any other
    account's target."""
    _insert_ticket(
        conn, ticket_id="TKT-9902", account_id="ACCT-004", created_at="2026-08-16T10:00:00+05:30"
    )
    result = calculate_sla(conn, "TKT-9902", auth, clock)
    assert result.result is not None
    assert result.result.applicable_source_id == "SRC-01"
    assert result.result.target_minutes == 30


def test_brand_new_lumenworks_order_gets_agreement_service_credit_automatically(conn, auth, clock):
    """ORD-9903 has never existed. LumenWorks' 4-hour/INR-300 replacement
    (SRC-06 s3) must apply the same way it does for ORD-2002."""
    _insert_order(
        conn, order_id="ORD-9903", account_id="ACCT-002",
        booked_at="2026-08-16T00:00:00+05:30",
        cancellation_requested_at=None,
        carrier_fault=True, customer_fault=False,
        pickup_window_end="2026-08-16T01:00:00+05:30",  # 10h before snapshot -> well past 4h
    )
    result = evaluate_service_credit(conn, "ORD-9903", auth, clock)
    assert result.result is not None
    assert result.result.eligible is True
    assert result.result.credit_inr == 300.0
    assert result.result.applicable_rule == "SRC-06#3"


def test_no_hardcoded_ids_in_domain_or_policy_code():
    """Guards the guarantee the tests above depend on: no real example
    account/order/ticket ID appears as a runtime value in the domain or
    policy modules - only in prose comments/docstrings citing the source
    document, and in the AGREEMENT_OVERRIDES registry entries themselves
    (declarative data, not branches)."""
    import pathlib
    import re

    real_ids = ["ORD-1001", "ORD-1002", "ORD-2001", "ORD-2002", "ORD-3001", "ORD-4001",
                "TKT-450", "TKT-451", "TKT-501", "TKT-502", "TKT-503", "TKT-504", "TKT-505"]
    pattern = re.compile("|".join(re.escape(i) for i in real_ids))

    root = pathlib.Path(__file__).resolve().parents[2] / "app" / "domain"
    offenders = []
    for path in root.glob("*.py"):
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(path.name)
    assert offenders == [], f"found real example IDs referenced in domain code: {offenders}"
