"""Proves the DeepEval wiring (retrieval -> LLMTestCase -> judge bridge)
works up to the documented mock-judge limitation, without running the full
16-case baseline script. See scripts/run_deepeval_baseline.py and
docs/deepeval_baseline.md for the full run and its honest result.
"""

import pytest

from app.evaluation.adapters.deepeval_adapter import build_test_case
from app.evaluation.cases import load_golden_cases
from app.llm.deepeval_bridge import GatewayDeepEvalModel
from app.llm.mock_provider import MockProvider

deepeval = pytest.importorskip("deepeval")


def test_build_test_case_populates_retrieval_context_from_real_search(conn, auth):
    case = next(c for c in load_golden_cases() if c.case_id == "GC-001")
    provider = MockProvider()
    test_case = build_test_case(conn, case, auth, provider, "mock-model")

    assert test_case.input == case.question
    assert test_case.retrieval_context
    assert any("SRC-05" in str(ctx) for ctx in test_case.retrieval_context)
    assert test_case.actual_output is not None
    assert test_case.actual_output.startswith("[mock response to:")


def test_gateway_deepeval_model_generates_via_the_configured_provider():
    provider = MockProvider()
    judge = GatewayDeepEvalModel(provider, "mock-model")
    output = judge.generate("Is this relevant?")
    assert output.startswith("[mock response to:")
    assert judge.get_model_name() == "mock/mock-model"


def test_mock_judge_cannot_satisfy_deepeval_structured_output(conn, auth):
    """Documents the exact, stable failure mode scripts/run_deepeval_baseline.py
    catches and reports as 'harness-blocked' rather than a crash - a real
    LLM_API_KEY is required for an actual quality score."""
    from deepeval.metrics import ContextualRelevancyMetric

    case = next(c for c in load_golden_cases() if c.case_id == "GC-001")
    provider = MockProvider()
    judge = GatewayDeepEvalModel(provider, "mock-model")
    test_case = build_test_case(conn, case, auth, provider, "mock-model")

    metric = ContextualRelevancyMetric(model=judge, async_mode=False, include_reason=False)
    with pytest.raises(ValueError, match="invalid JSON"):
        metric.measure(test_case)
