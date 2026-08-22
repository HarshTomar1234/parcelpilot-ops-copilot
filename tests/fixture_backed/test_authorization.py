"""Authorization/security regression coverage that runs even when the real
pack is unavailable - Phase 3 pre-flight 2.1 explicitly calls out
"security" as a public-CI test category, so this must not silently
disappear from CI just because the confidential pack is missing.
"""

import pytest

from app.agent.tools import (
    CalculateSupportOutcomeRequest,
    CalculationType,
    LookupKind,
    LookupStructuredDataRequest,
    calculate_support_outcome_tool,
    lookup_structured_data_tool,
)
from app.authorization.context import AuthContext, Role
from app.domain.cancellation import evaluate_cancellation
from app.errors import NotAuthorizedError
from app.observability.tracing import RequestContext
from tests.fixtures.seed_fixture_db import (
    FIXTURE_AGREEMENT_OVERRIDES,
    FIXTURE_DEFAULT_SOURCE,
    FIXTURE_FEE_RULES,
)

_REGISTRY = {"overrides": FIXTURE_AGREEMENT_OVERRIDES, "defaults": FIXTURE_DEFAULT_SOURCE}


def test_scoped_context_blocks_cross_account_order(conn, clock):
    scoped = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["FX-002"])
    with pytest.raises(NotAuthorizedError):
        evaluate_cancellation(
            conn, "FXO-1001", scoped, clock, fee_rules=FIXTURE_FEE_RULES, **_REGISTRY
        )


def test_tool_layer_blocks_cross_account_lookup(conn, clock):
    scoped = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["FX-002"])
    request = LookupStructuredDataRequest(kind=LookupKind.GET_ORDER, entity_id="FXO-1001")
    with pytest.raises(NotAuthorizedError):
        lookup_structured_data_tool(conn, request, scoped, clock, RequestContext.new())


def test_tool_layer_blocks_cross_account_calculation(conn, clock):
    scoped = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["FX-002"])
    request = CalculateSupportOutcomeRequest(
        calculation_type=CalculationType.CANCELLATION, entity_id="FXO-1001"
    )
    with pytest.raises(NotAuthorizedError):
        calculate_support_outcome_tool(conn, request, scoped, clock, RequestContext.new())


def test_scoped_context_allows_in_scope_access(conn, clock):
    scoped = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["FX-001"])
    result = evaluate_cancellation(
        conn, "FXO-1001", scoped, clock, fee_rules=FIXTURE_FEE_RULES, **_REGISTRY
    )
    assert result.result is not None
    assert result.result.fee_inr == 0.0
