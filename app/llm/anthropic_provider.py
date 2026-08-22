"""Real Anthropic-backed provider. Requires the optional `llm` extra
(pip install -e ".[llm]") - anthropic is imported lazily so the base
install and CI's fast test suite never need it or a network connection.

Retry classification (Phase 3 pre-flight 2.4): only failures that are
plausibly transient are retried. A permanent client error (bad request,
auth, an invalid model name) retried five times just fails five times
slower - it never becomes retryable by waiting.

Untested against a live API in this environment (no ANTHROPIC_API_KEY was
available - see docs/_internal/phase-reports/). The retry/backoff logic
itself IS tested, by injecting a mocked `messages.create` that raises
specific SDK exception types and a no-op sleep function - see
tests/unit/test_anthropic_retry.py.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from app.llm.error_classification import is_retryable_provider_error
from app.llm.pricing import PricingTable
from app.llm.types import CostEstimate, LLMRequest, LLMResponse, TokenUsage
from app.observability.tracing import RequestContext

# Classification (which exception type names are retryable) now lives in
# app/llm/error_classification.py, shared with the gateway's provider-level
# fallback decision (Phase 4 pre-flight 1C) - this module used to keep its
# own copy. Classification here is by actual exception type name, not the
# SDK's RetryableError marker - that marker exists in the SDK but is not
# actually applied to any of these built-in exception classes, so it is not
# usable for this purpose (verified against anthropic==1.0.0 by inspecting
# __mro__, not assumed from the name).


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        pricing: PricingTable | None = None,
        base_delay_seconds: float = 0.5,
        max_delay_seconds: float = 8.0,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "AnthropicProvider requires the 'llm' extra: pip install -e '.[llm]'"
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key)
        self._pricing = pricing or PricingTable()
        self._base_delay = base_delay_seconds
        self._max_delay = max_delay_seconds
        self._sleep = sleep_fn

    def _backoff_delay(self, attempt: int) -> float:
        """Exponential backoff with full jitter: a random delay in
        [0, min(max_delay, base * 2**attempt)], per the standard AWS
        architecture-blog formula - avoids every retrying client waking up
        at the same instant after a shared outage."""
        upper_bound = min(self._max_delay, self._base_delay * (2**attempt))
        return random.uniform(0, upper_bound)

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

        response = None
        retries = 0
        for attempt in range(request.max_retries + 1):
            try:
                response = self._client.messages.create(**kwargs)  # type: ignore[arg-type]
                break
            except Exception as exc:
                is_last_attempt = attempt == request.max_retries
                if is_last_attempt or not is_retryable_provider_error(exc):
                    raise
                retries = attempt + 1
                self._sleep(self._backoff_delay(attempt))
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
