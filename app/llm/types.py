"""Provider-independent LLM request/response types. No module outside
app/llm may import an SDK (anthropic, openai, ...) directly - everything
downstream talks to these types and the LLMProvider protocol only.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LLMMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str


class LLMRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    messages: list[LLMMessage]
    model: str
    max_output_tokens: int = 1024
    temperature: float = 0.0
    timeout_seconds: float = 30.0
    max_retries: int = 2
    prompt_version: str | None = None


class TokenUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class CostEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_cost_usd: float
    output_cost_usd: float

    @property
    def total_cost_usd(self) -> float:
        return self.input_cost_usd + self.output_cost_usd


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str
    provider: str
    model: str
    usage: TokenUsage
    cost: CostEstimate
    latency_ms: float
    request_id: str
    trace_id: str
    prompt_version: str | None = None
    finish_reason: str | None = None
    retries: int = Field(default=0, ge=0)
