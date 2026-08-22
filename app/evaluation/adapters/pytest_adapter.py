"""EvaluationCase -> pytest.

Checks a golden case's *scalar* expected_facts (numbers, booleans, and the
small enum-like status/severity strings) against the actual result of
calculate_support_outcome_tool. Narrative/free-text expected_facts values
(e.g. a golden case's "delay_reference": "snapshot (pickup_actual_at is
null, delay still accruing)") are intentionally not string-matched here -
grading free text against a reference is DeepEval's job (answer quality),
not this adapter's (deterministic-fact regression). Every field not in a
FIELD_EXTRACTORS map is reported as skipped, never silently ignored, so a
case that turns out to have zero checkable fields is visible, not a false
pass.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from app.agent.tools import CalculationType
from app.evaluation.cases import EvaluationCase

_CANCELLATION: dict[str, Callable[[dict], object]] = {
    "fee_inr": lambda r: r["fee_inr"],
    "minutes_since_booking": lambda r: r["minutes_since_booking"],
    "order_status": lambda r: r["order_status"],
    "can_cancel": lambda r: r["decision"] == "can_cancel",
}
_SERVICE_CREDIT: dict[str, Callable[[dict], object]] = {
    "eligible": lambda r: r["eligible"],
    "credit_inr": lambda r: r["credit_inr"],
    "delay_hours_at_snapshot": lambda r: r["delay_hours"],
    "manager_approval_required": lambda r: r["manager_approval_required"],
}
_SLA: dict[str, Callable[[dict], object]] = {
    "breached": lambda r: r["breached"],
    "target_minutes": lambda r: r["target_minutes"],
    "breached_by_minutes": lambda r: r["elapsed_minutes_past_deadline"],
}
_SEVERITY: dict[str, Callable[[dict], object]] = {
    "derived_severity": lambda r: r["severity"],
}

FIELD_EXTRACTORS: dict[CalculationType, dict[str, Callable[[dict], object]]] = {
    CalculationType.CANCELLATION: _CANCELLATION,
    CalculationType.SERVICE_CREDIT: _SERVICE_CREDIT,
    CalculationType.SLA: _SLA,
    CalculationType.SEVERITY: _SEVERITY,
}


@dataclass(frozen=True)
class CaseCheckResult:
    case_id: str
    calculation_type: CalculationType
    checked: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.mismatches


def check_case_against_result(
    case: EvaluationCase, calculation_type: CalculationType, result: dict
) -> CaseCheckResult:
    extractors = FIELD_EXTRACTORS[calculation_type]
    checked: list[str] = []
    skipped: list[str] = []
    mismatches: list[str] = []
    for field_name, expected in case.expected_facts.items():
        extractor = extractors.get(field_name)
        if extractor is None:
            skipped.append(field_name)
            continue
        actual = extractor(result)
        if actual != expected:
            mismatches.append(f"{field_name}: expected {expected!r}, got {actual!r}")
        else:
            checked.append(field_name)
    return CaseCheckResult(
        case_id=case.case_id, calculation_type=calculation_type,
        checked=checked, skipped=skipped, mismatches=mismatches,
    )


def entity_ref(case: EvaluationCase) -> tuple[str, str] | None:
    """('orders', 'ORD-1001') or ('tickets', 'TKT-501') from the case's own
    SRC-07 structured citation - never invented, only parsed."""
    for citation in case.expected_citations:
        if citation.startswith("SRC-07:orders:"):
            return "orders", citation.split(":")[2]
        if citation.startswith("SRC-07:tickets:"):
            return "tickets", citation.split(":")[2]
    return None
