"""The hard trust gate (Phase 3 s15). This is the ONLY function that
produces the final trust_state for an agent response, and it is called
by the orchestrator AFTER response generation, overwriting anything the
LLM might have said - there is no code path where response-generation
output can set or change trust_state. This makes "UNCERTAIN/CONDITIONAL
-> CONFIDENT" not just disallowed by policy but structurally impossible:
the field the rule protects is never LLM-controlled in the first place.

Aggregation rule when multiple domain calculations ran (e.g. a
MULTI_SOURCE plan): the overall trust state is the worst (least certain)
of them - one CONDITIONAL result should never be hidden behind three
CONFIDENT ones.
"""

from __future__ import annotations

from app.domain.outcomes import TrustState

_SEVERITY_ORDER = {
    TrustState.CONFIDENT: 0,
    TrustState.CONDITIONAL: 1,
    TrustState.UNCERTAIN: 2,
    TrustState.ESCALATE: 3,
}


def enforce_trust_gate(
    domain_trust_states: list[TrustState],
    has_document_evidence: bool,
) -> TrustState:
    if domain_trust_states:
        return max(domain_trust_states, key=lambda t: _SEVERITY_ORDER[t])
    # No deterministic calculation ran - a pure retrieval/informational
    # answer is never CONFIDENT on its own: it is grounded evidence, not a
    # verified fact. No evidence at all means we cannot even ground it.
    return TrustState.CONDITIONAL if has_document_evidence else TrustState.UNCERTAIN
