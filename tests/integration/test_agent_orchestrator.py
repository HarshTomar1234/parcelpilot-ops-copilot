"""End-to-end agent tests against the real pack. Every fact asserted here
was verified by actually running run_agent() first - see the phase report.
"""

import pytest

from app.agent.budgets import AgentBudget
from app.agent.context import AgentRequestContext
from app.agent.intent import Intent
from app.agent.orchestrator import run_agent
from app.authorization.context import AuthContext, Role
from app.domain.outcomes import TrustState
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


def test_northstar_cancellation_question_is_confident_with_a_conflict(conn, auth, clock, provider):
    question = "Can Northstar cancel ORD-1001 without a cancellation fee? Explain why."
    result = run_agent(question, _ctx(auth, clock.now()), conn, provider)

    assert result.status == "completed"
    assert result.intent is Intent.CANCELLATION
    assert result.trust_state is TrustState.CONFIDENT
    assert result.conflicts and result.conflicts[0].winner_source_id == "SRC-05"
    assert any(c.source_id == "SRC-05" for c in result.citations)
    assert result.tool_calls == 3  # lookup, calculate, search
    assert result.llm_calls == 1


def test_sla_p1_breach_is_a_confident_completed_answer_not_an_escalated_status(
    conn, auth, clock, provider
):
    # needs_human_review=True here means "route this breach to an ops
    # workflow" (Support Policy v3 s4), not "the agent is unsure of its
    # answer" - matches golden case GC-008 (expected_status=answered,
    # expected_trust=CONFIDENT). See app/agent/orchestrator.py's comment on
    # why only TrustState.ESCALATE changes the agent's own response status.
    question = "Is TKT-501 within its first-response SLA?"
    result = run_agent(question, _ctx(auth, clock.now()), conn, provider)

    assert result.status == "completed"
    assert result.intent is Intent.SLA
    assert result.trust_state is TrustState.CONFIDENT  # confident it IS breached
    assert result.conflicts and result.conflicts[0].winner_source_id == "SRC-05"


def test_severity_question_does_not_escalate(conn, auth, clock, provider):
    result = run_agent("What severity is TKT-505?", _ctx(auth, clock.now()), conn, provider)
    assert result.status == "completed"
    assert result.intent is Intent.SEVERITY
    assert result.trust_state is TrustState.CONFIDENT


def test_unresolvable_question_is_insufficient_evidence(conn, auth, clock, provider):
    # No entity, no document match at all - the query has no searchable terms
    # once stopword-like tokens are stripped, so retrieval returns nothing.
    result = run_agent("   ", _ctx(auth, clock.now()), conn, provider)
    assert result.status == "insufficient_evidence"


def test_cross_account_order_reference_never_reaches_a_tool_call(conn, clock, provider):
    scoped = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["ACCT-002"])
    result = run_agent(
        "Can Northstar cancel ORD-1001 without a fee?", _ctx(scoped, clock.now()), conn, provider
    )
    # ORD-1001 belongs to ACCT-001; entity resolution must drop it silently,
    # not leak that it exists via an authorization error.
    assert "calculate_support_outcome" not in result.planned_tools or result.tool_calls == 1
    leaked = any(
        c.source_id == "SRC-07" and "ORD-1001" in (c.locator or "") for c in result.citations
    )
    assert not leaked
    assert result.status in ("insufficient_evidence", "completed")


def test_budget_of_zero_tool_calls_fails_safely(conn, auth, clock, provider):
    budget = AgentBudget(max_tool_calls=0)
    result = run_agent(
        "Can Northstar cancel ORD-1001?", _ctx(auth, clock.now()), conn, provider, budget=budget
    )
    assert result.status == "failed"
    assert "budget" in (result.reason or "").lower()


def test_state_trace_records_every_transition(conn, auth, clock, provider):
    result = run_agent("What severity is TKT-505?", _ctx(auth, clock.now()), conn, provider)
    assert result.state_trace[0] == "REQUEST_RECEIVED"
    assert result.state_trace[-1] == "COMPLETED"
    assert "TRUST_EVALUATED" in result.state_trace


def test_full_answer_is_json_serializable(conn, auth, clock, provider):
    question = "Can Northstar cancel ORD-1001 without a fee?"
    result = run_agent(question, _ctx(auth, clock.now()), conn, provider)
    payload = result.model_dump_json()
    assert '"status":"completed"' in payload
