"""Budget enforcement helpers (Phase 4 pre-flight 1A). Every AgentBudget
field must correspond to a real check, not sit unused: max_tool_calls and
max_wall_clock_seconds are enforced directly in orchestrator.py's tool
loop; max_iterations is enforced there too (see the loop's per-step check
- an "iteration" is one execute_tool() invocation, including retries, so
it is a real, distinct cap from max_tool_calls once a retryable tool
exists); max_context_tokens, max_estimated_cost_usd, and max_output_tokens
are enforced here, called from orchestrator.py before the resource they
bound is actually spent.
"""

from __future__ import annotations

from app.agent.budgets import AgentBudget
from app.llm.pricing import PricingTable

_pricing = PricingTable()


def approx_tokens(text: str) -> int:
    """Same whitespace-split proxy app/llm/mock_provider.py uses for its
    own token accounting - not billing-accurate, but cheap and consistent
    enough to gate a request before it is sent, not just report after."""
    return max(1, len(text.split()))


def estimate_worst_case_cost_usd(
    model: str, input_tokens: int, max_output_tokens: int
) -> float | None:
    """None means the model has no configured pricing entry - nothing to
    gate on, not a reason to block the request."""
    try:
        cost = _pricing.estimate_cost(model, input_tokens, max_output_tokens)
    except KeyError:
        return None
    return cost.total_cost_usd


def check_context_budget(context_tokens: int, budget: AgentBudget) -> str | None:
    """Returns a failure reason if over budget, else None."""
    if context_tokens > budget.max_context_tokens:
        return (
            f"estimated context size {context_tokens} tokens exceeds the "
            f"budget of {budget.max_context_tokens}"
        )
    return None


def check_cost_budget(estimated_cost_usd: float | None, budget: AgentBudget) -> str | None:
    if estimated_cost_usd is not None and estimated_cost_usd > budget.max_estimated_cost_usd:
        return (
            f"estimated cost ${estimated_cost_usd:.4f} exceeds the budget of "
            f"${budget.max_estimated_cost_usd:.4f}"
        )
    return None
