"""Public-CI agent tests against the fabricated fixture corpus - proves the
agent generalizes past the real pack's ID conventions and specific data,
never needing PARCELPILOT_SOURCE_DIR. Every fact asserted here was verified
by actually running run_agent() against the fixture DB first.

Scope note: app/agent/tools.py always calls the domain functions with their
production fee/credit/applicability registries (never the fixture ones from
tests/fixtures/seed_fixture_db.py) - that is correct for a real deployment,
which must never use fixture business rules. So these tests assert on
architecture-level behavior (routing, authorization, citation shape) rather
than specific dollar amounts or waiver outcomes; exact fixture-registry
correctness is covered at the domain-function level in test_domain_rules.py.
"""

from __future__ import annotations

import pytest

from app.agent.context import AgentRequestContext
from app.agent.intent import Intent
from app.agent.orchestrator import run_agent
from app.authorization.context import AuthContext, Role
from app.llm.mock_provider import MockProvider
from app.observability.tracing import RequestContext


@pytest.fixture()
def provider() -> MockProvider:
    return MockProvider()


def _ctx(auth: AuthContext, snapshot) -> AgentRequestContext:
    rc = RequestContext.new()
    return AgentRequestContext(
        request_id=rc.request_id, trace_id=rc.trace_id, user_id="test-user",
        auth=auth, dataset_snapshot_time=snapshot,
    )


def test_non_standard_id_prefix_still_resolves_to_the_right_intent(conn, auth, clock, provider):
    # FXO-/FXT-/FX- deliberately differ from the real pack's ORD-/TKT-/ACCT- -
    # this is the generality check the fixture corpus exists to run.
    question = "Can Meridian Freight cancel FXO-1001 without a cancellation fee?"
    result = run_agent(question, _ctx(auth, clock.now()), conn, provider)

    assert result.status == "completed"
    assert result.intent is Intent.CANCELLATION
    assert result.planned_tools == [
        "lookup_structured_data", "calculate_support_outcome", "search_documents",
    ]
    assert result.tool_calls == 3


def test_service_credit_intent_resolves_on_fixture_order_id(conn, auth, clock, provider):
    result = run_agent(
        "Is a service credit owed for FXO-2002?", _ctx(auth, clock.now()), conn, provider
    )
    assert result.status == "completed"
    assert result.intent is Intent.SERVICE_CREDIT


def test_sla_intent_resolves_on_fixture_ticket_id(conn, auth, clock, provider):
    result = run_agent(
        "Is FXT-501 within its first-response SLA?", _ctx(auth, clock.now()), conn, provider
    )
    assert result.intent is Intent.SLA
    assert result.status in ("completed", "escalated")


def test_severity_intent_resolves_on_fixture_ticket_id(conn, auth, clock, provider):
    result = run_agent("What severity is FXT-505?", _ctx(auth, clock.now()), conn, provider)
    assert result.status == "completed"
    assert result.intent is Intent.SEVERITY


def test_cross_account_fixture_order_is_dropped_not_leaked(conn, clock, provider):
    scoped = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["FX-002"])
    question = "Can Meridian Freight cancel FXO-1001 without a fee?"
    result = run_agent(question, _ctx(scoped, clock.now()), conn, provider)

    # FXO-1001 belongs to FX-001, outside FX-002's scope - it must not
    # resolve to a targeted plan at all, regardless of ID shape.
    assert result.intent is not Intent.CANCELLATION
    assert "calculate_support_outcome" not in result.planned_tools
