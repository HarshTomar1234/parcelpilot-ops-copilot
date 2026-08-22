"""Tool-contract tests: every future agent call goes through these three
functions, never through the repository/domain/retrieval modules directly.
"""

import pytest

from app.agent.tools import (
    CalculateSupportOutcomeRequest,
    CalculationType,
    LookupKind,
    LookupStructuredDataRequest,
    SearchDocumentsRequest,
    calculate_support_outcome_tool,
    lookup_structured_data_tool,
    search_documents_tool,
)
from app.authorization.context import AuthContext, Role
from app.errors import NotAuthorizedError
from app.models.structured import Account, Order, Ticket
from app.observability.tracing import RequestContext


@pytest.fixture()
def ctx() -> RequestContext:
    return RequestContext.new()


def test_search_documents_tool_returns_typed_results(conn, auth, ctx):
    response = search_documents_tool(
        conn, SearchDocumentsRequest(query="Northstar cancellation fee", top_k=3), auth, ctx
    )
    assert response.results
    assert response.results[0].source_id == "SRC-05"
    assert response.latency_ms >= 0


def test_search_documents_tool_applies_account_scope(conn, ctx):
    scoped = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["ACCT-002"])
    query = "Northstar agreement cancellation"
    response = search_documents_tool(
        conn, SearchDocumentsRequest(query=query, top_k=10), scoped, ctx
    )
    assert not any(r.source_id == "SRC-05" for r in response.results)


def test_lookup_get_order(conn, auth, clock, ctx):
    request = LookupStructuredDataRequest(kind=LookupKind.GET_ORDER, entity_id="ORD-1001")
    response = lookup_structured_data_tool(conn, request, auth, clock, ctx)
    assert len(response.records) == 1
    record = response.records[0]
    assert isinstance(record, Order)
    assert record.order_id == "ORD-1001"


def test_lookup_get_account(conn, auth, clock, ctx):
    request = LookupStructuredDataRequest(kind=LookupKind.GET_ACCOUNT, entity_id="ACCT-001")
    response = lookup_structured_data_tool(conn, request, auth, clock, ctx)
    record = response.records[0]
    assert isinstance(record, Account)
    assert record.account_name == "Northstar Logistics"


def test_lookup_get_ticket(conn, auth, clock, ctx):
    request = LookupStructuredDataRequest(kind=LookupKind.GET_TICKET, entity_id="TKT-501")
    response = lookup_structured_data_tool(conn, request, auth, clock, ctx)
    record = response.records[0]
    assert isinstance(record, Ticket)
    assert record.ticket_id == "TKT-501"


def test_lookup_search_orders_by_account(conn, auth, clock, ctx):
    request = LookupStructuredDataRequest(kind=LookupKind.SEARCH_ORDERS, account_id="ACCT-002")
    response = lookup_structured_data_tool(conn, request, auth, clock, ctx)
    assert response.records
    for record in response.records:
        assert isinstance(record, Order)
        assert record.account_id == "ACCT-002"


def test_lookup_search_tickets_by_status(conn, auth, clock, ctx):
    request = LookupStructuredDataRequest(kind=LookupKind.SEARCH_TICKETS, status="open")
    response = lookup_structured_data_tool(conn, request, auth, clock, ctx)
    assert response.records
    for record in response.records:
        assert isinstance(record, Ticket)
        assert record.status.value == "open"


def test_lookup_get_order_missing_entity_id_raises(conn, auth, clock, ctx):
    request = LookupStructuredDataRequest(kind=LookupKind.GET_ORDER)
    with pytest.raises(ValueError, match="entity_id is required"):
        lookup_structured_data_tool(conn, request, auth, clock, ctx)


def test_lookup_scoped_context_blocks_cross_account_order(conn, clock, ctx):
    scoped = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["ACCT-002"])
    request = LookupStructuredDataRequest(kind=LookupKind.GET_ORDER, entity_id="ORD-1001")
    with pytest.raises(NotAuthorizedError):
        lookup_structured_data_tool(conn, request, scoped, clock, ctx)


@pytest.mark.parametrize(
    ("calc_type", "entity_id", "expected_key", "expected_value"),
    [
        (CalculationType.CANCELLATION, "ORD-1001", "fee_inr", 0.0),
        (CalculationType.SERVICE_CREDIT, "ORD-2002", "credit_inr", 300.0),
        (CalculationType.SLA, "TKT-501", "breached", True),
        (CalculationType.SEVERITY, "TKT-501", "severity", "P1"),
    ],
)
def test_calculate_support_outcome_tool(
    conn, auth, clock, ctx, calc_type, entity_id, expected_key, expected_value
):
    request = CalculateSupportOutcomeRequest(calculation_type=calc_type, entity_id=entity_id)
    response = calculate_support_outcome_tool(conn, request, auth, clock, ctx)
    assert response.result is not None
    assert response.result[expected_key] == expected_value


def test_calculate_support_outcome_tool_response_is_json_serializable(conn, auth, clock, ctx):
    request = CalculateSupportOutcomeRequest(
        calculation_type=CalculationType.SLA, entity_id="TKT-501"
    )
    response = calculate_support_outcome_tool(conn, request, auth, clock, ctx)
    payload = response.model_dump_json()
    assert '"needs_human_review":true' in payload


def test_calculate_support_outcome_tool_scoped_context_blocks(conn, clock, ctx):
    scoped = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["ACCT-002"])
    request = CalculateSupportOutcomeRequest(
        calculation_type=CalculationType.CANCELLATION, entity_id="ORD-1001"
    )
    with pytest.raises(NotAuthorizedError):
        calculate_support_outcome_tool(conn, request, scoped, clock, ctx)
