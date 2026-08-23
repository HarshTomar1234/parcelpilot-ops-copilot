"""Shared provider construction, used by both the CLI dev harness
(scripts/run_agent_cli.py) and the API layer (app/api/deps.py) so the
"live requires ANTHROPIC_API_KEY, otherwise MockProvider, never fabricate
a live result" rule lives in exactly one place.
"""

from __future__ import annotations

import os

from app.llm.base import LLMProvider
from app.llm.gateway import ParcelPilotLLMGateway
from app.llm.mock_provider import MockProvider


def build_default_provider(live: bool, model: str) -> tuple[LLMProvider, str]:
    """live=False (or no ANTHROPIC_API_KEY) always returns MockProvider -
    deterministic, free, no network. live=True with a key returns a
    gateway that tries the real Anthropic provider first and falls back
    to MockProvider only on a transient failure - never silently serving
    a live-quality answer from a provider that wasn't actually reached."""
    if not live:
        return MockProvider(), "mock-model"

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "live mode requires ANTHROPIC_API_KEY; refusing to fabricate a live result"
        )

    from app.llm.anthropic_provider import AnthropicProvider

    gateway = ParcelPilotLLMGateway(
        [(AnthropicProvider(api_key=api_key), model), (MockProvider(), "mock-model")]
    )
    return gateway, model
