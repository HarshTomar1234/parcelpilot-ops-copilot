"""Citation validation no longer silently strips an invalid marker and
returns the answer as if it were valid (Phase 4 pre-flight 1D). Sequence:
generated answer -> validate -> if invalid, one bounded repair attempt ->
validate again -> if still invalid, a controlled evidence_validation_failed
result. Uses a small stateful fake provider (first call answers with a
fabricated marker, second call is scripted to succeed or fail) since
MockProvider always echoes the prompt and cannot "get it right" on repair.
"""

from __future__ import annotations

from app.agent.budgets import AgentBudget
from app.agent.context import AgentRequestContext
from app.agent.orchestrator import run_agent
from app.llm.types import CostEstimate, LLMRequest, LLMResponse, TokenUsage
from app.observability.tracing import RequestContext

_CANCELLATION_QUESTION = "Can Meridian Freight cancel FXO-1001 without a cancellation fee?"


def _ctx(auth, snapshot) -> AgentRequestContext:
    rc = RequestContext.new()
    return AgentRequestContext(
        request_id=rc.request_id, trace_id=rc.trace_id, user_id="test-user",
        auth=auth, dataset_snapshot_time=snapshot,
    )


class _ScriptedProvider:
    """Returns each response in `answers` in order, one per call.complete()."""

    name = "scripted"

    def __init__(self, answers: list[str]) -> None:
        self._answers = list(answers)
        self.calls = 0

    def complete(self, request: LLMRequest, context: RequestContext) -> LLMResponse:
        content = self._answers[self.calls]
        self.calls += 1
        return LLMResponse(
            content=content, provider=self.name, model=request.model,
            usage=TokenUsage(input_tokens=1, output_tokens=1),
            cost=CostEstimate(input_cost_usd=0.001, output_cost_usd=0.001),
            latency_ms=0.0, request_id=context.request_id, trace_id=context.trace_id,
        )


def test_first_answer_invalid_then_repair_succeeds(conn, auth, clock):
    provider = _ScriptedProvider(
        [
            "The fee is waived [FAKE-999].",  # invalid marker
            "The fee is waived per the agreement.",  # repaired, no markers at all - valid
        ]
    )
    result = run_agent(_CANCELLATION_QUESTION, _ctx(auth, clock.now()), conn, provider)

    assert provider.calls == 2
    assert result.status == "completed"
    assert result.llm_calls == 2
    assert result.answer == "The fee is waived per the agreement."


def test_repair_still_invalid_returns_controlled_failure(conn, auth, clock):
    provider = _ScriptedProvider(
        [
            "The fee is waived [FAKE-999].",
            "The fee is waived [FAKE-999] again.",  # still invalid after repair
        ]
    )
    result = run_agent(_CANCELLATION_QUESTION, _ctx(auth, clock.now()), conn, provider)

    assert provider.calls == 2
    assert result.status == "evidence_validation_failed"
    assert "FAKE-999" in (result.reason or "")
    assert "bounded repair attempt" in (result.reason or "")
    assert result.llm_calls == 2
    # the deterministic investigation is preserved even though the answer failed
    assert result.tool_calls == 3
    assert result.citations  # real evidence pack citations, not the bad answer text


def test_no_repair_attempted_when_llm_call_budget_is_one(conn, auth, clock):
    provider = _ScriptedProvider(["The fee is waived [FAKE-999]."])
    budget = AgentBudget(max_llm_calls=1)
    result = run_agent(
        _CANCELLATION_QUESTION, _ctx(auth, clock.now()), conn, provider, budget=budget
    )

    assert provider.calls == 1  # no repair call attempted
    assert result.status == "evidence_validation_failed"
    assert "no repair attempt was available" in (result.reason or "")
    assert result.llm_calls == 1


def test_valid_first_answer_never_triggers_a_repair_call(conn, auth, clock):
    provider = _ScriptedProvider(["A clean answer with no citation markers at all."])
    result = run_agent(_CANCELLATION_QUESTION, _ctx(auth, clock.now()), conn, provider)

    assert provider.calls == 1
    assert result.status == "completed"
    assert result.llm_calls == 1
