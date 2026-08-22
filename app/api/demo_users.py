"""Demo identity registry (Phase 6 s4-5). This is a hosted-assessment
stand-in for a real identity provider, never a design for one - the server
maps a client-supplied demo identity slug to a real, server-owned
AuthContext; the client never supplies role or account_scope directly, so
it can never widen its own access.

DEFAULT_DEMO_USERS matches the real source pack's four accounts
(ACCT-001..004). tests override get_demo_users (app/api/deps.py) with an
equivalent fixture-shaped registry so the same routes work against
tests/fixtures/seed_fixture_db.py without needing the real pack.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.authorization.context import AuthContext, Role


class DemoUser(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str
    role: Role
    account_scope: list[str] | None = None

    def to_auth_context(self) -> AuthContext:
        return AuthContext(role=self.role, account_scope=self.account_scope)


DEFAULT_DEMO_USERS: dict[str, DemoUser] = {
    "ops_admin": DemoUser(
        id="ops_admin",
        display_name="Priya Sharma - Operations Admin (all accounts)",
        role=Role.OPERATIONS_ADMIN,
        account_scope=None,
    ),
    "support_agent": DemoUser(
        id="support_agent",
        display_name="Rahul Verma - Support Agent (Northstar Logistics, ACCT-001)",
        role=Role.SUPPORT_AGENT,
        account_scope=["ACCT-001"],
    ),
    "restricted_support": DemoUser(
        id="restricted_support",
        display_name="Anita Desai - Restricted Support (LumenWorks, ACCT-002)",
        role=Role.RESTRICTED_SUPPORT,
        account_scope=["ACCT-002"],
    ),
}
