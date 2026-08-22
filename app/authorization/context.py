"""The authorization boundary that every structured-data access function
depends on, per AGENTS.md rule 4 ("authorization is enforced in the
API/tool/data layers") and ADR-011.

Phase 1 scope: account-scope filtering only, applied inside the repository
functions before rows are returned. Role-based field allowlists, cross-account
aggregate permissions, and action-confirmation checks are Phase 4/5 - this
module exists now so the data-access signatures never need to change shape
when that lands.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Role(StrEnum):
    OPERATIONS_ADMIN = "operations_admin"
    SUPPORT_AGENT = "support_agent"
    RESTRICTED_SUPPORT = "restricted_support"


class AuthContext(BaseModel):
    """account_scope=None means unrestricted (internal tooling, ingestion,
    or an operations_admin caller). A non-None list restricts every
    structured-data lookup to those account_ids."""

    model_config = ConfigDict(frozen=True)

    role: Role
    account_scope: list[str] | None = None

    def allows_account(self, account_id: str) -> bool:
        return self.account_scope is None or account_id in self.account_scope


# Permissive context for ingestion, scripts, and Phase 1 tests that are not
# exercising authorization. Never use this to serve a real user request.
INTERNAL_SYSTEM_CONTEXT = AuthContext(role=Role.OPERATIONS_ADMIN, account_scope=None)
