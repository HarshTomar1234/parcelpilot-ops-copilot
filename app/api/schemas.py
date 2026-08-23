"""Typed request/response contracts for the HTTP API (Phase 6 s3). Every
response embeds the existing, already-typed domain/agent/detection/action
models directly (AgentRunResult, AlertCandidate, ActionOutcome) rather than
re-shaping them - the backend stays the single source of truth for what a
result looks like; this module only adds the thin envelope fields the UI
needs (which demo identity is asking, the dataset snapshot in effect).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.actions.models import ActionOutcome
from app.agent.orchestrator import AgentRunResult
from app.api.demo_users import DemoUser
from app.detection.models import AlertCandidate, AlertType
from app.detection.rules import DEFAULT_WINDOW_DAYS


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    result: AgentRunResult
    viewed_as: DemoUser
    dataset_snapshot: datetime


class RadarRequest(BaseModel):
    alert_types: list[AlertType] | None = None
    window_days: int = Field(default=DEFAULT_WINDOW_DAYS, ge=1, le=365)
    group_by_account: bool = False


class RadarResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    alerts: list[AlertCandidate]
    total_alerts: int
    grouped_by_account: dict[str, list[str]] | None
    latency_ms: float
    viewed_as: DemoUser
    dataset_snapshot: datetime


class PrepareEscalationRequest(BaseModel):
    ticket_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=500)


class ConfirmActionRequest(BaseModel):
    action_id: str = Field(min_length=1, max_length=64)
    payload_hash: str = Field(min_length=1, max_length=128)


class ExecuteActionRequest(BaseModel):
    action_id: str = Field(min_length=1, max_length=64)


class ActionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: ActionOutcome
    viewed_as: DemoUser
