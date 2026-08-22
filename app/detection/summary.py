"""Optional LLM summary over an already-detected alert (Phase 5 s12). The
LLM is called only after deterministic detection has already produced a
complete AlertCandidate - it receives that candidate's fields as
already-decided facts (the prompt says so explicitly, matching
app/agent/response_composer.py's pattern) and returns prose only. There
is no code path here that writes anything back onto the AlertCandidate;
the function returns a separate string, and the caller decides whether to
attach it - count, threshold, severity, affected_accounts, and evidence
are never touched by this module.
"""

from __future__ import annotations

from app.agent.prompts import load_prompt, prompt_version_string
from app.detection.models import AlertCandidate
from app.llm.base import LLMProvider
from app.llm.types import LLMMessage, LLMRequest, LLMResponse
from app.observability.tracing import RequestContext

_SYSTEM_PROMPT_NAME = "operations_radar_summary_system"


def _render_prompt(alert: AlertCandidate) -> str:
    lines = [
        f"Alert type: {alert.alert_type.value}",
        f"Severity (already decided - do not restate a different one): {alert.severity.value}",
        f"Title: {alert.title}",
        f"Reason (already decided - do not alter the facts in it): {alert.reason}",
        f"Observed count: {alert.observed_count} (threshold: {alert.threshold})",
        f"Time window: {alert.time_window}",
        f"Affected accounts (already decided - do not add or remove any): "
        f"{', '.join(alert.affected_accounts)}",
        f"Representative records: {', '.join(alert.representative_records)}",
        f"Trust state: {alert.trust_state.value}",
        f"Recommended next step (already decided): {alert.recommended_next_step}",
        "",
        "Write a concise operator-facing summary: what was detected, why it matters, and "
        "the recommended next step. Use only the facts above - do not invent a count, "
        "threshold, affected account, or severity, and do not claim causality beyond what "
        "the reason states.",
    ]
    return "\n".join(lines)


def compose_alert_summary(
    alert: AlertCandidate,
    provider: LLMProvider,
    model: str,
    context: RequestContext,
    max_output_tokens: int = 256,
) -> tuple[str, LLMResponse]:
    system_prompt = load_prompt(_SYSTEM_PROMPT_NAME)
    request = LLMRequest(
        messages=[
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=_render_prompt(alert)),
        ],
        model=model,
        max_output_tokens=max_output_tokens,
        prompt_version=prompt_version_string(_SYSTEM_PROMPT_NAME),
    )
    response = provider.complete(request, context)
    return response.content, response
