"""Response composition (Phase 3 s16). The LLM call here is a renderer
over the verified EvidencePack - it receives the deterministic domain
result(s), trust state, assumptions, and conflicts as already-decided
facts ("do not recompute or alter these") and is asked only to write a
grounded, cited explanation. trust_state is never parsed back out of the
model's output; the orchestrator attaches it separately from
trust_gate.py, so there is no path for the model to change it.
"""

from __future__ import annotations

from app.agent.budget_enforcement import approx_tokens
from app.agent.citations import citation_key
from app.agent.evidence_pack import EvidencePack
from app.agent.prompts import load_prompt, prompt_version_string
from app.domain.outcomes import TrustState
from app.llm.base import LLMProvider
from app.llm.types import LLMMessage, LLMRequest, LLMResponse
from app.observability.tracing import RequestContext

_SYSTEM_PROMPT_NAME = "support_agent_system"


def _render_evidence_blocks(pack: EvidencePack) -> list[str]:
    """Evidence, deterministic result(s), assumptions, and conflicts - the
    facts a grounded answer is actually built from. Shared by the initial
    compose and the repair prompt: a repair call that only sees the valid
    marker *labels* (no underlying values) cannot rewrite a grounded
    answer - it can only ask for the facts back, which is exactly the
    failure a live run demonstrated before this was shared."""
    lines: list[str] = []

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

    return lines


def _render_user_prompt(pack: EvidencePack, trust_state: TrustState) -> str:
    lines = [f"Question: {pack.question}", ""]
    lines += _render_evidence_blocks(pack)

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


def _render_repair_prompt(
    pack: EvidencePack, trust_state: TrustState, previous_answer: str, invalid_markers: list[str]
) -> str:
    lines = [
        f"Question: {pack.question}",
        "",
        "Your previous answer cited source markers that do not exist in the evidence "
        "provided. Rewrite the answer using ONLY the exact markers listed below - do not "
        "invent a marker or reuse an invalid one.",
        "",
        "Invalid markers you used: " + ", ".join(f"[{m}]" for m in invalid_markers),
        "",
    ]
    lines += _render_evidence_blocks(pack)
    lines += [
        f"Previous answer:\n{previous_answer}",
        "",
        "Write a corrected, concise, grounded answer using only the valid markers and "
        "deterministic result(s) above. "
        f"State the trust level plainly if it is not CONFIDENT ({trust_state.value}).",
    ]
    return "\n".join(lines)


def estimate_prompt_tokens(pack: EvidencePack, trust_state: TrustState) -> int:
    """Called before compose_response() so the orchestrator can gate on
    max_context_tokens/max_estimated_cost_usd before actually spending
    either."""
    system_prompt = load_prompt(_SYSTEM_PROMPT_NAME)
    user_prompt = _render_user_prompt(pack, trust_state)
    return approx_tokens(system_prompt) + approx_tokens(user_prompt)


def _call_llm(
    user_prompt: str,
    provider: LLMProvider,
    model: str,
    context: RequestContext,
    max_output_tokens: int,
) -> tuple[str, LLMResponse]:
    system_prompt = load_prompt(_SYSTEM_PROMPT_NAME)
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


def compose_response(
    pack: EvidencePack,
    trust_state: TrustState,
    provider: LLMProvider,
    model: str,
    context: RequestContext,
    max_output_tokens: int,
) -> tuple[str, LLMResponse]:
    user_prompt = _render_user_prompt(pack, trust_state)
    return _call_llm(user_prompt, provider, model, context, max_output_tokens)


def repair_citations(
    pack: EvidencePack,
    trust_state: TrustState,
    previous_answer: str,
    invalid_markers: list[str],
    provider: LLMProvider,
    model: str,
    context: RequestContext,
    max_output_tokens: int,
) -> tuple[str, LLMResponse]:
    """One bounded repair attempt (Phase 4 pre-flight 1D): the orchestrator
    calls this at most once, after the first composed answer fails
    citation validation. If the repaired answer still fails validation,
    the orchestrator returns a controlled evidence_validation_failed
    result - it never silently strips the bad marker and presents the
    answer as valid."""
    repair_prompt = _render_repair_prompt(pack, trust_state, previous_answer, invalid_markers)
    return _call_llm(repair_prompt, provider, model, context, max_output_tokens)
