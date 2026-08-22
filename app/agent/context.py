"""Trusted backend request context (Phase 3 s4). Every field here is set by
the backend from a validated session/auth layer before the agent runs -
never parsed or inferred from the user's message text. There is
deliberately no code path anywhere in app/agent/ that reads user_id, role,
or account_scope out of the question string; AuthContext (already
enforced below the model since Phase 1) is embedded here, not replaced.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.authorization.context import AuthContext


class AgentRequestContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    trace_id: str
    user_id: str
    auth: AuthContext
    dataset_snapshot_time: datetime

    @property
    def role(self):
        return self.auth.role

    @property
    def account_scope(self) -> list[str] | None:
        return self.auth.account_scope
