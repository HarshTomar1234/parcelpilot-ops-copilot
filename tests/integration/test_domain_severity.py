"""Cross-checked against docs/initial_rules.md R4's derived severities for
the five open tickets, plus synthetic (non-workbook) descriptions proving
the classifier generalizes rather than memorizing the five known tickets.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.domain.outcomes import TrustState
from app.domain.severity import classify_severity
from app.models.enums import TicketStatus
from app.models.structured import Ticket

_EXPECTED = {"TKT-501": "P1", "TKT-502": "P2", "TKT-503": "P3", "TKT-504": "P3", "TKT-505": "P1"}


def test_all_five_open_tickets_match_phase0_derivation(conn, auth, clock):
    from app.structured_data.repository import search_tickets

    tickets = search_tickets(conn, auth, clock.now().tzinfo, status=TicketStatus.OPEN)
    for ticket in tickets:
        result = classify_severity(ticket, conn)
        assert result.result is not None
        assert result.result.severity is not None
        assert result.result.severity.value == _EXPECTED[ticket.ticket_id], ticket.ticket_id
        assert result.trust_state is TrustState.CONFIDENT


def _ticket(description: str) -> Ticket:
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime(2026, 8, 16, 10, 0, tzinfo=tz)
    return Ticket(
        ticket_id="TKT-TEST", account_id="ACCT-001", created_at=now, status=TicketStatus.OPEN,
        subject="test", description=description, channel="email", assigned_to="X",
        last_customer_message_at=now, historical_resolution=None,
    )


def test_generalizes_to_a_synthetic_outage_description():
    result = classify_severity(_ticket("All customers see a complete outage with no workaround."))
    assert result.result is not None
    assert result.result.severity is not None
    assert result.result.severity.value == "P1"


def test_generalizes_to_a_synthetic_degraded_description():
    description = "Some users report intermittent failures; others unaffected."
    result = classify_severity(_ticket(description))
    assert result.result is not None
    assert result.result.severity is not None
    assert result.result.severity.value == "P2"


def test_generalizes_to_a_synthetic_howto_description():
    result = classify_severity(_ticket("How do we update our default carrier preference?"))
    assert result.result is not None
    assert result.result.severity is not None
    assert result.result.severity.value == "P3"


def test_ambiguous_description_abstains_rather_than_guesses():
    result = classify_severity(_ticket("The dashboard looks a bit different today."))
    assert result.result is not None
    assert result.result.severity is None
    assert result.trust_state is TrustState.UNCERTAIN
    assert result.needs_human_review is True


def test_workaround_polarity_does_not_falsely_downgrade_p1():
    # "no workaround" must not also register as the P2 "workaround exists" signal.
    description = "Complete outage of the booking system with no workaround."
    result = classify_severity(_ticket(description))
    assert result.result is not None
    assert result.result.severity is not None
    assert result.result.severity.value == "P1"
