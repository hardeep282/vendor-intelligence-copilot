"""copilot.llm.prompts: loads and validates versioned prompt YAML files."""

from __future__ import annotations

import pytest

from copilot.llm.prompts import PromptNotFoundError, load_prompt


def test_loads_latest_version_by_default() -> None:
    prompt = load_prompt("vendor_insight")
    assert prompt.name == "vendor_insight"
    assert prompt.version == 1
    assert prompt.model == "claude-sonnet-5"
    assert prompt.effort == "medium"
    assert prompt.cache_system is True


def test_loads_explicit_version() -> None:
    prompt = load_prompt("vendor_insight", version=1)
    assert prompt.version == 1


def test_missing_prompt_name_raises() -> None:
    with pytest.raises(PromptNotFoundError):
        load_prompt("does-not-exist")


def test_missing_version_raises() -> None:
    with pytest.raises(PromptNotFoundError):
        load_prompt("vendor_insight", version=99)


def test_render_system_substitutes_role() -> None:
    prompt = load_prompt("vendor_insight")
    rendered = prompt.render_system(role="analyst")
    assert '"analyst" role' in rendered
    assert "{role}" not in rendered


def test_render_user_substitutes_vendor_fields() -> None:
    prompt = load_prompt("vendor_insight")
    rendered = prompt.render_user(vendor_name="ACME CO", vendor_data_block="{}")
    assert "ACME CO" in rendered
    assert "{vendor_name}" not in rendered
