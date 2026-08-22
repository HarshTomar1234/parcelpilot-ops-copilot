"""Versioned prompt loading. AGENTS.md rule 19 principle applied to
prompts: they are inspectable files, not strings buried in Python, and
every load is traceable to an exact version - MLflow experiment metadata
records this version, never "whatever the file currently says".
"""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent

# Logical name -> current version. Bump the value (and add the new file)
# when a prompt changes; never edit a shipped version's file in place.
CURRENT_VERSIONS: dict[str, str] = {
    "support_agent_system": "v1",
    "operations_radar_summary_system": "v1",
}


def load_prompt(name: str, version: str | None = None) -> str:
    """Load a versioned prompt by logical name, e.g. load_prompt(
    "support_agent_system") -> the text of support_agent_system_v1.md."""
    resolved_version = version or CURRENT_VERSIONS.get(name)
    if resolved_version is None:
        raise KeyError(f"no current version registered for prompt {name!r}")
    path = _PROMPTS_DIR / f"{name}_{resolved_version}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def prompt_version_string(name: str) -> str:
    """e.g. 'support_agent_system_v1' - what MLflow experiment metadata
    and LLMRequest.prompt_version should record."""
    version = CURRENT_VERSIONS.get(name)
    if version is None:
        raise KeyError(f"no current version registered for prompt {name!r}")
    return f"{name}_{version}"
