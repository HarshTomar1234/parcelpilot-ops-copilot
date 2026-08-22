"""The bounded agent state machine (Phase 3 s3, s13). run_agent() is the
single entry point; every state transition is recorded in the returned
trace. No unbounded loop exists - the plan is built once, tool calls are
capped at budget.max_tool_calls, and there is exactly one LLM call in the
default path (response composition; see app/agent/intent.py for why
planning does not need a second one).

Security invariant this module depends on and tests: entity resolution
(app/agent/entities.py) drops any ID the caller is not authorized to see
*before* a plan is ever built from it - a cross-account reference in the
question text never reaches a tool call, it simply is not resolved, and
the request ends in INSUFFICIENT_EVIDENCE rather than leaking whether the
record exists.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.agent.budget_enforcement import (
    check_context_budget,
    check_cost_budget,
    estimate_worst_case_cost_usd,
)
from app.agent.budgets import DEFAULT_BUDGET, AgentBudget
from app.agent.citations import validate_citations
from app.agent.clarification import needs_account_clarification
from app.agent.context import AgentRequestContext
from app.agent.entities import resolve_entities
from app.agent.evidence_pack import build_evidence_pack
from app.agent.intent import Intent, resolve_intent
from app.agent.planner import build_plan
from app.agent.registry import execute_tool
from app.agent.response_composer import compose_response, estimate_prompt_tokens, repair_citations
from app.agent.state import AgentState
from app.agent.tool_result import ToolErrorType, ToolResult
from app.agent.trust_gate import enforce_trust_gate
from app.domain.outcomes import Conflict, EvidenceRef, TrustState
from app.llm.base import LLMProvider
from app.observability.tracing import RequestContext, span
from app.time.clock import FixedSnapshotClock

AgentStatus = Literal[
    "completed", "needs_clarification", "insufficient_evidence", "escalated", "failed",
    "evidence_validation_failed",
]


class AgentRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: AgentStatus
    answer: str | None = None
    trust_state: TrustState | None = None
    citations: list[EvidenceRef] = []
    assumptions: list[str] = []
    conflicts: list[Conflict] = []
    reason: str | None = None
    intent: Intent | None = None
    planned_tools: list[str] = []
    tool_trace: list[dict] = []
    state_trace: list[str] = []
    llm_calls: int = 0
    tool_calls: int = 0
    total_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    request_id: str
    trace_id: str


def _terminal(
    context: AgentRequestContext,
    status: AgentStatus,
    reason: str,
    state_trace: list[str],
    start: float,
    *,
    intent: Intent | None = None,
    trust_state: TrustState | None = None,
    tool_trace: list[dict] | None = None,
    tool_calls: int = 0,
    llm_calls: int = 0,
    total_cost_usd: float = 0.0,
    citations: list[EvidenceRef] | None = None,
    assumptions: list[str] | None = None,
    conflicts: list[Conflict] | None = None,
    planned_tools: list[str] | None = None,
) -> AgentRunResult:
    return AgentRunResult(
        status=status,
        reason=reason,
        intent=intent,
        trust_state=trust_state,
        citations=citations or [],
        assumptions=assumptions or [],
        conflicts=conflicts or [],
        planned_tools=planned_tools or [],
        state_trace=state_trace,
        tool_trace=tool_trace or [],
        tool_calls=tool_calls,
        llm_calls=llm_calls,
        total_latency_ms=(time.perf_counter() - start) * 1000,
        total_cost_usd=total_cost_usd,
        request_id=context.request_id,
        trace_id=context.trace_id,
    )


def run_agent(
    question: str,
    context: AgentRequestContext,
    conn: sqlite3.Connection,
    provider: LLMProvider,
    model: str = "mock-model",
    budget: AgentBudget = DEFAULT_BUDGET,
) -> AgentRunResult:
    start = time.perf_counter()
    tracing_ctx = RequestContext(request_id=context.request_id, trace_id=context.trace_id)
    clock = FixedSnapshotClock(context.dataset_snapshot_time)
    state_trace: list[str] = [AgentState.REQUEST_RECEIVED.value, AgentState.AUTH_VALIDATED.value]

    with span("agent.run", tracing_ctx, question_length=len(question)):
        entities = resolve_entities(question, conn, context.auth, clock)
        state_trace.append(AgentState.ENTITIES_RESOLVED.value)

        if entities.needs_clarification:
            reason = (
                f"question matches multiple accounts: {entities.ambiguous_account_names}; "
                "please specify an account ID or a more specific name"
            )
            state_trace.append(AgentState.NEEDS_CLARIFICATION.value)
            return _terminal(context, "needs_clarification", reason, state_trace, start)

        intent = resolve_intent(question, entities)
        state_trace.append(AgentState.INTENT_RESOLVED.value)

        account_clarification = needs_account_clarification(question, entities, context.auth)
        if account_clarification:
            state_trace.append(AgentState.NEEDS_CLARIFICATION.value)
            return _terminal(
                context, "needs_clarification", account_clarification, state_trace, start,
                intent=intent,
            )

        if intent is Intent.UNSUPPORTED:
            state_trace.append(AgentState.INSUFFICIENT_EVIDENCE.value)
            return _terminal(
                context, "insufficient_evidence", "empty or unsupported request",
                state_trace, start, intent=intent,
            )

        plan = build_plan(question, intent, entities)
        state_trace.append(AgentState.PLAN_CREATED.value)

        if not plan.steps:
            state_trace.append(AgentState.INSUFFICIENT_EVIDENCE.value)
            reason = "no entity or topic in the question resolved to a supported investigation"
            return _terminal(
                context, "insufficient_evidence", reason, state_trace, start, intent=intent,
            )
        if len(plan.steps) > budget.max_tool_calls:
            state_trace.append(AgentState.FAILED.value)
            reason = (
                f"plan requires {len(plan.steps)} tool calls, "
                f"exceeding the budget of {budget.max_tool_calls}"
            )
            return _terminal(context, "failed", reason, state_trace, start, intent=intent)

        tool_results: list[ToolResult] = []
        tool_trace: list[dict] = []
        iterations = 0
        state_trace.append(AgentState.TOOL_EXECUTING.value)
        for step in plan.steps:
            if time.perf_counter() - start > budget.max_wall_clock_seconds:
                state_trace.append(AgentState.FAILED.value)
                return _terminal(
                    context, "failed", "wall-clock budget exceeded", state_trace, start,
                    intent=intent, tool_trace=tool_trace, tool_calls=len(tool_results),
                )
            if iterations >= budget.max_iterations:
                state_trace.append(AgentState.FAILED.value)
                reason = f"iteration budget of {budget.max_iterations} exceeded"
                return _terminal(
                    context, "failed", reason, state_trace, start,
                    intent=intent, tool_trace=tool_trace, tool_calls=len(tool_results),
                )
            result = execute_tool(step.tool, step.args, conn, context.auth, clock, tracing_ctx)
            iterations += result.attempts
            tool_results.append(result)
            tool_trace.append(
                {
                    "tool": step.tool,
                    "purpose": step.purpose,
                    "success": result.success,
                    "error_type": result.error_type.value if result.error_type else None,
                    "latency_ms": round(result.latency_ms, 3),
                }
            )
            if not result.success and result.error_type is ToolErrorType.NOT_AUTHORIZED:
                # Defense in depth: entity resolution should already have
                # dropped anything unauthorized before a plan step referenced
                # it, so this should not be reachable in normal operation.
                # If it is, fail safely rather than proceed with partial data.
                state_trace.append(AgentState.FAILED.value)
                return _terminal(
                    context, "failed", "not authorized", state_trace, start, intent=intent,
                    tool_trace=tool_trace, tool_calls=len(tool_results),
                )

        pack = build_evidence_pack(
            question, intent, entities, tool_results,
            context.dataset_snapshot_time, context.account_scope,
        )
        state_trace.append(AgentState.EVIDENCE_VALIDATED.value)
        state_trace.append(AgentState.DOMAIN_EVALUATED.value)

        if not pack.citations and not pack.document_evidence and not pack.domain_results:
            state_trace.append(AgentState.INSUFFICIENT_EVIDENCE.value)
            reason = "no evidence could be retrieved or calculated for this request"
            return _terminal(
                context, "insufficient_evidence", reason, state_trace, start, intent=intent,
                tool_trace=tool_trace, tool_calls=len(tool_results),
            )

        trust_state = enforce_trust_gate(pack.domain_trust_states, bool(pack.document_evidence))
        state_trace.append(AgentState.TRUST_EVALUATED.value)

        if budget.max_llm_calls < 1:
            state_trace.append(AgentState.FAILED.value)
            return _terminal(
                context, "failed", "llm call budget exhausted before response composition",
                state_trace, start, intent=intent, trust_state=trust_state,
                tool_trace=tool_trace, tool_calls=len(tool_results),
            )

        context_tokens = estimate_prompt_tokens(pack, trust_state)
        context_failure = check_context_budget(context_tokens, budget)
        if context_failure:
            state_trace.append(AgentState.FAILED.value)
            return _terminal(
                context, "failed", context_failure, state_trace, start,
                intent=intent, trust_state=trust_state,
                tool_trace=tool_trace, tool_calls=len(tool_results),
            )

        estimated_cost = estimate_worst_case_cost_usd(
            model, context_tokens, budget.max_output_tokens
        )
        cost_failure = check_cost_budget(estimated_cost, budget)
        if cost_failure:
            state_trace.append(AgentState.FAILED.value)
            return _terminal(
                context, "failed", cost_failure, state_trace, start,
                intent=intent, trust_state=trust_state,
                tool_trace=tool_trace, tool_calls=len(tool_results),
            )

        try:
            answer_text, llm_response = compose_response(
                pack, trust_state, provider, model, tracing_ctx, budget.max_output_tokens
            )
        except Exception as exc:  # noqa: BLE001 - the LLM-call reliability boundary
            # Whatever the provider/gateway raised (AllProvidersFailedError,
            # NonRetryableProviderError, or anything else) becomes a
            # controlled failure here, never a raw exception out of
            # run_agent() - the deterministic investigation up to this
            # point (tool_trace, citations already gathered) is preserved
            # in the terminal result even though composition didn't finish.
            state_trace.append(AgentState.FAILED.value)
            return _terminal(
                context, "failed", f"response composition failed: {exc}", state_trace, start,
                intent=intent, trust_state=trust_state,
                tool_trace=tool_trace, tool_calls=len(tool_results),
            )
        state_trace.append(AgentState.RESPONSE_COMPOSED.value)

        citation_check = validate_citations(answer_text, pack)
        llm_call_count = 1
        total_llm_cost = llm_response.cost.total_cost_usd

        # Phase 4 pre-flight 1D: an invalid citation is never silently
        # stripped and presented as a valid answer. One bounded repair
        # attempt is made (a second LLM call, told exactly which markers
        # were invalid and the real valid list); if the repaired answer
        # still fails validation, the request ends in a controlled
        # evidence_validation_failed result, not a "completed" one with
        # quietly-edited text.
        if not citation_check.valid:
            if budget.max_llm_calls < 2:
                state_trace.append(AgentState.EVIDENCE_VALIDATION_FAILED.value)
                reason = (
                    f"answer cited unsupported source(s) {citation_check.invalid_markers}; "
                    "no repair attempt was available within the LLM call budget"
                )
                return _terminal(
                    context, "evidence_validation_failed", reason, state_trace, start,
                    intent=intent, trust_state=trust_state, tool_trace=tool_trace,
                    tool_calls=len(tool_results), llm_calls=llm_call_count,
                    total_cost_usd=total_llm_cost, citations=pack.citations,
                    assumptions=pack.assumptions, conflicts=pack.conflicts,
                    planned_tools=[s.tool for s in plan.steps],
                )

            try:
                repaired_text, repair_response = repair_citations(
                    pack, trust_state, answer_text, citation_check.invalid_markers,
                    provider, model, tracing_ctx, budget.max_output_tokens,
                )
            except Exception as exc:  # noqa: BLE001 - same reliability boundary as compose_response
                state_trace.append(AgentState.FAILED.value)
                return _terminal(
                    context, "failed", f"citation repair call failed: {exc}", state_trace, start,
                    intent=intent, trust_state=trust_state, tool_trace=tool_trace,
                    tool_calls=len(tool_results), llm_calls=llm_call_count,
                    total_cost_usd=total_llm_cost, citations=pack.citations,
                    assumptions=pack.assumptions, conflicts=pack.conflicts,
                    planned_tools=[s.tool for s in plan.steps],
                )
            llm_call_count += 1
            total_llm_cost += repair_response.cost.total_cost_usd
            repair_check = validate_citations(repaired_text, pack)

            if not repair_check.valid:
                state_trace.append(AgentState.EVIDENCE_VALIDATION_FAILED.value)
                reason = (
                    "answer still cited unsupported source(s) "
                    f"{repair_check.invalid_markers} after one bounded repair attempt"
                )
                return _terminal(
                    context, "evidence_validation_failed", reason, state_trace, start,
                    intent=intent, trust_state=trust_state, tool_trace=tool_trace,
                    tool_calls=len(tool_results), llm_calls=llm_call_count,
                    total_cost_usd=total_llm_cost, citations=pack.citations,
                    assumptions=pack.assumptions, conflicts=pack.conflicts,
                    planned_tools=[s.tool for s in plan.steps],
                )
            answer_text = repaired_text

        # needs_human_review is overloaded at the domain layer: sometimes it
        # means epistemic uncertainty (severity.py's UNCERTAIN ties, already
        # routed through trust_from() into TrustState.ESCALATE) and
        # sometimes it means "this confidently-established fact triggers an
        # operational escalation workflow" (sla.py: a P1 breach is CONFIDENT
        # but still needs_human_review=True per Support Policy v3 s4). Only
        # the epistemic case should change the agent's own response status -
        # an operational flag belongs in the answer's content (surfaced to
        # the model via response_composer.py), not in whether the agent
        # itself trusts its answer enough to give a "completed" one.
        final_status: AgentStatus = (
            "escalated" if trust_state is TrustState.ESCALATE else "completed"
        )
        state_trace.append(
            (AgentState.ESCALATED if final_status == "escalated" else AgentState.COMPLETED).value
        )

        return AgentRunResult(
            status=final_status,
            answer=answer_text,
            trust_state=trust_state,
            citations=pack.citations,
            assumptions=pack.assumptions,
            conflicts=pack.conflicts,
            reason=None,
            intent=intent,
            planned_tools=[s.tool for s in plan.steps],
            tool_trace=tool_trace,
            state_trace=state_trace,
            llm_calls=llm_call_count,
            tool_calls=len(tool_results),
            total_latency_ms=(time.perf_counter() - start) * 1000,
            total_cost_usd=total_llm_cost,
            request_id=context.request_id,
            trace_id=context.trace_id,
        )
