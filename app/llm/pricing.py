"""Config-driven pricing (AGENTS.md rule 14 / Phase 2 s11: "pricing must be
configuration-driven, do not hard-code business rules around model prices").
Rates live in pricing.json, not in this module's logic.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.llm.types import CostEstimate

_DEFAULT_PATH = Path(__file__).parent / "pricing.json"


class PricingTable:
    def __init__(self, path: Path = _DEFAULT_PATH) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        self._rates = {k: v for k, v in raw.items() if not k.startswith("_")}

    def estimate_cost(
        self, model: str, usage_input_tokens: int, usage_output_tokens: int
    ) -> CostEstimate:
        rate = self._rates.get(model)
        if rate is None:
            raise KeyError(f"no pricing configured for model {model!r} in {_DEFAULT_PATH.name}")
        return CostEstimate(
            input_cost_usd=usage_input_tokens / 1_000_000 * rate["input_per_million_usd"],
            output_cost_usd=usage_output_tokens / 1_000_000 * rate["output_per_million_usd"],
        )

    def known_models(self) -> list[str]:
        return list(self._rates.keys())
