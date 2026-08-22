"""GC-002-style ambiguous-entity clarification (Phase 4 s3). A question
needing a specific order/ticket/account must ask for clarification when
the caller's scope doesn't narrow to one obvious account - never silently
run a generic search and answer as if it applied to a guessed account.
Every fact asserted here was verified by actually running run_agent()
first - see app/agent/clarification.py.
"""

from __future__ import annotations

import pytest

from app.agent.context import AgentRequestContext
from app.agent.orchestrator import run_agent
from app.authorization.context import INTERNAL_SYSTEM_CONTEXT, AuthContext, Role
from app.llm.mock_provider import MockProvider
from app.observability.tracing import RequestContext

_AMBIGUOUS_QUESTION = (
    "A pickup is three hours late because of carrier fault. Should I get a service credit?"
)


@pytest.fixture()
def provider() -> MockProvider:
    return MockProvider()


def _ctx(auth: AuthContext, snapshot) -> AgentRequestContext:
    rc = RequestContext.new()
    return AgentRequestContext(
        request_id=rc.request_id, trace_id=rc.trace_id, user_id="test-user",
        auth=auth, dataset_snapshot_time=snapshot,
    )


def test_one_obvious_account_does_not_need_clarification(conn, clock, provider):
    auth = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["FX-001"])
    result = run_agent(_AMBIGUOUS_QUESTION, _ctx(auth, clock.now()), conn, provider)
    assert result.status != "needs_clarification"


def test_multiple_accounts_in_scope_needs_clarification(conn, clock, provider):
    auth = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["FX-001", "FX-002"])
    result = run_agent(_AMBIGUOUS_QUESTION, _ctx(auth, clock.now()), conn, provider)
    assert result.status == "needs_clarification"
    assert "2 accounts" in (result.reason or "")


def test_no_account_scope_at_all_needs_clarification(conn, clock, provider):
    result = run_agent(
        _AMBIGUOUS_QUESTION, _ctx(INTERNAL_SYSTEM_CONTEXT, clock.now()), conn, provider
    )
    assert result.status == "needs_clarification"
    assert "any account" in (result.reason or "")


def test_explicit_order_does_not_need_clarification(conn, clock, provider):
    auth = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["FX-001", "FX-002"])
    result = run_agent(
        "Is a service credit owed for FXO-2002?", _ctx(auth, clock.now()), conn, provider
    )
    assert result.status != "needs_clarification"


def test_explicit_account_name_does_not_need_clarification(conn, clock, provider):
    auth = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["FX-001", "FX-002"])
    result = run_agent(
        "Is Meridian Freight owed a service credit for a late pickup?",
        _ctx(auth, clock.now()), conn, provider,
    )
    assert result.status != "needs_clarification"


def test_reason_states_what_information_is_missing(conn, clock, provider):
    auth = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["FX-001", "FX-002"])
    result = run_agent(_AMBIGUOUS_QUESTION, _ctx(auth, clock.now()), conn, provider)
    assert result.reason is not None
    assert "account" in result.reason
    assert "order" in result.reason
    assert "ticket" in result.reason
