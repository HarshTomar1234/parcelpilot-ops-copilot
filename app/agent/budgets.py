"""Execution budgets (Phase 3 s3). When a limit is reached the orchestrator
returns a controlled FAILED/INSUFFICIENT_EVIDENCE result - it never
silently continues past a budget.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AgentBudget(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_iterations: int = 6
    max_tool_calls: int = 6
    max_llm_calls: int = 2
    max_context_tokens: int = 8000
    max_output_tokens: int = 1024
    max_wall_clock_seconds: float = 30.0
    max_estimated_cost_usd: float = 0.50


DEFAULT_BUDGET = AgentBudget()
