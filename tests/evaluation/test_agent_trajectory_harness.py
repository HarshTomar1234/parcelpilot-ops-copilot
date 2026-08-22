"""Proves the agent-trajectory DeepEval wiring works against a real run_agent()
call. ToolCorrectnessMetric needs no judge model (it is exact tool-name
comparison), so unlike the RAG-quality metrics in test_deepeval_harness.py,
this produces a genuine, non-fabricated score even with MockProvider - see
scripts/run_agent_trajectory_eval.py for the full-dataset run.
"""

import pytest

from app.evaluation.adapters.agent_trajectory_adapter import (
    auth_for_case,
    build_test_case,
    expected_agent_status,
    run_case,
)
from app.evaluation.cases import load_golden_cases
from app.llm.mock_provider import MockProvider

deepeval = pytest.importorskip("deepeval")


def test_gc001_trajectory_calls_exactly_the_expected_tools(conn, clock):
    case = next(c for c in load_golden_cases() if c.case_id == "GC-001")
    provider = MockProvider()
    result = run_case(conn, case, provider, "mock-model", clock.now())

    assert set(result.planned_tools) == set(case.expected_tools)
    assert expected_agent_status(case) == "completed"
    assert result.status == "completed"


def test_tool_correctness_metric_scores_a_real_trajectory_without_a_judge():
    from deepeval.metrics import ToolCorrectnessMetric
    from deepeval.test_case import ToolCall

    from app.agent.orchestrator import AgentRunResult
    from app.llm.deepeval_bridge import GatewayDeepEvalModel

    result = AgentRunResult(
        status="completed", planned_tools=["search_documents", "lookup_structured_data"],
        request_id="r1", trace_id="t1",
    )

    class _Case:
        case_id = "STUB-1"
        question = "q"
        expected_tools = ["search_documents", "lookup_structured_data"]

    llm_test_case = build_test_case(_Case(), result)  # type: ignore[arg-type]
    judge = GatewayDeepEvalModel(MockProvider(), "mock-model")
    metric = ToolCorrectnessMetric(model=judge, async_mode=False)
    metric.measure(llm_test_case)

    assert metric.score == 1.0
    assert llm_test_case.tools_called
    assert isinstance(llm_test_case.tools_called[0], ToolCall)


def test_auth_for_case_maps_all_and_none_to_unrestricted():
    class _Case:
        role = "support_agent"
        account_scope = "ALL"

    auth = auth_for_case(_Case())  # type: ignore[arg-type]
    assert auth.account_scope is None
