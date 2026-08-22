import sqlite3
from zoneinfo import ZoneInfo

import pytest

from app.authorization.context import INTERNAL_SYSTEM_CONTEXT, AuthContext, Role
from app.errors import NotAuthorizedError, UnknownEntityError
from app.models.enums import TicketStatus
from app.structured_data.repository import (
    get_account,
    get_order,
    get_ticket,
    search_orders,
    search_tickets,
)

TZ = ZoneInfo("Asia/Kolkata")


def test_get_account_permissive_context(conn: sqlite3.Connection):
    account = get_account(conn, "ACCT-001", INTERNAL_SYSTEM_CONTEXT)
    assert account.account_name == "Northstar Logistics"


def test_get_unknown_account_raises(conn: sqlite3.Connection):
    with pytest.raises(UnknownEntityError):
        get_account(conn, "ACCT-999", INTERNAL_SYSTEM_CONTEXT)


def test_get_order_returns_typed_domain_object(conn: sqlite3.Connection):
    order = get_order(conn, "ORD-2002", INTERNAL_SYSTEM_CONTEXT, TZ)
    assert order.carrier == "RoadRunner"
    assert order.carrier_fault is True
    assert order.pickup_actual_at is None


def test_get_unknown_order_raises(conn: sqlite3.Connection):
    with pytest.raises(UnknownEntityError):
        get_order(conn, "ORD-9999", INTERNAL_SYSTEM_CONTEXT, TZ)


def test_scoped_context_blocks_out_of_scope_order(conn: sqlite3.Connection):
    scoped = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["ACCT-002"])
    with pytest.raises(NotAuthorizedError):
        get_order(conn, "ORD-1001", scoped, TZ)  # belongs to ACCT-001


def test_scoped_context_allows_in_scope_order(conn: sqlite3.Connection):
    scoped = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["ACCT-002"])
    order = get_order(conn, "ORD-2002", scoped, TZ)
    assert order.order_id == "ORD-2002"


def test_scoped_context_blocks_out_of_scope_ticket(conn: sqlite3.Connection):
    scoped = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["ACCT-003"])
    with pytest.raises(NotAuthorizedError):
        get_ticket(conn, "TKT-501", scoped, TZ)  # belongs to ACCT-001


def test_search_orders_scoped_filters_in_the_query(conn: sqlite3.Connection):
    scoped = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["ACCT-002"])
    orders = search_orders(conn, scoped, TZ)
    assert orders  # ACCT-002 has orders in the pack
    assert all(o.account_id == "ACCT-002" for o in orders)


def test_search_orders_out_of_scope_account_id_raises(conn: sqlite3.Connection):
    scoped = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["ACCT-002"])
    with pytest.raises(NotAuthorizedError):
        search_orders(conn, scoped, TZ, account_id="ACCT-001")


def test_search_tickets_by_status(conn: sqlite3.Connection):
    tickets = search_tickets(conn, INTERNAL_SYSTEM_CONTEXT, TZ, status=TicketStatus.OPEN)
    assert tickets
    assert all(t.status == TicketStatus.OPEN for t in tickets)


def test_search_tickets_unrestricted_context_sees_all_accounts(conn: sqlite3.Connection):
    tickets = search_tickets(conn, INTERNAL_SYSTEM_CONTEXT, TZ)
    assert {t.account_id for t in tickets} == {"ACCT-001", "ACCT-002", "ACCT-003", "ACCT-004"}
