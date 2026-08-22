"""Runs tests/evaluation/golden_cases.json through the real deterministic
tool layer via app/evaluation/adapters/pytest_adapter.py, instead of the
hand-picked assertions in tests/integration/test_domain_*.py. This is what
Phase 2 s13/s14 mean by "EvaluationCase -> pytest": the golden dataset
itself becomes the regression suite for the numbers that matter, and it
fails loudly if a case's expected facts stop matching the deterministic
engine's actual output.
"""

import pytest

from app.agent.tools import (
    CalculateSupportOutcomeRequest,
    CalculationType,
    calculate_support_outcome_tool,
)
from app.evaluation.adapters.pytest_adapter import (
    FIELD_EXTRACTORS,
    check_case_against_result,
    entity_ref,
)
from app.evaluation.cases import load_golden_cases
from app.observability.tracing import RequestContext


def _applicable_calc_types(table: str) -> list[CalculationType]:
    if table == "orders":
        return [CalculationType.CANCELLATION, CalculationType.SERVICE_CREDIT]
    return [CalculationType.SLA, CalculationType.SEVERITY]


def _has_checkable_facts(case) -> bool:
    ref = entity_ref(case)
    if ref is None or not case.expected_facts:
        return False
    table, _ = ref
    expected_keys = set(case.expected_facts)
    return any(
        set(FIELD_EXTRACTORS[calc_type]) & expected_keys
        for calc_type in _applicable_calc_types(table)
    )


_ALL_CASES = load_golden_cases()
# Cases like GC-011/012/014/015 expect facts about historical-resolution
# accuracy or known-issue applicability - real answer-quality questions for
# a future retrieval/reasoning agent, not numbers any of the four
# deterministic calculators produce. Excluded here, not silently "passed".
_DOMAIN_CASES = [c for c in _ALL_CASES if _has_checkable_facts(c)]
_SKIPPED_NON_DOMAIN_CASES = [
    c.case_id for c in _ALL_CASES if entity_ref(c) is not None and c not in _DOMAIN_CASES
]


def _run(conn, auth, clock, entity_id: str, calc_type: CalculationType) -> dict:
    request = CalculateSupportOutcomeRequest(calculation_type=calc_type, entity_id=entity_id)
    response = calculate_support_outcome_tool(conn, request, auth, clock, RequestContext.new())
    assert response.result is not None, f"{entity_id}/{calc_type.value} produced no result"
    return response.result


@pytest.mark.parametrize("case", _DOMAIN_CASES, ids=[c.case_id for c in _DOMAIN_CASES])
def test_golden_case_scalar_facts_match_deterministic_engine(case, conn, auth, clock):
    ref = entity_ref(case)
    assert ref is not None  # guaranteed by the _has_checkable_facts filter above
    table, entity_id = ref
    total_checked = 0
    all_mismatches: list[str] = []

    for calc_type in _applicable_calc_types(table):
        extractor_keys = set(FIELD_EXTRACTORS[calc_type])
        if not (extractor_keys & set(case.expected_facts)):
            continue  # this calculation type has no checkable overlap for this case
        result = _run(conn, auth, clock, entity_id, calc_type)
        check = check_case_against_result(case, calc_type, result)
        total_checked += len(check.checked)
        all_mismatches += check.mismatches

    assert total_checked > 0, f"{case.case_id}: no checkable scalar facts found (adapter gap?)"
    assert not all_mismatches, f"{case.case_id}: {all_mismatches}"


def test_non_domain_cases_are_the_expected_answer_quality_ones():
    """Locks in *which* cases the adapter excludes, so a real regression
    (entity_ref() breaking, a category being renamed) is distinguishable
    from a legitimate new non-domain case being added to the golden set."""
    assert set(_SKIPPED_NON_DOMAIN_CASES) == {"GC-011", "GC-012", "GC-014", "GC-015"}


def test_all_order_and_ticket_referencing_cases_are_accounted_for():
    with_entity = [c.case_id for c in _ALL_CASES if entity_ref(c) is not None]
    accounted = {c.case_id for c in _DOMAIN_CASES} | set(_SKIPPED_NON_DOMAIN_CASES)
    assert set(with_entity) == accounted
