"""Response composition (Phase 3 s16). The LLM call here is a renderer
over the verified EvidencePack - it receives the deterministic domain
result(s), trust state, assumptions, and conflicts as already-decided
facts ("do not recompute or alter these") and is asked only to write a
grounded, cited explanation. trust_state is never parsed back out of the
model's output; the orchestrator attaches it separately from
trust_gate.py, so there is no path for the model to change it.
"""

from __future__ import annotations

from app.agent.citations import citation_key
from app.agent.evidence_pack import EvidencePack
from app.agent.prompts import load_prompt, prompt_version_string
from app.domain.outcomes import TrustState
from app.llm.base import LLMProvider
from app.llm.types import LLMMessage, LLMRequest, LLMResponse
from app.observability.tracing import RequestContext

_SYSTEM_PROMPT_NAME = "support_agent_system"


def _render_user_prompt(pack: EvidencePack, trust_state: TrustState) -> str:
    lines = [f"Question: {pack.question}", ""]

    if pack.citations:
        lines.append("Evidence (cite using these exact [source_id:locator] markers):")
        for ref in pack.citations:
            note = f" {ref.note}" if ref.note else ""
            lines.append(f"- [{citation_key(ref)}]{note}")
        lines.append("")

    if pack.domain_results:
        lines.append("Deterministic result(s) - do not recompute or alter these:")
        for result in pack.domain_results:
            lines.append(f"- {result}")
        lines.append("")

    if pack.assumptions:
        lines.append("Assumptions this result depends on:")
        for assumption in pack.assumptions:
            lines.append(f"- {assumption}")
        lines.append("")

    if pack.conflicts:
        lines.append("Source conflicts already resolved:")
        for conflict in pack.conflicts:
            lines.append(
                f"- {conflict.winner_source_id} overrides {conflict.loser_source_id}: "
                f"{conflict.reason}"
            )
        lines.append("")

    lines.append(f"Trust state (backend-determined, do not restate a higher confidence): "
                  f"{trust_state.value}")
    if pack.needs_human_review:
        lines.append(
            "This result should be flagged for human/operational follow-up "
            "(e.g. an SLA breach requiring escalation) - say so plainly in the answer."
        )
    lines.append(
        "Write a concise, grounded answer using only the evidence and results above. "
        "Cite sources with the bracketed markers shown. State the trust level plainly if "
        "it is not CONFIDENT. If evidence is missing, say so rather than guessing."
    )
    return "\n".join(lines)


def compose_response(
    pack: EvidencePack,
    trust_state: TrustState,
    provider: LLMProvider,
    model: str,
    context: RequestContext,
    max_output_tokens: int,
) -> tuple[str, LLMResponse]:
    system_prompt = load_prompt(_SYSTEM_PROMPT_NAME)
    user_prompt = _render_user_prompt(pack, trust_state)
    request = LLMRequest(
        messages=[
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ],
        model=model,
        max_output_tokens=max_output_tokens,
        prompt_version=prompt_version_string(_SYSTEM_PROMPT_NAME),
    )
    response = provider.complete(request, context)
    return response.content, response
