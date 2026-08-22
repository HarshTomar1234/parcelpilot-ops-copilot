from app.policy.applicability import ClauseTopic, resolve_applicability


def test_northstar_overrides_cancellation_fee(conn, clock):
    result = resolve_applicability(
        conn, ClauseTopic.CANCELLATION_FEE, "ACCT-001", clock.now().date()
    )
    assert result.winning_source_id == "SRC-05"
    assert result.overridden_source_id == "SRC-03"
    assert result.needs_human_review is False


def test_lumenworks_does_not_override_cancellation_fee(conn, clock):
    # SRC-06 s2 explicitly declines to override - default SOP applies.
    result = resolve_applicability(
        conn, ClauseTopic.CANCELLATION_FEE, "ACCT-002", clock.now().date()
    )
    assert result.winning_source_id == "SRC-03"
    assert result.overridden_source_id is None


def test_lumenworks_overrides_service_credit_threshold(conn, clock):
    result = resolve_applicability(
        conn, ClauseTopic.SERVICE_CREDIT_THRESHOLD_AND_AMOUNT, "ACCT-002", clock.now().date()
    )
    assert result.winning_source_id == "SRC-06"
    assert result.overridden_source_id == "SRC-03"


def test_northstar_does_not_override_service_credit_threshold(conn, clock):
    # SRC-05 s3 only caps the aggregate; the per-credit threshold/amount is unchanged.
    result = resolve_applicability(
        conn, ClauseTopic.SERVICE_CREDIT_THRESHOLD_AND_AMOUNT, "ACCT-001", clock.now().date()
    )
    assert result.winning_source_id == "SRC-03"


def test_northstar_introduces_the_aggregate_cap_with_no_default(conn, clock):
    result = resolve_applicability(
        conn, ClauseTopic.SERVICE_CREDIT_AGGREGATE_CAP, "ACCT-001", clock.now().date()
    )
    assert result.winning_source_id == "SRC-05"
    assert result.overridden_source_id is None


def test_account_with_no_agreement_falls_back_to_default(conn, clock):
    result = resolve_applicability(
        conn, ClauseTopic.CANCELLATION_FEE, "ACCT-003", clock.now().date()
    )
    assert result.winning_source_id == "SRC-03"
    assert result.overridden_source_id is None
    assert "No agreement" in result.reason


def test_sla_topic_prefers_the_agreement_for_both_account_scoped_accounts(conn, clock):
    northstar = resolve_applicability(
        conn, ClauseTopic.SLA_FIRST_RESPONSE, "ACCT-001", clock.now().date()
    )
    lumenworks = resolve_applicability(
        conn, ClauseTopic.SLA_FIRST_RESPONSE, "ACCT-002", clock.now().date()
    )
    assert northstar.winning_source_id == "SRC-05"
    assert lumenworks.winning_source_id == "SRC-06"


def test_enterprise_with_no_agreement_uses_default_sla(conn, clock):
    result = resolve_applicability(
        conn, ClauseTopic.SLA_FIRST_RESPONSE, "ACCT-004", clock.now().date()
    )
    assert result.winning_source_id == "SRC-01"
