"""Provider-resilient LLM gateway (Phase 3 s19-20, Phase 4 pre-flight 1C).
Wraps an ordered list of (LLMProvider, model) candidates and tries each in
turn until one succeeds - the orchestrator and response_composer never see
a raw provider exception, and never need to know how many providers exist
behind the gateway. Implements the same LLMProvider protocol shape as a
single provider (name + complete()), so it is a drop-in replacement
anywhere a provider is accepted; response_composer.py needs no change to
use it.

Retry-within-a-provider (exponential backoff, transient-vs-permanent
classification) already lives inside each provider itself
(app/llm/anthropic_provider.py). This module's retry concept is one level
up - an entire provider unavailable after its own retries are exhausted.

Fallback is not unconditional: a candidate's failure is classified with
the same shared rule anthropic_provider.py uses
(app/llm/error_classification.py) before deciding what to do next. A
transient failure (timeout, network error, 429, retryable 5xx) falls
over to the next candidate. A permanent failure (bad credentials, a
malformed request, an unknown model, insufficient permission, a schema
failure) stops immediately without trying the rest - falling back on a
config error would either repeat it against the next provider for no
reason or silently mask a real problem behind an apparent recovery.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from app.llm.base import LLMProvider
from app.llm.error_classification import is_retryable_provider_error
from app.llm.types import LLMRequest, LLMResponse
from app.observability.tracing import RequestContext


class ProviderAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    success: bool
    error: str | None = None
    retryable: bool = False
    latency_ms: float


class GatewayRunInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_attempts: list[ProviderAttempt]
    fallback_used: bool
    fallback_reason: str | None
    total_cost_usd: float
    total_latency_ms: float


class AllProvidersFailedError(Exception):
    def __init__(self, attempts: list[ProviderAttempt]) -> None:
        self.attempts = attempts
        summary = "; ".join(f"{a.provider}: {a.error}" for a in attempts)
        super().__init__(f"every configured LLM provider failed: {summary}")


class NonRetryableProviderError(Exception):
    """Raised immediately when a candidate fails with a permanent error -
    the gateway does not try the remaining candidates, since a config
    error (bad credentials, invalid model, malformed request) will fail
    identically against any provider."""

    def __init__(self, attempt: ProviderAttempt) -> None:
        self.attempt = attempt
        super().__init__(f"{attempt.provider} failed with a non-retryable error: {attempt.error}")


@dataclass(frozen=True)
class _Candidate:
    provider: LLMProvider
    model: str


class ParcelPilotLLMGateway:
    """name is the gateway's own identity for tracing; individual attempts
    record each real provider's name separately in provider_attempts."""

    name = "parcelpilot-gateway"

    def __init__(self, candidates: list[tuple[LLMProvider, str]]) -> None:
        if not candidates:
            raise ValueError("ParcelPilotLLMGateway requires at least one candidate provider")
        self._candidates = [_Candidate(provider=p, model=m) for p, m in candidates]
        self.last_run: GatewayRunInfo | None = None

    def complete(self, request: LLMRequest, context: RequestContext) -> LLMResponse:
        attempts: list[ProviderAttempt] = []
        start = time.perf_counter()

        for index, candidate in enumerate(self._candidates):
            attempt_start = time.perf_counter()
            scoped_request = request.model_copy(update={"model": candidate.model})
            try:
                response = candidate.provider.complete(scoped_request, context)
            except Exception as exc:  # noqa: BLE001 - the provider-fallback boundary
                latency_ms = (time.perf_counter() - attempt_start) * 1000
                retryable = is_retryable_provider_error(exc)
                attempt = ProviderAttempt(
                    provider=candidate.provider.name, model=candidate.model,
                    success=False, error=str(exc), retryable=retryable, latency_ms=latency_ms,
                )
                attempts.append(attempt)
                if not retryable:
                    self.last_run = GatewayRunInfo(
                        provider_attempts=attempts,
                        fallback_used=False,
                        fallback_reason=attempt.error,
                        total_cost_usd=0.0,
                        total_latency_ms=(time.perf_counter() - start) * 1000,
                    )
                    raise NonRetryableProviderError(attempt) from exc
                continue

            latency_ms = (time.perf_counter() - attempt_start) * 1000
            attempts.append(
                ProviderAttempt(
                    provider=candidate.provider.name, model=candidate.model,
                    success=True, latency_ms=latency_ms,
                )
            )
            fallback_used = index > 0
            self.last_run = GatewayRunInfo(
                provider_attempts=attempts,
                fallback_used=fallback_used,
                fallback_reason=attempts[0].error if fallback_used else None,
                total_cost_usd=response.cost.total_cost_usd,
                total_latency_ms=(time.perf_counter() - start) * 1000,
            )
            return response

        self.last_run = GatewayRunInfo(
            provider_attempts=attempts,
            fallback_used=len(attempts) > 1,
            fallback_reason=attempts[0].error if attempts else None,
            total_cost_usd=0.0,
            total_latency_ms=(time.perf_counter() - start) * 1000,
        )
        raise AllProvidersFailedError(attempts)
