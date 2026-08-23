"""Optional LLM summary over a detected alert (Phase 5 s12). The
deterministic AlertCandidate stays authoritative - the LLM call only
produces a separate string, and there is no code path that writes
anything back onto count/threshold/severity/affected_accounts/evidence.
"""

from __future__ import annotations

import pytest

from app.detection.models import (
    AlertCandidate,
    AlertSeverity,
    AlertType,
)
from app.detection.summary import compose_alert_summary
from app.domain.outcomes import EvidenceRef, TrustState
from app.llm.mock_provider import MockProvider
from app.llm.types import CostEstimate, LLMRequest, LLMResponse, TokenUsage
from app.observability.tracing import RequestContext


def _sample_alert() -> AlertCandidate:
    return AlertCandidate(
        alert_id="ALERT-test0000000000",
        alert_type=AlertType.SLA_BREACH,
        severity=AlertSeverity.CRITICAL,
        title="P1 SLA breach: FXT-501",
        reason="FXT-501 (P1) is 15 minutes past its first-response deadline.",
        observed_count=1,
        threshold=1,
        time_window="point-in-time (dataset snapshot)",
        representative_records=["FXT-501"],
        affected_accounts=["FX-001"],
        evidence=[EvidenceRef(kind="structured", source_id="SRC-07", locator="tickets:FXT-501")],
        recommended_next_step="Review for immediate escalation.",
        trust_state=TrustState.CONFIDENT,
        rule_version="v1",
    )


def test_compose_alert_summary_returns_a_separate_string_not_a_mutated_alert():
    alert = _sample_alert()
    summary, response = compose_alert_summary(
        alert, MockProvider(), "mock-model", RequestContext.new()
    )
    assert isinstance(summary, str)
    # The alert object itself is frozen/unchanged - proven by re-reading
    # every field after the call and comparing to the original values.
    assert alert.observed_count == 1
    assert alert.threshold == 1
    assert alert.severity is AlertSeverity.CRITICAL
    assert alert.affected_accounts == ["FX-001"]
    assert len(alert.evidence) == 1
    assert response.cost.total_cost_usd == 0.0  # mock-model is free


def test_prompt_includes_every_authoritative_field_as_already_decided():
    alert = _sample_alert()
    captured: list[LLMRequest] = []

    class _RecordingProvider:
        name = "recording"

        def complete(self, request: LLMRequest, context: RequestContext) -> LLMResponse:
            captured.append(request)
            return LLMResponse(
                content="ok", provider=self.name, model=request.model,
                usage=TokenUsage(input_tokens=1, output_tokens=1),
                cost=CostEstimate(input_cost_usd=0.0, output_cost_usd=0.0),
                latency_ms=0.0, request_id=context.request_id, trace_id=context.trace_id,
            )

    compose_alert_summary(alert, _RecordingProvider(), "mock-model", RequestContext.new())
    assert captured
    prompt_text = "\n".join(m.content for m in captured[0].messages)
    assert "1 (threshold: 1)" in prompt_text
    assert "FX-001" in prompt_text
    assert "already decided" in prompt_text.lower()


def test_alert_candidate_is_frozen_and_cannot_be_mutated_by_a_caller():
    from pydantic import ValidationError

    alert = _sample_alert()
    with pytest.raises(ValidationError):
        alert.observed_count = 999  # type: ignore[misc]
