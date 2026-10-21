"""Tests for the API skeleton: /health and /version."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from copilot.api.main import app
from copilot.settings import get_settings


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("APP_ENV", "dev")  # never touch AWS in tests
    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_prod_startup_loads_secrets_from_ssm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_loader(prefix: str, region: str) -> list[str]:
        calls.append((prefix, region))
        return ["ANTHROPIC_API_KEY"]

    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setattr("copilot.api.main.load_into_environ", fake_loader)
    get_settings.cache_clear()
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200
    get_settings.cache_clear()
    assert calls == [("/vendor-copilot/prod", "ap-south-1")]


def test_version_reports_git_sha(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from importlib.metadata import version as package_version

    monkeypatch.setenv("GIT_SHA", "abc1234")
    get_settings.cache_clear()
    body = client.get("/version").json()
    assert body["git_sha"] == "abc1234"
    assert body["env"] == "dev"
    # Read from the installed package's own metadata rather than hardcoding a version string
    # here -- a hardcoded value just breaks (as it did going from 0.0.1 to 0.1.0 at the v0.1.0
    # release) every time pyproject.toml's version bumps, checking nothing real in the process.
    assert body["version"] == package_version("vendor-intelligence-copilot")
