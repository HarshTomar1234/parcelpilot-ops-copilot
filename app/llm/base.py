"""The provider-agnostic gateway boundary. No business or domain module may
import an SDK directly - everything downstream depends on LLMProvider only,
so a provider swap (or a LiteLLM-backed implementation later) never touches
call sites. See docs/architecture_decision_record.md ADR-016.
"""

from __future__ import annotations

from typing import Protocol

from app.llm.types import LLMRequest, LLMResponse
from app.observability.tracing import RequestContext


class LLMProvider(Protocol):
    name: str

    def complete(self, request: LLMRequest, context: RequestContext) -> LLMResponse: ...
