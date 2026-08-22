"""Unified outcome model every domain service returns.

AGENTS.md rule 5: critical calculations are deterministic Python, and the
LLM (when one exists) may only explain a DecisionResult, never alter it.
Rule 6: every substantive answer has traceable evidence - EvidenceRef is
that trace, typed by the three citation kinds AGENTS.md distinguishes
(document, structured record, calculation).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class TrustState(StrEnum):
    CONFIDENT = "CONFIDENT"
    CONDITIONAL = "CONDITIONAL"
    UNCERTAIN = "UNCERTAIN"
    ESCALATE = "ESCALATE"


class EvidenceRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["document", "structured", "calculation"]
    source_id: str
    locator: str | None = None
    note: str | None = None


class Conflict(BaseModel):
    model_config = ConfigDict(frozen=True)

    winner_source_id: str
    loser_source_id: str
    scope: str
    reason: str
    needs_human_review: bool = False


T = TypeVar("T", bound=BaseModel)


class DecisionResult(BaseModel, Generic[T]):
    """The envelope every domain service (cancellation, service credit, SLA,
    severity) returns. `result` carries the domain-specific payload; every
    other field is common machinery for trust, evidence, and conflicts.
    """

    result: T | None
    trust_state: TrustState
    reason: str
    evidence: list[EvidenceRef] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    source_notes: list[str] = Field(default_factory=list)
    calculation_inputs: dict[str, object] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    needs_human_review: bool = False


def trust_from(*, review_required: bool, has_assumptions: bool) -> TrustState:
    """Shared trust-state derivation: a review requirement always wins
    (we cannot vouch for the outcome), otherwise an unresolved assumption
    downgrades CONFIDENT to CONDITIONAL.
    """
    if review_required:
        return TrustState.ESCALATE
    if has_assumptions:
        return TrustState.CONDITIONAL
    return TrustState.CONFIDENT
