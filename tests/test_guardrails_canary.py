"""Tests for the canary-token helper (Day 7 step 2)."""

from __future__ import annotations

from copilot.guardrails.canary import canary_line, canary_token
from copilot.guardrails.policy import load_policy


def test_token_uses_policy_prefix() -> None:
    policy = load_policy()
    assert canary_token("data_analyst") == f"{policy.canary.prefix}DATA_ANALYST"


def test_token_deterministic() -> None:
    assert canary_token("knowledge") == canary_token("knowledge")


def test_different_agents_different_tokens() -> None:
    assert canary_token("data_analyst") != canary_token("action")


def test_line_contains_its_token() -> None:
    assert canary_token("action") in canary_line("action")
