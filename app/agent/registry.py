"""Controlled tool registry (Phase 3 s7, Phase 4 pre-flight 1B). Only names
in TOOL_REGISTRY can be invoked; execute_tool() is the single dispatch
point that wraps the three existing typed tool contracts (app/agent/
tools.py) and normalizes every outcome into a ToolResult (s8) - no
repository, domain module, or raw SQL is ever exposed to a planner/model
directly.

Timeout: enforced by measuring actual elapsed wall-clock time against
spec.timeout_seconds. All three tools today are local, synchronous SQLite
operations against a connection created with the sqlite3 default
check_same_thread=True (app/db/connection.py, unchanged this phase) -
that thread-affinity rules out a safe preemptive/threaded interrupt
without a broader connection-handling redesign, which is out of scope for
this phase. So a call that runs longer than its budget is caught and
reported as TIMEOUT after the fact, not interrupted mid-flight - honest
for tools that are all sub-millisecond today; revisit with a per-call
connection + worker thread if a genuinely long-running or network-bound
tool is ever added.

Retry: bounded, only for a tool whose ToolSpec.retryable=True AND whose
failure classifies as transient (currently just TIMEOUT). All three
current tools are deterministic local reads with no transient failure
mode - retrying a deterministic failure just fails again, identically -
so all three are retryable=False by design. The retry loop itself is
implemented and unit-tested (via an injectable sleep function, same
pattern as app/llm/anthropic_provider.py's backoff), so it is real, not
vestigial, ready for a future I/O-bound tool.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from app.agent.tool_result import ToolErrorType, ToolResult
from app.agent.tools import (
    CalculateSupportOutcomeRequest,
    CalculateSupportOutcomeResponse,
    LookupStructuredDataRequest,
    LookupStructuredDataResponse,
    SearchDocumentsRequest,
    SearchDocumentsResponse,
    calculate_support_outcome_tool,
    lookup_structured_data_tool,
    search_documents_tool,
)
from app.authorization.context import AuthContext
from app.errors import InvalidFilterError, NotAuthorizedError, ParcelPilotError, UnknownEntityError
from app.observability.tracing import RequestContext, span
from app.time.clock import SnapshotClock


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    requires_auth: bool
    timeout_seconds: float
    retryable: bool
    evidence_bearing: bool  # does a successful call add citable evidence?
    max_retries: int = 2


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "search_documents": ToolSpec(
        name="search_documents",
        description="Search policies, agreements, product documentation, and SOPs.",
        input_model=SearchDocumentsRequest,
        output_model=SearchDocumentsResponse,
        requires_auth=True,
        timeout_seconds=5.0,
        retryable=False,  # local, deterministic FTS5 read - no transient failure mode
        evidence_bearing=True,
    ),
    "lookup_structured_data": ToolSpec(
        name="lookup_structured_data",
        description="Look up or search accounts, orders, and tickets.",
        input_model=LookupStructuredDataRequest,
        output_model=LookupStructuredDataResponse,
        requires_auth=True,
        timeout_seconds=5.0,
        retryable=False,  # local, deterministic read - no transient failure mode
        evidence_bearing=True,
    ),
    "calculate_support_outcome": ToolSpec(
        name="calculate_support_outcome",
        description="Deterministic cancellation/service_credit/sla/severity calculation.",
        input_model=CalculateSupportOutcomeRequest,
        output_model=CalculateSupportOutcomeResponse,
        requires_auth=True,
        timeout_seconds=10.0,
        retryable=False,  # deterministic - retrying a failure won't change the answer
        evidence_bearing=True,
    ),
}

_ERROR_MAP: dict[type[Exception], ToolErrorType] = {
    NotAuthorizedError: ToolErrorType.NOT_AUTHORIZED,
    UnknownEntityError: ToolErrorType.NOT_FOUND,
    InvalidFilterError: ToolErrorType.INVALID_ARGUMENTS,
    ValueError: ToolErrorType.INVALID_ARGUMENTS,
    ValidationError: ToolErrorType.INVALID_ARGUMENTS,
}
# The only error type this phase treats as retry-eligible for a local
# tool. NOT_FOUND/NOT_AUTHORIZED/INVALID_ARGUMENTS/INTERNAL are all
# deterministic given the same input - retrying buys nothing.
_TRANSIENT_ERROR_TYPES = frozenset({ToolErrorType.TIMEOUT})


def _classify(exc: Exception) -> ToolErrorType:
    for exc_type, error_type in _ERROR_MAP.items():
        if isinstance(exc, exc_type):
            return error_type
    return ToolErrorType.INTERNAL


def _dispatch(
    name: str,
    request: BaseModel,
    conn: sqlite3.Connection,
    auth: AuthContext,
    clock: SnapshotClock,
    context: RequestContext,
) -> BaseModel:
    with span(f"agent.tool.{name}", context):
        if name == "search_documents":
            assert isinstance(request, SearchDocumentsRequest)
            return search_documents_tool(conn, request, auth, context)
        if name == "lookup_structured_data":
            assert isinstance(request, LookupStructuredDataRequest)
            return lookup_structured_data_tool(conn, request, auth, clock, context)
        assert isinstance(request, CalculateSupportOutcomeRequest)
        return calculate_support_outcome_tool(conn, request, auth, clock, context)


def execute_tool(
    name: str,
    raw_args: dict,
    conn: sqlite3.Connection,
    auth: AuthContext,
    clock: SnapshotClock,
    context: RequestContext,
    *,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> ToolResult:
    """Validates raw_args against the tool's own input schema, dispatches to
    the real typed tool function, and normalizes any exception (or a
    timeout) into a ToolResult - the agent protocol never sees a raw
    Python exception. Retries up to spec.max_retries times only when
    spec.retryable is True and the failure classifies as transient.
    """
    if name not in TOOL_REGISTRY:
        return ToolResult.fail(
            name, ToolErrorType.INVALID_ARGUMENTS, f"unknown tool {name!r}", 0.0
        )
    spec = TOOL_REGISTRY[name]

    try:
        request = spec.input_model(**raw_args)
    except ValidationError as exc:
        return ToolResult.fail(
            name, ToolErrorType.INVALID_ARGUMENTS, f"invalid arguments: {exc}", 0.0
        )

    max_attempts = (spec.max_retries + 1) if spec.retryable else 1
    result: ToolResult | None = None
    for attempt in range(1, max_attempts + 1):
        start = time.perf_counter()
        try:
            output = _dispatch(name, request, conn, auth, clock, context)
        except Exception as exc:  # noqa: BLE001 - the tool-protocol normalization boundary
            latency_ms = (time.perf_counter() - start) * 1000
            error_type = _classify(exc)
            # ParcelPilotError/ValueError/ValidationError messages are intentional,
            # written to be safe to show (AGENTS.md rule 20-style honesty applies
            # to failures too). Anything else is an unanticipated bug - its
            # message might contain internals, so it is never shown verbatim.
            is_safe = isinstance(exc, (ParcelPilotError, ValueError, ValidationError))
            safe_message = str(exc) if is_safe else "an internal error occurred"
            result = ToolResult.fail(
                name, error_type, safe_message, latency_ms,
                retryable=error_type in _TRANSIENT_ERROR_TYPES, attempts=attempt,
            )
        else:
            latency_ms = (time.perf_counter() - start) * 1000
            if latency_ms > spec.timeout_seconds * 1000:
                result = ToolResult.fail(
                    name, ToolErrorType.TIMEOUT,
                    f"{name} exceeded its {spec.timeout_seconds}s timeout budget",
                    latency_ms, retryable=True, attempts=attempt,
                )
            else:
                return ToolResult.ok(name, output, latency_ms, attempts=attempt)

        if result.error_type not in _TRANSIENT_ERROR_TYPES or attempt >= max_attempts:
            return result
        sleep_fn(0.05 * attempt)  # small bounded backoff between retries

    assert result is not None
    return result
