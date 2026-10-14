"""Tests for the Model Selection Agent (Day 5 step 6, Addendum A1). No network and no API key,
same convention as tests/test_rag_corrective.py and tests/test_sql_service.py: the LLM side is
FakeMessagesResource, queued in the exact order the graph is expected to call it in.
"""

from __future__ import annotations

from copilot.agents.model_selection import (
    MAX_REVISIONS,
    ModelSelectionAgent,
    all_model_families,
)
from copilot.llm.client import LLMClient
from tests.fakes.anthropic_fakes import FakeMessagesResource, structured_response


def _llm_with(responses: list[object]) -> LLMClient:
    llm = LLMClient(api_key="sk-test-not-real")
    llm._client.messages = FakeMessagesResource(responses)  # type: ignore[attr-defined]
    return llm


def test_accepts_the_first_proposal_when_the_critique_says_correct() -> None:
    llm = _llm_with(
        [
            structured_response(
                {
                    "task_type": "forecasting",
                    "model_family": "ets",
                    "reasoning": "monthly history with a horizon, no labels",
                }
            ),
            structured_response({"verdict": "correct", "concerns": "none"}),
        ]
    )
    agent = ModelSelectionAgent(llm)

    result = agent.select("forecast next quarter's portfolio demand")

    assert result.abstained is False
    assert result.task_type == "forecasting"
    assert result.model_family == "ets"
    assert result.revisions == 0
    assert result.rejected_proposals == []
    assert result.llm_calls == 2


def test_revises_once_then_accepts_the_better_proposal() -> None:
    llm = _llm_with(
        [
            structured_response(
                {
                    "task_type": "regression",
                    "model_family": "linear_regression",
                    "reasoning": "numeric target",
                }
            ),
            structured_response(
                {
                    "verdict": "incorrect",
                    "concerns": "labelled categories, not a continuous target",
                    "suggested_model_family": "random_forest",
                }
            ),
            structured_response(
                {
                    "task_type": "classification",
                    "model_family": "random_forest",
                    "reasoning": "labelled at-risk/healthy categories, per the revision feedback",
                }
            ),
            structured_response({"verdict": "correct", "concerns": "none"}),
        ]
    )
    agent = ModelSelectionAgent(llm)

    result = agent.select("classify SKUs as at-risk or healthy from tabular features")

    assert result.abstained is False
    assert result.model_family == "random_forest"
    assert result.revisions == 1
    assert result.rejected_proposals == ["linear_regression"]
    assert result.llm_calls == 4


def test_abstains_after_exhausting_the_revision_budget() -> None:
    responses = []
    for i in range(MAX_REVISIONS + 1):
        responses.append(
            structured_response(
                {
                    "task_type": "clustering",
                    "model_family": "kmeans",
                    "reasoning": f"attempt {i}",
                }
            )
        )
        responses.append(
            structured_response(
                {
                    "verdict": "incorrect",
                    "concerns": f"still wrong on attempt {i}",
                    "suggested_model_family": None,
                }
            )
        )
    llm = _llm_with(responses)
    agent = ModelSelectionAgent(llm)

    result = agent.select("an ambiguous requirement")

    assert result.abstained is True
    assert result.model_family is None
    assert result.revisions == MAX_REVISIONS
    assert len(result.rejected_proposals) == MAX_REVISIONS
    assert result.abstain_reason is not None
    assert "still wrong on attempt" in result.abstain_reason
    assert result.llm_calls == 2 * (MAX_REVISIONS + 1)


def test_an_ambiguous_verdict_also_triggers_a_revision_not_acceptance() -> None:
    llm = _llm_with(
        [
            structured_response(
                {
                    "task_type": "classification",
                    "model_family": "xgboost",
                    "reasoning": "under-specified requirement",
                }
            ),
            structured_response(
                {
                    "verdict": "ambiguous",
                    "concerns": "requirement doesn't say whether labels exist",
                    "suggested_model_family": None,
                }
            ),
            structured_response(
                {
                    "task_type": "classification",
                    "model_family": "xgboost",
                    "reasoning": "assuming labels exist per the clarified requirement",
                }
            ),
            structured_response({"verdict": "correct", "concerns": "none"}),
        ]
    )
    agent = ModelSelectionAgent(llm)

    result = agent.select("an under-specified requirement")

    assert result.abstained is False
    assert result.revisions == 1


def test_all_model_families_matches_the_full_catalog_across_every_task_type() -> None:
    families = all_model_families()
    assert "random_forest" in families
    assert "xgboost" in families
    assert "ets" in families
    assert "kmeans" in families
    assert "linear_regression" in families
    assert "logistic_regression" in families
    assert "naive" in families
