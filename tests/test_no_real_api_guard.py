"""The shared safety net in tests/conftest.py: no test may reach the real Anthropic API.

Added 10 Nov 2026 after one MCP test, on a laptop with a real key in `.env`, made a real paid
Claude call (about one cent). This proves the net is actually in place for every test.
"""

from __future__ import annotations

import anthropic
import pytest


def test_a_real_sdk_call_fails_loudly_during_tests() -> None:
    client = anthropic.Anthropic(api_key="sk-ant-dummy-not-real", max_retries=0)
    with pytest.raises(RuntimeError, match="real Anthropic API"):
        client.messages.create(
            model="claude-sonnet-5", max_tokens=1, messages=[{"role": "user", "content": "hi"}]
        )
    with pytest.raises(RuntimeError, match="real Anthropic API"):
        client.messages.count_tokens(
            model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}]
        )
