"""Narrow typed data-access functions. Every function takes an AuthContext
and applies account-scope filtering before rows are returned - not as a
post-filter on already-fetched data (AGENTS.md rule 4, ADR-011).

No caller, present or future, gets a raw SQL escape hatch (AGENTS.md rule
11 / Phase 1I): these functions are the only way application code touches
accounts/orders/tickets.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, tzinfo

from app.authorization.context import AuthContext
from app.errors import NotAuthorizedError, UnknownEntityError
from app.models.enums import OrderStatus, TicketStatus
from app.models.structured import Account, Order, Ticket


def _check_scope(auth: AuthContext, account_id: str, entity_type: str, entity_id: str) -> None:
    if not auth.allows_account(account_id):
        raise NotAuthorizedError(f"{auth.role.value} cannot access {entity_type} {entity_id}")


def get_account(conn: sqlite3.Connection, account_id: str, auth: AuthContext) -> Account:
    if not auth.allows_account(account_id):
        raise NotAuthorizedError(f"{auth.role.value} cannot access account {account_id}")
    row = conn.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
    if row is None:
        raise UnknownEntityError("account", account_id)
    return _row_to_account(row)


def get_order(conn: sqlite3.Connection, order_id: str, auth: AuthContext, tz: tzinfo) -> Order:
    row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if row is None:
        raise UnknownEntityError("order", order_id)
    _check_scope(auth, row["account_id"], "order", order_id)
    return _row_to_order(row, tz)


def get_ticket(conn: sqlite3.Connection, ticket_id: str, auth: AuthContext, tz: tzinfo) -> Ticket:
    row = conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
    if row is None:
        raise UnknownEntityError("ticket", ticket_id)
    _check_scope(auth, row["account_id"], "ticket", ticket_id)
    return _row_to_ticket(row, tz)


def search_orders(
    conn: sqlite3.Connection,
    auth: AuthContext,
    tz: tzinfo,
    *,
    account_id: str | None = None,
    status: OrderStatus | None = None,
    carrier: str | None = None,
) -> list[Order]:
    if account_id is not None and not auth.allows_account(account_id):
        raise NotAuthorizedError(f"{auth.role.value} cannot access account {account_id}")

    clauses: list[str] = []
    params: list[object] = []
    if auth.account_scope is not None:
        placeholders = ", ".join("?" for _ in auth.account_scope)
        clauses.append(f"account_id IN ({placeholders})")
        params += auth.account_scope
    if account_id is not None:
        clauses.append("account_id = ?")
        params.append(account_id)
    if status is not None:
        clauses.append("status = ?")
        params.append(status.value)
    if carrier is not None:
        clauses.append("carrier = ?")
        params.append(carrier)

    sql = "SELECT * FROM orders"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY order_id"

    rows = conn.execute(sql, params).fetchall()
    return [_row_to_order(row, tz) for row in rows]


def search_tickets(
    conn: sqlite3.Connection,
    auth: AuthContext,
    tz: tzinfo,
    *,
    account_id: str | None = None,
    status: TicketStatus | None = None,
) -> list[Ticket]:
    if account_id is not None and not auth.allows_account(account_id):
        raise NotAuthorizedError(f"{auth.role.value} cannot access account {account_id}")

    clauses: list[str] = []
    params: list[object] = []
    if auth.account_scope is not None:
        placeholders = ", ".join("?" for _ in auth.account_scope)
        clauses.append(f"account_id IN ({placeholders})")
        params += auth.account_scope
    if account_id is not None:
        clauses.append("account_id = ?")
        params.append(account_id)
    if status is not None:
        clauses.append("status = ?")
        params.append(status.value)

    sql = "SELECT * FROM tickets"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY ticket_id"

    rows = conn.execute(sql, params).fetchall()
    return [_row_to_ticket(row, tz) for row in rows]


def _row_to_account(row: sqlite3.Row) -> Account:
    return Account(
        account_id=row["account_id"],
        account_name=row["account_name"],
        plan=row["plan"],
        status=row["status"],
        csm=row["csm"],
        contract_file=row["contract_file"],
        premium_support=bool(row["premium_support"]),
        notes=row["notes"],
    )


def _dt_optional(value: str | None, tz: tzinfo) -> datetime | None:
    if value is None:
        return None
    naive = datetime.fromisoformat(value)
    return naive if naive.tzinfo is not None else naive.replace(tzinfo=tz)


def _dt(value: str, tz: tzinfo) -> datetime:
    parsed = _dt_optional(value, tz)
    assert parsed is not None  # value is a required (NOT NULL) column
    return parsed


def _row_to_order(row: sqlite3.Row, tz: tzinfo) -> Order:
    return Order(
        order_id=row["order_id"],
        account_id=row["account_id"],
        carrier=row["carrier"],
        status=row["status"],
        booked_at=_dt(row["booked_at"], tz),
        pickup_window_start=_dt(row["pickup_window_start"], tz),
        pickup_window_end=_dt(row["pickup_window_end"], tz),
        pickup_actual_at=_dt_optional(row["pickup_actual_at"], tz),
        shipment_fee_inr=row["shipment_fee_inr"],
        carrier_fault=bool(row["carrier_fault"]),
        customer_fault=bool(row["customer_fault"]),
        cancellation_requested_at=_dt_optional(row["cancellation_requested_at"], tz),
        notes=row["notes"],
    )


def _row_to_ticket(row: sqlite3.Row, tz: tzinfo) -> Ticket:
    return Ticket(
        ticket_id=row["ticket_id"],
        account_id=row["account_id"],
        created_at=_dt(row["created_at"], tz),
        status=row["status"],
        subject=row["subject"],
        description=row["description"],
        channel=row["channel"],
        assigned_to=row["assigned_to"],
        last_customer_message_at=_dt(row["last_customer_message_at"], tz),
        historical_resolution=row["historical_resolution"],
    )
