"""Timeout and retry enforcement in app/agent/registry.py::execute_tool
(Phase 4 pre-flight 1B). Uses a fake, explicitly-advanced clock in place of
time.perf_counter to simulate a slow call deterministically - the nested
span()/tool-latency calls also read the clock, so a flat sequence of
scripted return values would be fragile; instead the clock only moves
when _dispatch is told to advance it, so every other perf_counter() read
in between sees a stable value.
"""

from __future__ import annotations

import dataclasses
import time

import pytest

from app.agent import registry
from app.agent.tool_result import ToolErrorType
from app.observability.tracing import RequestContext


class _FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _install_slow_dispatch(monkeypatch: pytest.MonkeyPatch, seconds: float) -> _FakeClock:
    """Patches time.perf_counter with a fake clock and _dispatch so that
    every call to the real tool appears to take `seconds` wall-clock time,
    without an actual sleep and without depending on the exact number of
    perf_counter() calls made by span()/the tool function itself."""
    fake_clock = _FakeClock()
    monkeypatch.setattr(time, "perf_counter", fake_clock)
    real_dispatch = registry._dispatch

    def slow_dispatch(*args, **kwargs):  # type: ignore[no-untyped-def]
        output = real_dispatch(*args, **kwargs)
        fake_clock.advance(seconds)
        return output

    monkeypatch.setattr(registry, "_dispatch", slow_dispatch)
    return fake_clock


def test_fast_call_succeeds_with_a_single_attempt(conn, auth, clock):
    result = registry.execute_tool(
        "search_documents", {"query": "cancellation"},
        conn, auth, clock, RequestContext.new(),
    )
    assert result.success
    assert result.attempts == 1


def test_call_exceeding_its_timeout_budget_is_reported_as_timeout(conn, auth, clock, monkeypatch):
    _install_slow_dispatch(monkeypatch, seconds=10.0)  # search_documents budget is 5s

    result = registry.execute_tool(
        "search_documents", {"query": "cancellation"},
        conn, auth, clock, RequestContext.new(),
    )
    assert not result.success
    assert result.error_type is ToolErrorType.TIMEOUT
    assert result.retryable is True
    assert result.attempts == 1  # search_documents is retryable=False - no retry attempted


def test_non_retryable_tool_does_not_retry_on_timeout(conn, auth, clock, monkeypatch):
    _install_slow_dispatch(monkeypatch, seconds=10.0)
    sleep_calls: list[float] = []

    result = registry.execute_tool(
        "search_documents", {"query": "cancellation"},
        conn, auth, clock, RequestContext.new(), sleep_fn=sleep_calls.append,
    )
    assert result.attempts == 1
    assert sleep_calls == []


def test_retryable_tool_retries_after_a_timeout_then_succeeds(conn, auth, clock, monkeypatch):
    # Temporarily mark search_documents retryable to exercise the retry
    # loop itself with a real tool function - none of the three production
    # tools opt into this today (all deterministic local reads), but the
    # mechanism must actually work for when one does.
    original = registry.TOOL_REGISTRY["search_documents"]
    monkeypatch.setitem(
        registry.TOOL_REGISTRY, "search_documents",
        dataclasses.replace(original, retryable=True, max_retries=2),
    )
    fake_clock = _install_slow_dispatch(monkeypatch, seconds=10.0)
    real_dispatch = registry._dispatch  # the slow_dispatch installed above
    call_count = 0

    def flaky_then_fast_dispatch(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return real_dispatch(*args, **kwargs)  # attempt 1: slow -> timeout
        fake_clock.advance(-9.999)  # attempt 2: back under budget -> fast
        return real_dispatch(*args, **kwargs)

    monkeypatch.setattr(registry, "_dispatch", flaky_then_fast_dispatch)
    sleep_calls: list[float] = []

    result = registry.execute_tool(
        "search_documents", {"query": "cancellation"},
        conn, auth, clock, RequestContext.new(), sleep_fn=sleep_calls.append,
    )
    assert result.success
    assert result.attempts == 2
    assert sleep_calls == [0.05]


def test_retryable_tool_exhausts_retries_then_returns_the_last_timeout(
    conn, auth, clock, monkeypatch
):
    original = registry.TOOL_REGISTRY["search_documents"]
    monkeypatch.setitem(
        registry.TOOL_REGISTRY, "search_documents",
        dataclasses.replace(original, retryable=True, max_retries=1),
    )
    _install_slow_dispatch(monkeypatch, seconds=10.0)  # always over budget

    result = registry.execute_tool(
        "search_documents", {"query": "cancellation"},
        conn, auth, clock, RequestContext.new(), sleep_fn=lambda s: None,
    )
    assert not result.success
    assert result.error_type is ToolErrorType.TIMEOUT
    assert result.attempts == 2  # 1 initial + 1 retry, then gave up


def test_invalid_arguments_are_never_retried(conn, auth, clock, monkeypatch):
    original = registry.TOOL_REGISTRY["lookup_structured_data"]
    monkeypatch.setitem(
        registry.TOOL_REGISTRY, "lookup_structured_data",
        dataclasses.replace(original, retryable=True, max_retries=2),
    )
    calls: list[float] = []
    result = registry.execute_tool(
        "lookup_structured_data", {"kind": "get_order"},  # missing entity_id
        conn, auth, clock, RequestContext.new(), sleep_fn=calls.append,
    )
    assert not result.success
    assert result.error_type is ToolErrorType.INVALID_ARGUMENTS
    assert result.attempts == 1
    assert calls == []
