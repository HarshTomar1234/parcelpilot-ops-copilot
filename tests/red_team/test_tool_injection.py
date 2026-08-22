"""Red team s9: attack tool arguments directly - calling the typed tool
functions app/agent/registry.py dispatches to, the same way a
compromised planner or a bug in intent resolution could hand them a bad
request. Every tool takes a pydantic-validated typed request (never a
raw dict/SQL string) and the caller's real AuthContext - authorization is
enforced inside the repository functions the tools call through, not
re-derived from anything in the request.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent.tools import (
    CalculateSupportOutcomeRequest,
    CalculationType,
    LookupKind,
    LookupStructuredDataRequest,
    calculate_support_outcome_tool,
    lookup_structured_data_tool,
)
from app.authorization.context import AuthContext, Role
from app.detection.models import AlertType
from app.detection.rules import DEFAULT_WINDOW_DAYS
from app.errors import NotAuthorizedError, UnknownEntityError
from app.observability.tracing import RequestContext

_SCOPED = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["FX-001"])


def _rc() -> RequestContext:
    return RequestContext.new()


# ---------------- lookup_structured_data ----------------


def test_sql_like_entity_id_is_treated_as_inert_text_and_not_found(conn, clock):
    req = LookupStructuredDataRequest(kind=LookupKind.GET_TICKET, entity_id="FXT-501' OR '1'='1")
    with pytest.raises(UnknownEntityError):
        lookup_structured_data_tool(conn, req, _SCOPED, clock, _rc())


def test_unauthorized_account_id_filter_is_denied_not_silently_emptied(conn, clock):
    req = LookupStructuredDataRequest(kind=LookupKind.SEARCH_TICKETS, account_id="FX-004")
    # An explicit filter naming an account outside the caller's scope is
    # denied outright by the repository layer - stricter than a silent
    # empty result, and never FX-004's actual records either way.
    with pytest.raises(NotAuthorizedError):
        lookup_structured_data_tool(conn, req, _SCOPED, clock, _rc())


def test_get_ticket_outside_scope_raises_not_authorized_not_a_silent_empty_result(conn, clock):
    req = LookupStructuredDataRequest(kind=LookupKind.GET_TICKET, entity_id="FXT-505")  # FX-004
    with pytest.raises(NotAuthorizedError):
        lookup_structured_data_tool(conn, req, _SCOPED, clock, _rc())


def test_fake_role_cannot_be_smuggled_through_the_typed_request(conn, clock):
    """LookupStructuredDataRequest has no role/account_scope field - an
    extra "role" kwarg is silently dropped (pydantic's default
    extra="ignore"), not stored anywhere the tool could read it back, so
    it has no way to influence which auth is actually used (the caller's
    real AuthContext, passed as a separate trusted parameter)."""
    req = LookupStructuredDataRequest(
        kind=LookupKind.GET_TICKET, entity_id="FXT-505",
        role="operations_admin",  # type: ignore[call-arg]
    )
    assert not hasattr(req, "role")
    with pytest.raises(NotAuthorizedError):
        lookup_structured_data_tool(conn, req, _SCOPED, clock, _rc())


# ---------------- detect_issues (via run_operations_radar, its real backend) ----------------


def test_detect_issues_account_scope_widening_attempt_has_no_widening_field(conn, clock):
    from app.detection.service import run_operations_radar

    alerts_normal = run_operations_radar(conn, _SCOPED, clock, window_days=DEFAULT_WINDOW_DAYS)
    for alert in alerts_normal:
        assert set(alert.affected_accounts) <= {"FX-001"}


def test_detect_issues_huge_window_is_bounded_by_typed_validation(conn, clock):
    from app.api.schemas import RadarRequest

    with pytest.raises(ValidationError):
        RadarRequest(window_days=999999)


def test_detect_issues_malformed_alert_type_is_rejected_by_the_enum(conn, clock):
    with pytest.raises(ValueError):
        AlertType("not_a_real_type")


# ---------------- calculate_support_outcome ----------------


def test_mismatched_calculation_and_entity_combination_fails_safely(conn, clock):
    """An order ID handed to a ticket-shaped calculation (sla) - the
    domain layer looks up a ticket table row for an ID that's really an
    order, and must fail as unknown rather than silently computing
    garbage."""
    req = CalculateSupportOutcomeRequest(calculation_type=CalculationType.SLA, entity_id="FXO-1001")
    with pytest.raises(UnknownEntityError):
        calculate_support_outcome_tool(conn, req, _SCOPED, clock, _rc())


def test_malformed_entity_id_for_cancellation_fails_safely(conn, clock):
    req = CalculateSupportOutcomeRequest(
        calculation_type=CalculationType.CANCELLATION, entity_id="'; DROP TABLE orders;--"
    )
    with pytest.raises(UnknownEntityError):
        calculate_support_outcome_tool(conn, req, _SCOPED, clock, _rc())
    # the table survives
    still_works = CalculateSupportOutcomeRequest(
        calculation_type=CalculationType.CANCELLATION, entity_id="FXO-1001"
    )
    calculate_support_outcome_tool(conn, still_works, _SCOPED, clock, _rc())


def test_unauthorized_entity_for_calculation_raises_not_authorized(conn, clock):
    req = CalculateSupportOutcomeRequest(
        calculation_type=CalculationType.CANCELLATION, entity_id="FXO-4001"  # FX-004
    )
    with pytest.raises(NotAuthorizedError):
        calculate_support_outcome_tool(conn, req, _SCOPED, clock, _rc())


def test_calculation_type_must_be_a_real_enum_value(conn, clock):
    with pytest.raises(ValidationError):
        CalculateSupportOutcomeRequest(
            calculation_type="delete_everything",  # type: ignore[arg-type]
            entity_id="FXO-1001",
        )
