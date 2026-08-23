"""detect_issues as a registered agent tool (Phase 5 s10) - the
next tool category beyond the original three, dispatched through the same
execute_tool() boundary with the same authorization/timeout/retry
guarantees, never exposing arbitrary SQL.
"""

from __future__ import annotations

from app.agent.registry import execute_tool
from app.agent.tool_result import ToolErrorType
from app.authorization.context import AuthContext, Role
from app.observability.tracing import RequestContext


def test_tool_is_registered_and_callable(conn, auth, clock):
    result = execute_tool(
        "detect_issues", {}, conn, auth, clock, RequestContext.new()
    )
    assert result.success
    assert result.tool_name == "detect_issues"


def test_tool_filters_by_alert_type(conn, auth, clock):
    result = execute_tool(
        "detect_issues", {"alert_types": ["carrier_pattern"]},
        conn, auth, clock, RequestContext.new(),
    )
    assert result.success
    assert result.output is not None
    assert all(a.alert_type.value == "carrier_pattern" for a in result.output.alerts)


def test_tool_group_by_account_populates_grouped_field(conn, auth, clock):
    result = execute_tool(
        "detect_issues", {"group_by_account": True},
        conn, auth, clock, RequestContext.new(),
    )
    assert result.success
    assert result.output is not None
    assert result.output.grouped_by_account is not None


def test_tool_rejects_an_out_of_range_window(conn, auth, clock):
    result = execute_tool(
        "detect_issues", {"window_days": 0},
        conn, auth, clock, RequestContext.new(),
    )
    assert not result.success
    assert result.error_type is ToolErrorType.INVALID_ARGUMENTS


def test_tool_account_scope_field_cannot_widen_a_restricted_caller(conn, clock):
    scoped = AuthContext(role=Role.SUPPORT_AGENT, account_scope=["FX-002"])
    result = execute_tool(
        "detect_issues", {"account_scope": ["FX-001", "FX-002", "FX-999"]},
        conn, scoped, clock, RequestContext.new(),
    )
    assert result.success
    assert result.output is not None
    assert all("FX-001" not in a.affected_accounts for a in result.output.alerts)
    assert all("FX-999" not in a.affected_accounts for a in result.output.alerts)


def test_tool_never_exposes_a_sql_or_free_form_query_argument(conn, auth, clock):
    from app.agent.tools import DetectIssuesRequest

    fields = DetectIssuesRequest.model_fields
    assert "sql" not in fields
    assert "query" not in fields
    assert "raw_filter" not in fields
