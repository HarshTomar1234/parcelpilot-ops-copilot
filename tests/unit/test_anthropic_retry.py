"""Retry classification and backoff, tested without any network call:
`_client.messages.create` is monkeypatched to raise specific SDK exception
types (or succeed) on a scripted schedule, and `sleep_fn` is replaced with a
recorder instead of a real sleep, so this suite runs in milliseconds and
exercises the exact logic a live retry would hit.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

anthropic = pytest.importorskip("anthropic")
httpx2 = pytest.importorskip("httpx2")  # anthropic's vendored httpx fork

from app.llm.anthropic_provider import AnthropicProvider  # noqa: E402
from app.llm.pricing import PricingTable  # noqa: E402
from app.llm.types import LLMMessage, LLMRequest  # noqa: E402
from app.observability.tracing import RequestContext  # noqa: E402


def _mock_message(text: str = "hello") -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        stop_reason="end_turn",
    )


def _provider(sleep_calls: list[float] | None = None) -> AnthropicProvider:
    def _fake_sleep(seconds: float) -> None:
        if sleep_calls is not None:
            sleep_calls.append(seconds)

    return AnthropicProvider(
        api_key="sk-test-not-real",
        pricing=PricingTable(),
        base_delay_seconds=0.01,
        max_delay_seconds=0.02,
        sleep_fn=_fake_sleep,
    )


def _request(max_retries: int = 2) -> LLMRequest:
    return LLMRequest(
        messages=[LLMMessage(role="user", content="hi")],
        model="claude-sonnet-5",
        max_retries=max_retries,
    )


def test_succeeds_immediately_with_zero_retries(monkeypatch):
    provider = _provider()
    monkeypatch.setattr(provider._client.messages, "create", lambda **kw: _mock_message())

    response = provider.complete(_request(), RequestContext.new())

    assert response.content == "hello"
    assert response.retries == 0


_TRANSIENT = [
    "APIConnectionError", "RateLimitError", "InternalServerError",
    "OverloadedError", "ServiceUnavailableError",
]
_PERMANENT = [
    "AuthenticationError", "BadRequestError", "PermissionDeniedError",
    "NotFoundError", "UnprocessableEntityError",
]


@pytest.mark.parametrize("exc_name", _TRANSIENT)
def test_retries_transient_errors_then_succeeds(monkeypatch, exc_name):
    exc_cls = getattr(anthropic, exc_name)
    calls = {"n": 0}

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _build_exception(exc_cls, exc_name)
        return _mock_message()

    provider = _provider()
    monkeypatch.setattr(provider._client.messages, "create", flaky)

    response = provider.complete(_request(max_retries=2), RequestContext.new())

    assert response.content == "hello"
    assert response.retries == 1
    assert calls["n"] == 2


@pytest.mark.parametrize("exc_name", _PERMANENT)
def test_non_retryable_errors_raise_immediately_without_retry(monkeypatch, exc_name):
    exc_cls = getattr(anthropic, exc_name)
    calls = {"n": 0}

    def always_fails(**kw):
        calls["n"] += 1
        raise _build_exception(exc_cls, exc_name)

    sleep_calls: list[float] = []
    provider = _provider(sleep_calls)
    monkeypatch.setattr(provider._client.messages, "create", always_fails)

    with pytest.raises(exc_cls):
        provider.complete(_request(max_retries=3), RequestContext.new())

    assert calls["n"] == 1  # no retry attempted at all
    assert sleep_calls == []  # never backed off for a non-retryable error


def test_exhausts_retries_then_raises_the_transient_error(monkeypatch):
    def always_flaky(**kw):
        raise _build_exception(anthropic.RateLimitError, "RateLimitError")

    provider = _provider()
    monkeypatch.setattr(provider._client.messages, "create", always_flaky)

    with pytest.raises(anthropic.RateLimitError):
        provider.complete(_request(max_retries=2), RequestContext.new())


def test_backoff_delays_stay_within_configured_bounds(monkeypatch):
    calls = {"n": 0}

    def flaky_twice(**kw):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise _build_exception(anthropic.OverloadedError, "OverloadedError")
        return _mock_message()

    sleep_calls: list[float] = []
    provider = _provider(sleep_calls)
    monkeypatch.setattr(provider._client.messages, "create", flaky_twice)

    response = provider.complete(_request(max_retries=3), RequestContext.new())

    assert response.retries == 2
    assert len(sleep_calls) == 2
    assert all(0 <= delay <= 0.02 for delay in sleep_calls)


def _build_exception(exc_cls: type, name: str) -> Exception:
    """Builds a real instance of an anthropic SDK exception without a live
    HTTP call, using real httpx2 (anthropic's vendored httpx fork) Request/
    Response objects - APIStatusError/APIConnectionError subclasses read
    real attributes off these at construction time, so a duck-typed stand-in
    is not reliable."""
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    if name == "APIConnectionError":
        return exc_cls(request=request)
    if name == "APITimeoutError":
        return exc_cls(request=request)
    response = httpx2.Response(500, request=request, json={"error": {"type": name}})
    return exc_cls(name, response=response, body=None)
