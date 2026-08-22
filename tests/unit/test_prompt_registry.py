import pytest

from app.agent.prompts import load_prompt, prompt_version_string


def test_loads_current_support_agent_prompt():
    text = load_prompt("support_agent_system")
    assert "trust_state" in text
    assert "search_documents" in text


def test_prompt_version_string_matches_registry():
    assert prompt_version_string("support_agent_system") == "support_agent_system_v1"


def test_can_load_an_explicit_version():
    assert load_prompt("support_agent_system", version="v1") == load_prompt("support_agent_system")


def test_unknown_prompt_name_raises():
    with pytest.raises(KeyError):
        load_prompt("not_a_real_prompt")


def test_unknown_explicit_version_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_prompt("support_agent_system", version="v99")
