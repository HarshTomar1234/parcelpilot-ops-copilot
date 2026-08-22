"""Typed, agent-facing tool contracts.

These are the only functions a future agent calls - never the repository,
retrieval, or domain modules directly, and never raw SQL (AGENTS.md rule 11
/ Phase 1I). Every contract validates its input and output through Pydantic
and is traced through app.observability.tracing, so a tool call is
traceable end to end before any agent orchestrates one.

No LLM or agent orchestration exists yet - this module only defines and
implements the boundary a future orchestrator will call.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.authorization.context import AuthContext
from app.detection.models import AlertCandidate, AlertType
from app.detection.rules import DEFAULT_WINDOW_DAYS
from app.detection.service import group_by_account, run_operations_radar
from app.documents.retrieval import DocumentSearchFilter, DocumentSearchResult, search_documents
from app.domain.cancellation import evaluate_cancellation
from app.domain.outcomes import Conflict, DecisionResult, EvidenceRef, TrustState
from app.domain.service_credit import evaluate_service_credit
from app.domain.severity import classify_severity
from app.domain.sla import calculate_sla
from app.models.enums import AuthorityClass, OrderStatus, SourceStatus, SourceType, TicketStatus
from app.models.structured import Account, Order, Ticket
from app.observability.tracing import RequestContext, span
from app.structured_data.repository import (
    get_account,
    get_order,
    get_ticket,
    search_orders,
    search_tickets,
)
from app.time.clock import SnapshotClock, tz_of

logger = logging.getLogger("agent.tools")


# ---------------------------------------------------------------------------
# search_documents
# ---------------------------------------------------------------------------


# Minimum BM25 relevance a chunk must clear to count as usable agent
# evidence (Phase 4 s2; SQLite FTS5's bm25() is negative, lower/more-
# negative = stronger match). Calibrated against the real pack, not
# invented: genuinely relevant queries' top matches score roughly -1.9 to
# -14.5 here, while a clearly off-topic question ("What is the weather
# today?") tops out around -0.34 - comfortably above this cutoff. This is
# a lexical-relevance filter only; it does not (and cannot) detect a
# question whose retrieved chunks score strongly but don't actually
# contain the specific fact asked for - that is a separate, harder,
# still-open gap, documented in docs/evaluation_report.md.
MIN_RELEVANCE_SCORE = -1.0


class SearchDocumentsRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str
    source_types: list[SourceType] | None = None
    authority_classes: list[AuthorityClass] | None = None
    statuses: list[SourceStatus] | None = None
    top_k: int = Field(default=5, ge=1, le=50)


class SearchDocumentsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: str
    results: list[DocumentSearchResult]
    latency_ms: float


def search_documents_tool(
    conn: sqlite3.Connection,
    request: SearchDocumentsRequest,
    auth: AuthContext,
    context: RequestContext,
) -> SearchDocumentsResponse:
    filters = DocumentSearchFilter(
        source_types=request.source_types,
        authority_classes=request.authority_classes,
        statuses=request.statuses,
        account_scope=auth.account_scope,
    )
    start = time.perf_counter()
    with span("tool.search_documents", context, query=request.query, top_k=request.top_k):
        raw_results = search_documents(conn, request.query, filters, request.top_k)
    results = [r for r in raw_results if r.score <= MIN_RELEVANCE_SCORE]
    latency_ms = (time.perf_counter() - start) * 1000

    logger.info(
        "tool.search_documents",
        extra={
            "request_id": context.request_id, "trace_id": context.trace_id,
            "result_count": len(results), "filtered_count": len(raw_results) - len(results),
            "latency_ms": round(latency_ms, 3),
        },
    )
    return SearchDocumentsResponse(query=request.query, results=results, latency_ms=latency_ms)


# ---------------------------------------------------------------------------
# lookup_structured_data
# ---------------------------------------------------------------------------


class LookupKind(StrEnum):
    GET_ACCOUNT = "get_account"
    GET_ORDER = "get_order"
    GET_TICKET = "get_ticket"
    SEARCH_ORDERS = "search_orders"
    SEARCH_TICKETS = "search_tickets"


class LookupStructuredDataRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: LookupKind
    entity_id: str | None = None  # required for get_*
    account_id: str | None = None  # filter for search_*
    status: str | None = None  # filter for search_*
    carrier: str | None = None  # filter for search_orders only


class LookupStructuredDataResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: LookupKind
    records: list[Account | Order | Ticket]
    latency_ms: float


def lookup_structured_data_tool(
    conn: sqlite3.Connection,
    request: LookupStructuredDataRequest,
    auth: AuthContext,
    clock: SnapshotClock,
    context: RequestContext,
) -> LookupStructuredDataResponse:
    tz = tz_of(clock)
    start = time.perf_counter()
    with span("tool.lookup_structured_data", context, kind=request.kind.value):
        records: list[Account | Order | Ticket]
        match request.kind:
            case LookupKind.GET_ACCOUNT:
                if request.entity_id is None:
                    raise ValueError("entity_id is required for get_account")
                records = [get_account(conn, request.entity_id, auth)]
            case LookupKind.GET_ORDER:
                if request.entity_id is None:
                    raise ValueError("entity_id is required for get_order")
                records = [get_order(conn, request.entity_id, auth, tz)]
            case LookupKind.GET_TICKET:
                if request.entity_id is None:
                    raise ValueError("entity_id is required for get_ticket")
                records = [get_ticket(conn, request.entity_id, auth, tz)]
            case LookupKind.SEARCH_ORDERS:
                order_status = OrderStatus(request.status) if request.status else None
                records = list(
                    search_orders(
                        conn, auth, tz, account_id=request.account_id,
                        status=order_status, carrier=request.carrier,
                    )
                )
            case LookupKind.SEARCH_TICKETS:
                ticket_status = TicketStatus(request.status) if request.status else None
                records = list(
                    search_tickets(
                        conn, auth, tz, account_id=request.account_id, status=ticket_status
                    )
                )
    latency_ms = (time.perf_counter() - start) * 1000

    logger.info(
        "tool.lookup_structured_data",
        extra={
            "request_id": context.request_id, "trace_id": context.trace_id,
            "kind": request.kind.value, "record_count": len(records),
            "latency_ms": round(latency_ms, 3),
        },
    )
    return LookupStructuredDataResponse(kind=request.kind, records=records, latency_ms=latency_ms)


# ---------------------------------------------------------------------------
# calculate_support_outcome
# ---------------------------------------------------------------------------


class CalculationType(StrEnum):
    CANCELLATION = "cancellation"
    SERVICE_CREDIT = "service_credit"
    SLA = "sla"
    SEVERITY = "severity"


class CalculateSupportOutcomeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    calculation_type: CalculationType
    entity_id: str  # order_id for cancellation/service_credit, ticket_id for sla/severity


class CalculateSupportOutcomeResponse(BaseModel):
    """Flattens a DecisionResult[T] into a tool-boundary payload - the
    caller doesn't need to know DecisionResult is a Python generic, just
    that `result` is the calculation-specific payload."""

    model_config = ConfigDict(frozen=True)

    calculation_type: CalculationType
    trust_state: TrustState
    reason: str
    result: dict[str, object] | None
    evidence: list[EvidenceRef]
    assumptions: list[str]
    conflicts: list[Conflict]
    needs_human_review: bool
    calculation_inputs: dict[str, object]
    latency_ms: float

    @classmethod
    def from_decision(
        cls, calculation_type: CalculationType, decision: DecisionResult, latency_ms: float
    ) -> CalculateSupportOutcomeResponse:
        return cls(
            calculation_type=calculation_type,
            trust_state=decision.trust_state,
            reason=decision.reason,
            result=decision.result.model_dump(mode="json") if decision.result else None,
            evidence=decision.evidence,
            assumptions=decision.assumptions,
            conflicts=decision.conflicts,
            needs_human_review=decision.needs_human_review,
            calculation_inputs=decision.calculation_inputs,
            latency_ms=latency_ms,
        )


def calculate_support_outcome_tool(
    conn: sqlite3.Connection,
    request: CalculateSupportOutcomeRequest,
    auth: AuthContext,
    clock: SnapshotClock,
    context: RequestContext,
) -> CalculateSupportOutcomeResponse:
    start = time.perf_counter()
    with span(
        "tool.calculate_support_outcome", context,
        calculation_type=request.calculation_type.value, entity_id=request.entity_id,
    ):
        decision: DecisionResult
        match request.calculation_type:
            case CalculationType.CANCELLATION:
                decision = evaluate_cancellation(conn, request.entity_id, auth, clock)
            case CalculationType.SERVICE_CREDIT:
                decision = evaluate_service_credit(conn, request.entity_id, auth, clock)
            case CalculationType.SLA:
                decision = calculate_sla(conn, request.entity_id, auth, clock)
            case CalculationType.SEVERITY:
                ticket = get_ticket(conn, request.entity_id, auth, tz_of(clock))
                decision = classify_severity(ticket, conn)
    latency_ms = (time.perf_counter() - start) * 1000

    logger.info(
        "tool.calculate_support_outcome",
        extra={
            "request_id": context.request_id, "trace_id": context.trace_id,
            "calculation_type": request.calculation_type.value,
            "trust_state": decision.trust_state.value, "latency_ms": round(latency_ms, 3),
        },
    )
    return CalculateSupportOutcomeResponse.from_decision(
        request.calculation_type, decision, latency_ms
    )


# ---------------------------------------------------------------------------
# detect_issues (Phase 5 s10)
# ---------------------------------------------------------------------------


class DetectIssuesRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    alert_types: list[AlertType] | None = None  # None = every rule
    window_days: int = Field(default=DEFAULT_WINDOW_DAYS, ge=1, le=365)
    # A further narrowing filter, never a widening one - always intersected
    # with the caller's real auth.account_scope inside run_operations_radar()
    # (via search_orders/search_tickets), so this field cannot be used to
    # see an account the caller isn't already authorized to see.
    account_scope: list[str] | None = None
    group_by_account: bool = False


class DetectIssuesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    alerts: list[AlertCandidate]
    grouped_by_account: dict[str, list[str]] | None = None
    latency_ms: float


def detect_issues_tool(
    conn: sqlite3.Connection,
    request: DetectIssuesRequest,
    auth: AuthContext,
    clock: SnapshotClock,
    context: RequestContext,
) -> DetectIssuesResponse:
    scoped_auth = auth
    if request.account_scope is not None:
        # Intersect, never union - a caller cannot widen their own scope by
        # naming an account here that their real auth doesn't already cover.
        allowed = {a for a in request.account_scope if auth.allows_account(a)}
        scoped_auth = AuthContext(role=auth.role, account_scope=sorted(allowed))

    start = time.perf_counter()
    with span(
        "tool.detect_issues", context,
        alert_types=[t.value for t in request.alert_types] if request.alert_types else "all",
        window_days=request.window_days,
    ):
        alerts = run_operations_radar(
            conn, scoped_auth, clock,
            alert_types=request.alert_types, window_days=request.window_days,
        )
    latency_ms = (time.perf_counter() - start) * 1000

    grouped = group_by_account(alerts) if request.group_by_account else None

    logger.info(
        "tool.detect_issues",
        extra={
            "request_id": context.request_id, "trace_id": context.trace_id,
            "alert_count": len(alerts), "latency_ms": round(latency_ms, 3),
        },
    )
    return DetectIssuesResponse(
        alerts=alerts, grouped_by_account=grouped, latency_ms=latency_ms
    )
