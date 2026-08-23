"""EvaluationCase -> a real run_agent() trajectory -> DeepEval LLMTestCase.

Unlike deepeval_adapter.py (Phase 2, retrieval-only), this exercises the
actual agent (app/agent/orchestrator.py) end to end for each golden case,
using the case's own role/account_scope so authorization-sensitive cases
are evaluated exactly as that operator would be scoped. tools_called comes
from AgentRunResult.planned_tools - what the plan actually decided to
execute - never invented or backfilled from the expectation.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from deepeval.test_case import LLMTestCase, ToolCall

from app.agent.context import AgentRequestContext
from app.agent.orchestrator import AgentRunResult, run_agent
from app.authorization.context import AuthContext, Role
from app.evaluation.cases import EvaluationCase
from app.llm.base import LLMProvider
from app.observability.tracing import RequestContext


def auth_for_case(case: EvaluationCase) -> AuthContext:
    role = Role(case.role) if case.role else Role.OPERATIONS_ADMIN
    scope = case.account_scope
    if scope in (None, "ALL"):
        return AuthContext(role=role, account_scope=None)
    assert isinstance(scope, list)
    return AuthContext(role=role, account_scope=scope)


def expected_agent_status(case: EvaluationCase) -> str | None:
    """Maps the golden dataset's status vocabulary onto AgentStatus. Returns
    None for action_pending/action_completed/rejected - those describe the
    state-changing action flow, which is explicitly out of scope for
    Phase 3 (no actions this phase), so there is no in-scope status to
    compare against."""
    if case.expected_status == "answered":
        return "escalated" if case.expected_trust == "ESCALATE" else "completed"
    if case.expected_status in ("needs_clarification", "insufficient_evidence"):
        return case.expected_status
    return None


def run_case(
    conn: sqlite3.Connection,
    case: EvaluationCase,
    provider: LLMProvider,
    model: str,
    snapshot: datetime,
) -> AgentRunResult:
    auth = auth_for_case(case)
    rc = RequestContext.new()
    ctx = AgentRequestContext(
        request_id=rc.request_id, trace_id=rc.trace_id, user_id="eval-harness",
        auth=auth, dataset_snapshot_time=snapshot,
    )
    return run_agent(case.question, ctx, conn, provider, model=model)


def build_test_case(case: EvaluationCase, result: AgentRunResult) -> LLMTestCase:
    return LLMTestCase(
        input=case.question,
        actual_output=result.answer or "",
        name=case.case_id,
        tools_called=[ToolCall(name=name, input_parameters=None) for name in result.planned_tools],
        expected_tools=[ToolCall(name=name, input_parameters=None) for name in case.expected_tools],
    )
