"""Controlled tool registry (Phase 3 s7). Only names in TOOL_REGISTRY can be
invoked; execute_tool() is the single dispatch point that wraps the three
existing typed tool contracts (app/agent/tools.py) and normalizes every
outcome into a ToolResult (s8) - no repository, domain module, or raw SQL
is ever exposed to a planner/model directly.
"""

from __future__ import annotations

import sqlite3
import time
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


TOOL_REGISTRY: dict[str, ToolSpec] = {
    "search_documents": ToolSpec(
        name="search_documents",
        description="Search policies, agreements, product documentation, and SOPs.",
        input_model=SearchDocumentsRequest,
        output_model=SearchDocumentsResponse,
        requires_auth=True,
        timeout_seconds=5.0,
        retryable=True,
        evidence_bearing=True,
    ),
    "lookup_structured_data": ToolSpec(
        name="lookup_structured_data",
        description="Look up or search accounts, orders, and tickets.",
        input_model=LookupStructuredDataRequest,
        output_model=LookupStructuredDataResponse,
        requires_auth=True,
        timeout_seconds=5.0,
        retryable=True,
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

_ERROR_MAP: dict[type[Exception], tuple[ToolErrorType, bool]] = {
    NotAuthorizedError: (ToolErrorType.NOT_AUTHORIZED, False),
    UnknownEntityError: (ToolErrorType.NOT_FOUND, False),
    InvalidFilterError: (ToolErrorType.INVALID_ARGUMENTS, False),
    ValueError: (ToolErrorType.INVALID_ARGUMENTS, False),
    ValidationError: (ToolErrorType.INVALID_ARGUMENTS, False),
}


def _classify(exc: Exception) -> tuple[ToolErrorType, bool]:
    for exc_type, (error_type, retryable) in _ERROR_MAP.items():
        if isinstance(exc, exc_type):
            return error_type, retryable
    return ToolErrorType.INTERNAL, False


def execute_tool(
    name: str,
    raw_args: dict,
    conn: sqlite3.Connection,
    auth: AuthContext,
    clock: SnapshotClock,
    context: RequestContext,
) -> ToolResult:
    """Validates raw_args against the tool's own input schema, dispatches to
    the real typed tool function, and normalizes any exception into a
    ToolResult - the agent protocol never sees a raw Python exception.
    """
    if name not in TOOL_REGISTRY:
        return ToolResult.fail(
            name, ToolErrorType.INVALID_ARGUMENTS, f"unknown tool {name!r}", 0.0
        )
    spec = TOOL_REGISTRY[name]

    start = time.perf_counter()
    try:
        request = spec.input_model(**raw_args)
    except ValidationError as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return ToolResult.fail(
            name, ToolErrorType.INVALID_ARGUMENTS, f"invalid arguments: {exc}", latency_ms
        )

    try:
        with span(f"agent.tool.{name}", context):
            if name == "search_documents":
                assert isinstance(request, SearchDocumentsRequest)
                output = search_documents_tool(conn, request, auth, context)
            elif name == "lookup_structured_data":
                assert isinstance(request, LookupStructuredDataRequest)
                output = lookup_structured_data_tool(conn, request, auth, clock, context)
            else:
                assert isinstance(request, CalculateSupportOutcomeRequest)
                output = calculate_support_outcome_tool(conn, request, auth, clock, context)
        latency_ms = (time.perf_counter() - start) * 1000
        return ToolResult.ok(name, output, latency_ms)
    except Exception as exc:  # noqa: BLE001 - the tool-protocol normalization boundary
        latency_ms = (time.perf_counter() - start) * 1000
        error_type, retryable = _classify(exc)
        # ParcelPilotError/ValueError/ValidationError messages are intentional,
        # written to be safe to show (AGENTS.md rule 20-style honesty applies
        # to failures too). Anything else is an unanticipated bug - its
        # message might contain internals, so it is never shown verbatim.
        is_safe = isinstance(exc, (ParcelPilotError, ValueError, ValidationError))
        safe_message = str(exc) if is_safe else "an internal error occurred"
        return ToolResult.fail(name, error_type, safe_message, latency_ms, retryable=retryable)
