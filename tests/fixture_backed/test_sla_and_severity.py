from app.domain.outcomes import TrustState
from app.domain.severity import classify_severity
from app.domain.sla import calculate_sla
from app.structured_data.repository import get_ticket
from app.time.clock import tz_of
from tests.fixtures.seed_fixture_db import FIXTURE_AGREEMENT_OVERRIDES, FIXTURE_DEFAULT_SOURCE

_REGISTRY = {"overrides": FIXTURE_AGREEMENT_OVERRIDES, "defaults": FIXTURE_DEFAULT_SOURCE}


def test_meridian_p1_breaches_under_its_agreement(conn, auth, clock):
    result = calculate_sla(conn, "FXT-501", auth, clock, **_REGISTRY)
    assert result.result is not None
    assert result.result.severity.value == "P1"
    assert result.result.applicable_source_id == "FIX-05"
    assert result.result.breached is True
    assert result.conflicts and result.conflicts[0].winner_source_id == "FIX-05"


def test_vertex_p1_breaches_under_default_no_agreement(conn, auth, clock):
    result = calculate_sla(conn, "FXT-505", auth, clock, **_REGISTRY)
    assert result.result is not None
    assert result.result.severity.value == "P1"
    assert result.result.applicable_source_id == "FIX-01"
    assert result.result.breached is True
    assert not result.conflicts


def test_business_hour_targets_are_conditional(conn, auth, clock):
    for ticket_id in ("FXT-502", "FXT-503", "FXT-504"):
        result = calculate_sla(conn, ticket_id, auth, clock, **_REGISTRY)
        assert result.result is not None, ticket_id
        assert result.result.breached is None, ticket_id
        assert result.trust_state is TrustState.CONDITIONAL, ticket_id


def test_all_five_open_fixture_tickets_classify_correctly(conn, auth, clock):
    expected = {"FXT-501": "P1", "FXT-502": "P2", "FXT-503": "P3", "FXT-504": "P3", "FXT-505": "P1"}
    for ticket_id, expected_severity in expected.items():
        ticket = get_ticket(conn, ticket_id, auth, tz_of(clock))
        result = classify_severity(ticket, conn)
        assert result.result is not None
        assert result.result.severity is not None
        assert result.result.severity.value == expected_severity, ticket_id
