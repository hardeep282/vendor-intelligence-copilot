"""Tests for copilot.agents.wiring (Day 6 step 7). Fakes every real service so these run
offline, no network, no real API key -- the real wiring is only exercised for real by
scripts/run_orchestrator_golden.py on your own machine.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from copilot.agents.contracts import AgentResult, TaskSpec
from copilot.agents.wiring import build_executors
from copilot.settings import get_settings


def _spec(agent: str, **constraints: str) -> TaskSpec:
    return TaskSpec(
        task_id="t0", agent=agent, objective="x", role="analyst", constraints=constraints
    )


def test_build_executors_returns_all_five_agent_names() -> None:
    executors = build_executors(
        llm=Mock(), sql_service=Mock(), rag_service=Mock(), retriever=Mock()
    )

    assert set(executors) == {
        "data_analyst",
        "forecasting_risk",
        "inventory_planning",
        "knowledge",
        "action",
    }


def test_data_analyst_executor_calls_through_to_the_sql_service() -> None:
    sql_service = Mock()
    sql_service.answer.return_value = Mock(
        abstained=False,
        sql="select 1",
        rows=[{"x": 1}],
        truncated=False,
        assumptions=[],
        self_corrections=0,
        total_cost_usd=0.001,
        total_latency_s=0.1,
        llm_calls=1,
    )
    executors = build_executors(
        llm=Mock(), sql_service=sql_service, rag_service=Mock(), retriever=Mock()
    )

    result = executors["data_analyst"](_spec("data_analyst"))

    assert isinstance(result, AgentResult)
    assert result.status == "ok"
    sql_service.answer.assert_called_once()


def test_inventory_planning_executor_chains_off_a_forecast_without_a_second_call_signature() -> (
    None
):
    """`run_inventory_planning` needs a `ForecastResult`, not a bare `TaskSpec` -- the wiring's
    `_inventory_executor` must supply that itself so this executor still satisfies the plain
    `TaskSpec -> AgentResult` shape every other entry in the map does.
    """
    executors = build_executors(
        llm=Mock(), sql_service=Mock(), rag_service=Mock(), retriever=Mock(), con=None
    )

    # Against this repo's real snapshot (skipped gracefully if it isn't built), a real
    # forecast_demand() call runs -- proving _inventory_executor's internal chaining actually
    # produces a usable AgentResult, not just that it doesn't raise on import.
    if not (get_settings().snapshot_dir / "MANIFEST.json").exists():
        pytest.skip("snapshot not built")

    result = executors["inventory_planning"](_spec("inventory_planning", level="portfolio"))

    assert result.status == "ok"
    assert "safety stock" in result.findings
