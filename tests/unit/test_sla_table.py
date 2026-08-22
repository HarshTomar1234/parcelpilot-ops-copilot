import pytest

from app.documents.sla_table import parse_bullet_targets, parse_grid_table
from app.errors import DocumentParseError

GRID_BODY = (
    "Plan\nP1\nP2\nP3\n"
    "Enterprise\n30 minutes, 24x7\n2 hours\n1 business day\n"
    "Growth\n2 business hours\n4 business hours\n2 business days\n"
    "Standard\n4 business hours\n1 business day\n2 business days"
)


def test_parse_grid_table_produces_nine_rows():
    targets = parse_grid_table(GRID_BODY, "SRC-TEST")
    assert len(targets) == 9
    assert {(t.plan, t.severity) for t in targets} == {
        (p, s) for p in ("Enterprise", "Growth", "Standard") for s in ("P1", "P2", "P3")
    }


def test_parse_grid_table_preserves_plan_severity_target_association():
    by_key = {(t.plan, t.severity): t for t in parse_grid_table(GRID_BODY, "SRC-TEST")}
    assert by_key[("Enterprise", "P1")].target_text == "30 minutes, 24x7"
    assert by_key[("Enterprise", "P1")].target_minutes == 30
    assert by_key[("Enterprise", "P1")].is_24x7 is True
    assert by_key[("Enterprise", "P2")].target_minutes == 120
    assert by_key[("Growth", "P1")].target_minutes is None
    assert by_key[("Growth", "P1")].requires_business_calendar is True


def test_parse_grid_table_missing_header_raises():
    with pytest.raises(DocumentParseError):
        parse_grid_table("no grid here at all", "SRC-TEST")


def test_parse_grid_table_unexpected_plan_order_raises():
    bad = GRID_BODY.replace("Enterprise", "Unknown Plan", 1)
    with pytest.raises(DocumentParseError):
        parse_grid_table(bad, "SRC-TEST")


BULLET_BODY = "intro text\n- P1: 15 minutes, 24x7\n- P2: 1 hour\n- P3: 8 business hours"


def test_parse_bullet_targets_produces_three_rows_for_the_account():
    targets = parse_bullet_targets(BULLET_BODY, "SRC-TEST", "ACCT-001")
    assert len(targets) == 3
    assert all(t.account_id == "ACCT-001" and t.plan is None for t in targets)
    p1 = next(t for t in targets if t.severity == "P1")
    assert p1.target_minutes == 15
    assert p1.is_24x7 is True


def test_parse_bullet_targets_incomplete_set_raises():
    with pytest.raises(DocumentParseError):
        parse_bullet_targets("- P1: 15 minutes, 24x7", "SRC-TEST", "ACCT-001")
