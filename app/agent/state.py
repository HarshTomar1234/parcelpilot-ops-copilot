"""Bounded agent state machine (Phase 3 s3). A linear enum + a trace list of
(state, detail) pairs recorded by the orchestrator - not a general-purpose
FSM framework, which nothing here needs (AGENTS.md rule 19: prefer simple,
inspectable architecture).
"""

from __future__ import annotations

from enum import StrEnum


class AgentState(StrEnum):
    REQUEST_RECEIVED = "REQUEST_RECEIVED"
    AUTH_VALIDATED = "AUTH_VALIDATED"
    INTENT_RESOLVED = "INTENT_RESOLVED"
    ENTITIES_RESOLVED = "ENTITIES_RESOLVED"
    PLAN_CREATED = "PLAN_CREATED"
    TOOL_EXECUTING = "TOOL_EXECUTING"
    EVIDENCE_VALIDATED = "EVIDENCE_VALIDATED"
    DOMAIN_EVALUATED = "DOMAIN_EVALUATED"
    TRUST_EVALUATED = "TRUST_EVALUATED"
    RESPONSE_COMPOSED = "RESPONSE_COMPOSED"
    COMPLETED = "COMPLETED"

    # Terminal-only states, reachable from any earlier state.
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


TERMINAL_STATES = frozenset(
    {
        AgentState.COMPLETED,
        AgentState.NEEDS_CLARIFICATION,
        AgentState.INSUFFICIENT_EVIDENCE,
        AgentState.ESCALATED,
        AgentState.FAILED,
    }
)
