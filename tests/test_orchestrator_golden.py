"""Tests for the orchestrator golden set (Day 6 step 7). Pure schema/data checks, no network,
no LLM -- actually running these 11 questions end to end against the real Orchestrator is
scripts/run_orchestrator_golden.py's job, on your own machine with your own API key.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from copilot.evals.orchestrator_golden import (
    OrchestratorGoldenQuestion,
    load_orchestrator_golden,
    missing_mentions,
)


def test_loads_exactly_eleven_questions() -> None:
    """v2 (30 Oct 2026) = v1's ten + oq-011."""
    questions = load_orchestrator_golden()
    assert len(questions) == 11
    assert len({q.id for q in questions}) == 11  # unique ids


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


# -- oq-011 and must_mention (30 Oct 2026) ---------------------------------------------------


def test_oq_011_requires_the_real_top_controllable_vendors() -> None:
    q = next(q for q in load_orchestrator_golden() if q.id == "oq-011")
    assert q.must_mention == ["MARTIGNETTI", "ULTRA BEVERAGE", "WALKER", "PERFECTA"]
    assert set(q.expected_agents) == {"data_analyst", "forecasting_risk"}


def test_the_wrong_ranking_from_the_real_run_fails_the_check() -> None:
    """The 30 Oct answer ranked by total leakage: it named Diageo, Jim Beam, Pernod Ricard,
    Martignetti and Bacardi, and left out Ultra Beverage, M S Walker and Perfecta."""
    wrong = (
        "the top vendors are DIAGEO NORTH AMERICA INC, JIM BEAM BRANDS COMPANY, PERNOD RICARD "
        "USA, MARTIGNETTI COMPANIES, and BACARDI USA INC"
    )
    assert missing_mentions(wrong, ["MARTIGNETTI", "ULTRA BEVERAGE", "WALKER", "PERFECTA"]) == [
        "ULTRA BEVERAGE",
        "WALKER",
        "PERFECTA",
    ]


def test_the_right_ranking_passes_whatever_the_casing() -> None:
    right = "Martignetti Companies, Ultra Beverage Company LLP, M S Walker Inc, Perfecta Wines"
    assert missing_mentions(right, ["MARTIGNETTI", "ULTRA BEVERAGE", "WALKER", "PERFECTA"]) == []
    assert missing_mentions(None, ["X"]) == ["X"]
