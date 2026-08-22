"""Provider-resilient LLM gateway (Phase 3 s19-20). Wraps an ordered list
of (LLMProvider, model) candidates and tries each in turn until one
succeeds - the orchestrator and response_composer never see a raw provider
exception, and never need to know how many providers exist behind the
gateway. Implements the same LLMProvider protocol shape as a single
provider (name + complete()), so it is a drop-in replacement anywhere a
provider is accepted; response_composer.py needs no change to use it.

Retry-within-a-provider (exponential backoff, transient-vs-permanent
classification) already lives inside each provider itself
(app/llm/anthropic_provider.py). This module's retry concept is one level
up - an entire provider unavailable after its own retries are exhausted -
so it does not duplicate that classification; it just catches whatever a
provider ultimately raises and falls over to the next candidate.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from app.llm.base import LLMProvider
from app.llm.types import LLMRequest, LLMResponse
from app.observability.tracing import RequestContext


class ProviderAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    model: str
    success: bool
    error: str | None = None
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
                attempts.append(
                    ProviderAttempt(
                        provider=candidate.provider.name, model=candidate.model,
                        success=False, error=str(exc), latency_ms=latency_ms,
                    )
                )
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
