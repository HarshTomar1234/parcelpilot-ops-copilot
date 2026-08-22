"""Wraps our own LLMProvider gateway as a DeepEval judge model.

This is the point of ADR-017's provider abstraction: DeepEval's LLM-based
metrics (faithfulness, contextual relevancy) need a judge model, and that
judge goes through the same gateway as everything else - never a direct
`deepeval` default (OpenAI) or a second, uncoupled SDK dependency.

With MockProvider, the judge is deterministic and free, which is what lets
scripts/run_deepeval_baseline.py run in CI with no API key. That also means
MockProvider-judged scores are a harness/plumbing signal only, not a real
quality signal - see docs/_internal/phase-reports/phase-02.md.
"""

from __future__ import annotations

from deepeval.models.base_model import DeepEvalBaseLLM

from app.llm.base import LLMProvider
from app.llm.types import LLMMessage, LLMRequest
from app.observability.tracing import RequestContext


class GatewayDeepEvalModel(DeepEvalBaseLLM):
    def __init__(self, provider: LLMProvider, model_name: str) -> None:
        self._provider = provider
        self._model_name = model_name
        super().__init__()

    def load_model(self) -> LLMProvider:
        return self._provider

    def generate(self, prompt: str) -> str:
        request = LLMRequest(
            messages=[LLMMessage(role="user", content=prompt)], model=self._model_name
        )
        response = self._provider.complete(request, RequestContext.new())
        return response.content

    async def a_generate(self, prompt: str) -> str:
        return self.generate(prompt)

    def get_model_name(self) -> str:
        return f"{self._provider.name}/{self._model_name}"
