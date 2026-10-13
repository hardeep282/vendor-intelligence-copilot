"""Tests for the SSM secrets loader, using a fake client (no AWS needed)."""

import os
from typing import Any

import pytest

from copilot.secrets import fetch_parameters, load_into_environ


class FakeSSM:
    """Returns parameters in pages of two, like SSM's NextToken pagination."""

    def __init__(self, params: dict[str, str]) -> None:
        self.items = [{"Name": k, "Value": v} for k, v in params.items()]
        self.calls: list[dict[str, Any]] = []

    def get_parameters_by_path(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        start = int(kwargs.get("NextToken", 0))
        page = self.items[start : start + 2]
        resp: dict[str, Any] = {"Parameters": page}
        if start + 2 < len(self.items):
            resp["NextToken"] = str(start + 2)
        return resp


PARAMS = {
    "/vendor-copilot/prod/ANTHROPIC_API_KEY": "sk-test-1",
    "/vendor-copilot/prod/langsmith_api_key": "ls-test-2",
    "/vendor-copilot/prod/LANGSMITH_PROJECT": "vendor-copilot-prod",
}


def test_fetch_follows_pagination_and_decrypts() -> None:
    fake = FakeSSM(PARAMS)
    got = fetch_parameters(fake, "/vendor-copilot/prod")
    assert got == {
        "ANTHROPIC_API_KEY": "sk-test-1",
        "LANGSMITH_API_KEY": "ls-test-2",
        "LANGSMITH_PROJECT": "vendor-copilot-prod",
    }
    assert len(fake.calls) == 2
    assert all(c["WithDecryption"] for c in fake.calls)


def test_load_returns_names_not_values(monkeypatch: pytest.MonkeyPatch) -> None:
    # setenv first so monkeypatch restores the original environment after the test
    for k in ("ANTHROPIC_API_KEY", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT"):
        monkeypatch.setenv(k, "placeholder")
    names = load_into_environ("/vendor-copilot/prod", "ap-south-1", client=FakeSSM(PARAMS))
    assert names == ["ANTHROPIC_API_KEY", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT"]
    assert "sk-test-1" not in names
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-test-1"
