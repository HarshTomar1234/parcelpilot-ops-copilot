"""POST /api/chat (Phase 6 s9). A thin wrapper over run_agent() - no
business rule lives here. The full AgentRunResult is returned as-is
(status, trust_state, citations, assumptions, conflicts, tool/state
trace, latency, cost) - never re-shaped or summarized, so the UI shows
exactly what the deterministic pipeline actually did.
"""

from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter, Depends

from app.agent.context import AgentRequestContext
from app.agent.orchestrator import run_agent
from app.api.demo_users import DemoUser
from app.api.deps import get_clock, get_conn, get_current_user, get_provider, get_request_context
from app.api.schemas import ChatRequest, ChatResponse
from app.llm.base import LLMProvider
from app.observability.tracing import RequestContext
from app.time.clock import SnapshotClock

router = APIRouter(tags=["chat"])
logger = logging.getLogger("api.chat")


@router.post("/api/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    user: DemoUser = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_conn),
    clock: SnapshotClock = Depends(get_clock),
    provider_and_model: tuple[LLMProvider, str] = Depends(get_provider),
    request_context: RequestContext = Depends(get_request_context),
) -> ChatResponse:
    provider, model = provider_and_model
    ctx = AgentRequestContext(
        request_id=request_context.request_id,
        trace_id=request_context.trace_id,
        user_id=user.id,
        auth=user.to_auth_context(),
        dataset_snapshot_time=clock.now(),
    )
    result = run_agent(body.question, ctx, conn, provider, model=model)

    logger.info(
        "chat_completed",
        extra={
            "request_id": ctx.request_id, "trace_id": ctx.trace_id,
            "demo_user": user.id, "role": user.role.value, "status": result.status,
            "trust_state": result.trust_state.value if result.trust_state else None,
            "tool_calls": result.tool_calls, "llm_calls": result.llm_calls,
            "total_latency_ms": round(result.total_latency_ms, 3),
            "total_cost_usd": result.total_cost_usd, "provider": provider.name, "model": model,
        },
    )
    return ChatResponse(result=result, viewed_as=user, dataset_snapshot=clock.now())
