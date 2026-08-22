"""Deterministic, no-network provider. Used by default in tests and CI so
the LLM gateway, cost accounting, and DeepEval harness are all exercised
without an API key. Token counts use a whitespace-split proxy, not a real
tokenizer - documented here, never presented as billing-accurate.
"""

from __future__ import annotations

import time

from app.llm.pricing import PricingTable
from app.llm.types import CostEstimate, LLMRequest, LLMResponse, TokenUsage
from app.observability.tracing import RequestContext

_MODEL_NAME = "mock-model"


def _approx_tokens(text: str) -> int:
    return max(1, len(text.split()))


class MockProvider:
    name = "mock"

    def __init__(self, pricing: PricingTable | None = None) -> None:
        self._pricing = pricing or PricingTable()

    def complete(self, request: LLMRequest, context: RequestContext) -> LLMResponse:
        start = time.perf_counter()
        last_user = next(
            (m.content for m in reversed(request.messages) if m.role == "user"), ""
        )
        content = f"[mock response to: {last_user[:80]}]"

        input_tokens = sum(_approx_tokens(m.content) for m in request.messages)
        output_tokens = _approx_tokens(content)
        cost: CostEstimate = self._pricing.estimate_cost(
            _MODEL_NAME, input_tokens, output_tokens
        )
        latency_ms = (time.perf_counter() - start) * 1000

        return LLMResponse(
            content=content,
            provider=self.name,
            model=_MODEL_NAME,
            usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
            cost=cost,
            latency_ms=latency_ms,
            request_id=context.request_id,
            trace_id=context.trace_id,
            prompt_version=request.prompt_version,
            finish_reason="stop",
        )
