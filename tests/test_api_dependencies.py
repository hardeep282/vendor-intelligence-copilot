"""Tests for `copilot.api.dependencies._build_checkpointer` (Day 8 step 7).

No real Postgres instance in this test environment (or in CI -- same licence-rule-driven
constraint the eval gate's `llm_judged` layer documents for the real snapshot/Chroma index), so
the Postgres branch is proven by monkeypatching `ConnectionPool`/`PostgresSaver` with fakes and
checking `_build_checkpointer` wires them correctly -- the same "duck-typed fake standing in for
the real client" convention `tests/test_llm_client.py` and `tests/test_api_ask.py` already use.
The SQLite branch (the default, and every local-dev/test environment) is proven against a real
`SqliteSaver`, same as every other Orchestrator checkpoint test.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver

from copilot.api import dependencies
from copilot.settings import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_build_checkpointer_defaults_to_sqlite_when_no_database_url_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CHECKPOINT_DATABASE_URL", raising=False)

    checkpointer = dependencies._build_checkpointer()

    assert isinstance(checkpointer, SqliteSaver)


def test_build_checkpointer_treats_an_empty_string_database_url_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same pydantic-settings gotcha `scripts/run_eval_gate.py` already hardened against for
    `ANTHROPIC_API_KEY`: an env var set to the empty string (e.g. a GitHub Actions secret that
    was never configured) parses as `SecretStr("")`, not `None`. A naive `is not None` check
    would wrongly try to build a `PostgresSaver` with no DSN; this must fall back to SQLite
    instead, exactly like the real-infra check in the eval gate does.
    """
    monkeypatch.setenv("CHECKPOINT_DATABASE_URL", "")

    checkpointer = dependencies._build_checkpointer()

    assert isinstance(checkpointer, SqliteSaver)


def test_build_checkpointer_builds_postgres_saver_when_database_url_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    class _FakePool:
        def __init__(self, conninfo: str, **kwargs: object) -> None:
            calls["conninfo"] = conninfo
            calls["kwargs"] = kwargs

    class _FakePostgresSaver:
        def __init__(self, pool: object) -> None:
            calls["pool"] = pool

        def setup(self) -> None:
            calls["setup_called"] = True

    monkeypatch.setenv("CHECKPOINT_DATABASE_URL", "postgresql://user:pass@localhost:5432/copilot")
    monkeypatch.setattr(dependencies, "ConnectionPool", _FakePool)
    monkeypatch.setattr(dependencies, "PostgresSaver", _FakePostgresSaver)

    checkpointer = dependencies._build_checkpointer()

    assert isinstance(checkpointer, _FakePostgresSaver)
    assert calls["conninfo"] == "postgresql://user:pass@localhost:5432/copilot"
    assert calls["setup_called"] is True
