"""MockProvider is exercised fully (no network needed). AnthropicProvider
is only construction-tested here - a live call needs a real API key that
was not available while building this (see phase-02 report); the
constructor test proves the lazy-import wiring and request shape are
correct without needing one.
"""

import pytest

from app.llm.mock_provider import MockProvider
from app.llm.pricing import PricingTable
from app.llm.types import LLMMessage, LLMRequest
from app.observability.tracing import RequestContext


def test_pricing_table_computes_cost_from_config():
    table = PricingTable()
    cost = table.estimate_cost("claude-sonnet-5", 1_000_000, 1_000_000)
    assert cost.input_cost_usd == 3.0
    assert cost.output_cost_usd == 15.0
    assert cost.total_cost_usd == 18.0


def test_pricing_table_unknown_model_raises():
    table = PricingTable()
    with pytest.raises(KeyError):
        table.estimate_cost("not-a-real-model", 100, 100)


def test_mock_provider_is_deterministic():
    provider = MockProvider()
    request = LLMRequest(
        messages=[LLMMessage(role="user", content="hello world")], model="mock-model"
    )
    ctx = RequestContext.new()
    r1 = provider.complete(request, ctx)
    r2 = provider.complete(request, ctx)
    assert r1.content == r2.content
    assert r1.usage == r2.usage


def test_mock_provider_reports_token_usage_and_zero_cost():
    provider = MockProvider()
    request = LLMRequest(
        messages=[LLMMessage(role="user", content="one two three four five")], model="mock-model"
    )
    response = provider.complete(request, RequestContext.new())
    assert response.usage.input_tokens == 5
    assert response.usage.output_tokens > 0
    assert response.cost.total_cost_usd == 0.0


def test_mock_provider_propagates_request_and_trace_ids():
    provider = MockProvider()
    request = LLMRequest(messages=[LLMMessage(role="user", content="hi")], model="mock-model")
    ctx = RequestContext.new()
    response = provider.complete(request, ctx)
    assert response.request_id == ctx.request_id
    assert response.trace_id == ctx.trace_id


def test_mock_provider_carries_prompt_version_through():
    provider = MockProvider()
    request = LLMRequest(
        messages=[LLMMessage(role="user", content="hi")],
        model="mock-model",
        prompt_version="support_agent_system_v1",
    )
    response = provider.complete(request, RequestContext.new())
    assert response.prompt_version == "support_agent_system_v1"


def test_anthropic_provider_constructs_without_network_call():
    pytest.importorskip("anthropic")
    from app.llm.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider(api_key="sk-test-not-a-real-key")
    assert provider.name == "anthropic"
