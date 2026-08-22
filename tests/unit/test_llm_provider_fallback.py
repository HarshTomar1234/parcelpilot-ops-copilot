"""Provider-fallback routing, tested with stub providers - no network call,
no real credentials, no dependency on the source pack.

Failing providers raise exceptions named after real SDK exception classes
(RateLimitError, AuthenticationError, ...) rather than a generic
RuntimeError, because app/llm/gateway.py classifies by exception type
name (app/llm/error_classification.py) - a RuntimeError would not match
either the retryable or the recognized-non-retryable set, so using named
stand-ins is what actually exercises the classification, not just the
happy path around it.
"""

from __future__ import annotations

import pytest

from app.llm.gateway import (
    AllProvidersFailedError,
    NonRetryableProviderError,
    ParcelPilotLLMGateway,
)
from app.llm.mock_provider import MockProvider
from app.llm.types import CostEstimate, LLMMessage, LLMRequest, LLMResponse, TokenUsage
from app.observability.tracing import RequestContext


class RateLimitError(Exception):
    """Stand-in for anthropic.RateLimitError - retryable by name."""


class AuthenticationError(Exception):
    """Stand-in for anthropic.AuthenticationError - not retryable by name."""


class _FailingProvider:
    def __init__(self, exc: Exception, name: str = "failing-provider") -> None:
        self.name = name
        self._exc = exc

    def complete(self, request: LLMRequest, context: RequestContext) -> LLMResponse:
        raise self._exc


def _request() -> LLMRequest:
    return LLMRequest(messages=[LLMMessage(role="user", content="hello")], model="placeholder")


def test_primary_success_records_a_single_attempt_and_no_fallback():
    gateway = ParcelPilotLLMGateway([(MockProvider(), "mock-model")])
    response = gateway.complete(_request(), RequestContext.new())

    assert response.provider == "mock"
    assert gateway.last_run is not None
    assert gateway.last_run.fallback_used is False
    assert gateway.last_run.fallback_reason is None
    assert len(gateway.last_run.provider_attempts) == 1
    assert gateway.last_run.provider_attempts[0].success is True


def test_retryable_failure_falls_over_to_the_next_provider():
    gateway = ParcelPilotLLMGateway(
        [
            (_FailingProvider(RateLimitError("rate limited")), "primary-model"),
            (MockProvider(), "mock-model"),
        ]
    )
    response = gateway.complete(_request(), RequestContext.new())

    assert response.provider == "mock"
    run = gateway.last_run
    assert run is not None
    assert run.fallback_used is True
    assert run.fallback_reason == "rate limited"
    assert len(run.provider_attempts) == 2
    assert run.provider_attempts[0].success is False
    assert run.provider_attempts[0].retryable is True
    assert run.provider_attempts[0].provider == "failing-provider"
    assert run.provider_attempts[1].success is True


def test_all_providers_failing_with_retryable_errors_raises_with_every_attempt_recorded():
    gateway = ParcelPilotLLMGateway(
        [
            (_FailingProvider(RateLimitError("outage one"), "p1"), "m1"),
            (_FailingProvider(RateLimitError("outage two"), "p2"), "m2"),
        ]
    )
    with pytest.raises(AllProvidersFailedError) as exc_info:
        gateway.complete(_request(), RequestContext.new())

    attempts = exc_info.value.attempts
    assert len(attempts) == 2
    assert [a.error for a in attempts] == ["outage one", "outage two"]
    assert all(a.retryable for a in attempts)
    assert gateway.last_run is not None
    assert gateway.last_run.total_cost_usd == 0.0


def test_non_retryable_failure_stops_immediately_without_trying_the_rest():
    fallback_provider_called = False

    class _NeverCalledProvider:
        name = "never-called"

        def complete(self, request: LLMRequest, context: RequestContext) -> LLMResponse:
            nonlocal fallback_provider_called
            fallback_provider_called = True
            return MockProvider().complete(request, context)

    gateway = ParcelPilotLLMGateway(
        [
            (_FailingProvider(AuthenticationError("bad api key"), "primary"), "primary-model"),
            (_NeverCalledProvider(), "fallback-model"),
        ]
    )
    with pytest.raises(NonRetryableProviderError) as exc_info:
        gateway.complete(_request(), RequestContext.new())

    assert not fallback_provider_called
    assert exc_info.value.attempt.error == "bad api key"
    assert exc_info.value.attempt.retryable is False
    run = gateway.last_run
    assert run is not None
    assert len(run.provider_attempts) == 1
    assert run.fallback_used is False


def test_empty_candidate_list_is_rejected_at_construction():
    with pytest.raises(ValueError, match="at least one"):
        ParcelPilotLLMGateway([])


def test_gateway_uses_each_candidates_own_model_not_the_request_model():
    # The request is built with model="placeholder"; the gateway must
    # substitute each candidate's own configured model before calling it.
    calls: list[str] = []

    class _RecordingProvider:
        name = "recording"

        def complete(self, request: LLMRequest, context: RequestContext) -> LLMResponse:
            calls.append(request.model)
            return LLMResponse(
                content="ok", provider=self.name, model=request.model,
                usage=TokenUsage(input_tokens=1, output_tokens=1),
                cost=CostEstimate(input_cost_usd=0.0, output_cost_usd=0.0),
                latency_ms=0.0, request_id=context.request_id, trace_id=context.trace_id,
            )

    gateway = ParcelPilotLLMGateway([(_RecordingProvider(), "specific-model-name")])
    gateway.complete(_request(), RequestContext.new())
    assert calls == ["specific-model-name"]
