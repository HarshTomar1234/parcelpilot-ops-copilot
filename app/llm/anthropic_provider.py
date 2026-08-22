"""Real Anthropic-backed provider. Requires the optional `llm` extra
(pip install -e ".[llm]") - anthropic is imported lazily so the base
install and CI's fast test suite never need it or a network connection.

Untested against a live API in this environment (no ANTHROPIC_API_KEY was
available during development - see docs/_internal/phase-reports/phase-02.md).
The request/response shape is verified against the installed SDK's type
signatures; a real call has not been exercised.
"""

from __future__ import annotations

import time

from app.llm.pricing import PricingTable
from app.llm.types import CostEstimate, LLMRequest, LLMResponse, TokenUsage
from app.observability.tracing import RequestContext


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, pricing: PricingTable | None = None) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "AnthropicProvider requires the 'llm' extra: pip install -e '.[llm]'"
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key)
        self._pricing = pricing or PricingTable()

    def complete(self, request: LLMRequest, context: RequestContext) -> LLMResponse:
        start = time.perf_counter()
        system = next((m.content for m in request.messages if m.role == "system"), None)
        messages = [
            {"role": m.role, "content": m.content}
            for m in request.messages
            if m.role != "system"
        ]

        kwargs: dict[str, object] = {
            "model": request.model,
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "messages": messages,
            "timeout": request.timeout_seconds,
        }
        if system is not None:
            kwargs["system"] = system

        retries = 0
        response = None
        for attempt in range(request.max_retries + 1):
            try:
                response = self._client.messages.create(**kwargs)  # type: ignore[arg-type]
                break
            except Exception:
                retries = attempt
                if attempt == request.max_retries:
                    raise
        assert response is not None

        latency_ms = (time.perf_counter() - start) * 1000
        content = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        usage = TokenUsage(
            input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens
        )
        cost: CostEstimate = self._pricing.estimate_cost(
            request.model, usage.input_tokens, usage.output_tokens
        )

        return LLMResponse(
            content=content,
            provider=self.name,
            model=request.model,
            usage=usage,
            cost=cost,
            latency_ms=latency_ms,
            request_id=context.request_id,
            trace_id=context.trace_id,
            prompt_version=request.prompt_version,
            finish_reason=response.stop_reason,
            retries=retries,
        )
