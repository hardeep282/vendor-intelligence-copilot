"""Tests for TaskSpec/AgentResult (Day 6 step 1). Pure Pydantic contracts, no network, no LLM."""

from __future__ import annotations

import pytest

from copilot.agents.contracts import AgentBudget, AgentResult, TaskSpec


def test_task_spec_defaults_to_the_standard_budget() -> None:
    spec = TaskSpec(
        task_id="t1",
        agent="data_analyst",
        objective="find total freight cost for DIAGEO",
        role="analyst",
    )

    assert spec.budget == AgentBudget(
        max_steps=1, max_llm_calls=3, max_cost_usd=0.05, max_latency_s=30.0
    )
    assert spec.inputs == {}
    assert spec.constraints == {}
    assert spec.allowed_data_classes == []


def test_task_spec_carries_narrowing_constraints_without_free_text() -> None:
    spec = TaskSpec(
        task_id="t1",
        agent="data_analyst",
        objective="freight cost",
        role="analyst",
        constraints={"vendor": "DIAGEO", "period": "2024"},
    )

    assert spec.constraints["vendor"] == "DIAGEO"
    assert spec.constraints["period"] == "2024"


def test_agent_result_defaults_are_safe() -> None:
    result = AgentResult(
        task_id="t1", agent="data_analyst", status="ok", findings="freight is $1.64M"
    )

    assert result.evidence == []
    assert result.gaps == []
    assert result.data_classes == []
    assert result.confidence == "medium"
    assert result.cost_usd == 0.0


def test_data_classes_must_come_from_the_disclosure_policy_literal() -> None:
    with pytest.raises(ValueError):
        AgentResult(
            task_id="t1",
            agent="knowledge",
            status="ok",
            findings="...",
            data_classes=["top_secret"],  # type: ignore[list-item]
        )


@pytest.mark.parametrize(
    ("cost", "latency", "calls", "expected"),
    [
        (0.01, 5.0, 1, False),  # comfortably inside budget
        (0.05, 5.0, 1, False),  # exactly at the cost ceiling is not "exceeds"
        (0.06, 5.0, 1, True),  # over cost
        (0.01, 31.0, 1, True),  # over latency
        (0.01, 5.0, 4, True),  # over call count
    ],
)
def test_exceeds_checks_all_three_budget_dimensions(
    cost: float, latency: float, calls: int, expected: bool
) -> None:
    budget = AgentBudget(max_steps=1, max_llm_calls=3, max_cost_usd=0.05, max_latency_s=30.0)
    result = AgentResult(
        task_id="t1",
        agent="forecasting_risk",
        status="ok",
        findings="...",
        cost_usd=cost,
        latency_s=latency,
        llm_calls=calls,
    )

    assert result.exceeds(budget) is expected


def test_agent_name_is_restricted_to_the_five_specialist_roster() -> None:
    with pytest.raises(ValueError):
        TaskSpec(
            task_id="t1",
            agent="market_research",  # type: ignore[arg-type]
            objective="x",
            role="analyst",
        )
