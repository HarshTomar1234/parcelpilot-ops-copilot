"""Every AgentBudget field must correspond to a real enforcement mechanism
(Phase 4 pre-flight 1A). max_tool_calls and max_wall_clock_seconds were
already enforced in Phase 3; this file covers the three that were not:
max_iterations, max_context_tokens, max_estimated_cost_usd - plus a check
that max_output_tokens actually reaches the LLM request, not just sits in
the budget object unused.
"""

from __future__ import annotations

import pytest

from app.agent.budgets import AgentBudget
from app.agent.context import AgentRequestContext
from app.agent.orchestrator import run_agent
from app.llm.mock_provider import MockProvider
from app.llm.types import LLMRequest, LLMResponse
from app.observability.tracing import RequestContext


@pytest.fixture()
def provider() -> MockProvider:
    return MockProvider()


def _ctx(auth, snapshot) -> AgentRequestContext:
    rc = RequestContext.new()
    return AgentRequestContext(
        request_id=rc.request_id, trace_id=rc.trace_id, user_id="test-user",
        auth=auth, dataset_snapshot_time=snapshot,
    )


_CANCELLATION_QUESTION = "Can Meridian Freight cancel FXO-1001 without a cancellation fee?"


def test_iteration_budget_stops_a_multi_step_plan(conn, auth, clock, provider):
    # FXO-1001's cancellation plan needs 3 tool calls (lookup, calculate,
    # search); a budget of 1 iteration must stop before the 2nd.
    budget = AgentBudget(max_iterations=1)
    result = run_agent(
        _CANCELLATION_QUESTION, _ctx(auth, clock.now()), conn, provider, budget=budget
    )
    assert result.status == "failed"
    assert "iteration budget" in (result.reason or "")
    assert result.tool_calls == 1


def test_iteration_budget_of_default_size_does_not_block_a_normal_plan(conn, auth, clock, provider):
    result = run_agent(
        _CANCELLATION_QUESTION, _ctx(auth, clock.now()), conn, provider,
    )
    assert result.status != "failed"


def test_context_token_budget_rejects_an_undersized_budget(conn, auth, clock, provider):
    # A real evidence pack's rendered prompt is always more than a handful
    # of tokens - a budget of 1 token must be impossible to satisfy.
    budget = AgentBudget(max_context_tokens=1)
    result = run_agent(
        _CANCELLATION_QUESTION, _ctx(auth, clock.now()), conn, provider, budget=budget
    )
    assert result.status == "failed"
    assert "context size" in (result.reason or "")
    # The tool loop still ran (evidence was gathered) - only the LLM call
    # is blocked, not the deterministic investigation that already happened.
    assert result.tool_calls == 3


def test_cost_budget_rejects_a_real_model_with_a_zero_dollar_budget(conn, auth, clock, provider):
    budget = AgentBudget(max_estimated_cost_usd=0.0)
    rc = RequestContext.new()
    ctx = AgentRequestContext(
        request_id=rc.request_id, trace_id=rc.trace_id, user_id="test-user",
        auth=auth, dataset_snapshot_time=clock.now(),
    )
    result = run_agent(
        _CANCELLATION_QUESTION, ctx, conn, provider, model="claude-sonnet-5", budget=budget
    )
    assert result.status == "failed"
    assert "cost" in (result.reason or "")


def test_cost_budget_does_not_block_the_free_mock_model(conn, auth, clock, provider):
    budget = AgentBudget(max_estimated_cost_usd=0.0)
    result = run_agent(
        _CANCELLATION_QUESTION, _ctx(auth, clock.now()), conn, provider,
        model="mock-model", budget=budget,
    )
    assert result.status != "failed"  # mock-model is priced at $0 - nothing to block


def test_all_providers_failing_becomes_a_controlled_failure_not_a_raw_exception(
    conn, auth, clock
):
    from app.llm.gateway import ParcelPilotLLMGateway

    class _AlwaysFailingProvider:
        name = "always-failing"

        def complete(self, request: LLMRequest, context: RequestContext) -> LLMResponse:
            raise RuntimeError("simulated permanent outage")

    gateway = ParcelPilotLLMGateway([(_AlwaysFailingProvider(), "m1")])
    result = run_agent(
        _CANCELLATION_QUESTION, _ctx(auth, clock.now()), conn, gateway,
    )
    assert result.status == "failed"
    assert "response composition failed" in (result.reason or "")
    assert result.tool_calls == 3  # deterministic investigation still completed


def test_max_output_tokens_reaches_the_llm_request(conn, auth, clock):
    captured: list[LLMRequest] = []

    class _RecordingProvider:
        name = "recording"

        def complete(self, request: LLMRequest, context: RequestContext) -> LLMResponse:
            captured.append(request)
            return MockProvider().complete(request, context)

    budget = AgentBudget(max_output_tokens=17)
    run_agent(
        _CANCELLATION_QUESTION, _ctx(auth, clock.now()), conn, _RecordingProvider(),
        budget=budget,
    )
    assert captured
    assert captured[0].max_output_tokens == 17
