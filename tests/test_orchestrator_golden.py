"""Tests for the orchestrator golden set (Day 6 step 7). Pure schema/data checks, no network,
no LLM -- actually running these 10 questions end to end against the real Orchestrator is
scripts/run_orchestrator_golden.py's job, on your own machine with your own API key.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from copilot.evals.orchestrator_golden import OrchestratorGoldenQuestion, load_orchestrator_golden


def test_loads_exactly_ten_questions() -> None:
    questions = load_orchestrator_golden()
    assert len(questions) == 10
    assert len({q.id for q in questions}) == 10  # unique ids


def test_every_question_names_at_least_two_distinct_agents() -> None:
    for q in load_orchestrator_golden():
        assert len(q.expected_agents) >= 2
        assert len(set(q.expected_agents)) == len(q.expected_agents)


def test_inventory_planning_questions_also_expect_forecasting_risk() -> None:
    """orchestrator_plan's own rule: planning inventory_planning always implies planning
    forecasting_risk too, since the former needs the latter's output. A golden question that
    expects inventory_planning without forecasting_risk would fail against a correctly-behaving
    planner for a reason that has nothing to do with the question itself.
    """
    for q in load_orchestrator_golden():
        if "inventory_planning" in q.expected_agents:
            assert "forecasting_risk" in q.expected_agents, q.id


def test_a_question_with_only_one_expected_agent_is_rejected() -> None:
    with pytest.raises(ValidationError):
        OrchestratorGoldenQuestion(
            id="x", question="x?", role="analyst", expected_agents=["data_analyst"]
        )


def test_duplicate_expected_agents_are_rejected() -> None:
    with pytest.raises(ValidationError):
        OrchestratorGoldenQuestion(
            id="x",
            question="x?",
            role="analyst",
            expected_agents=["data_analyst", "data_analyst"],
        )
