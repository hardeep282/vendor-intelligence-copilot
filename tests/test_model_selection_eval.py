"""Tests for the Model Selection Agent's eval harness (Day 5 step 6): the golden-set loader, the
free catalog-membership metrics, and the LLM-judged reasoning_grounded check (fake LLM, no
network -- same convention as tests/test_rag_quality.py).
"""

from __future__ import annotations

from copilot.agents.model_selection import ModelSelectionResult, all_model_families
from copilot.evals.model_selection_golden import load_model_selection_golden
from copilot.evals.model_selection_metrics import model_family_acceptable, task_type_correct
from copilot.evals.model_selection_quality import reasoning_grounded
from copilot.llm.client import LLMClient
from tests.fakes.anthropic_fakes import FakeMessagesResource, structured_response


def test_golden_set_loads_eight_questions_two_per_task_type() -> None:
    questions = load_model_selection_golden()
    assert len(questions) == 8
    task_types = [q.expected_task_type for q in questions]
    assert task_types.count("classification") == 2
    assert task_types.count("clustering") == 2
    assert task_types.count("regression") == 2
    assert task_types.count("forecasting") == 2


def test_every_golden_questions_acceptable_families_exist_in_the_real_catalog() -> None:
    # Guards against the golden set drifting out of sync with MODEL_CATALOG -- a typo'd family
    # name here would otherwise silently make every eval run score 0 for that question forever.
    catalog = all_model_families()
    for q in load_model_selection_golden():
        for family in q.acceptable_model_families:
            assert family in catalog, f"{q.id}: {family!r} is not in the real catalog"


def test_task_type_correct_scores_1_on_a_match_and_0_on_a_mismatch() -> None:
    golden = load_model_selection_golden()[0]
    right = ModelSelectionResult(
        requirement=golden.requirement,
        task_type=golden.expected_task_type,
        model_family=golden.acceptable_model_families[0],
        reasoning="x",
        abstained=False,
    )
    assert task_type_correct(right, golden).score == 1.0

    wrong_type = "regression" if golden.expected_task_type != "regression" else "clustering"
    wrong = ModelSelectionResult(
        requirement=golden.requirement, task_type=wrong_type, model_family="x",  # type: ignore[arg-type]
        reasoning="x", abstained=False,
    )
    assert task_type_correct(wrong, golden).score == 0.0


def test_task_type_correct_scores_0_on_abstain() -> None:
    golden = load_model_selection_golden()[0]
    abstained = ModelSelectionResult(
        requirement=golden.requirement, abstained=True, abstain_reason="x"
    )
    assert task_type_correct(abstained, golden).score == 0.0


def test_model_family_acceptable_scores_1_for_any_family_in_the_accepted_set() -> None:
    golden = load_model_selection_golden()[0]
    for family in golden.acceptable_model_families:
        result = ModelSelectionResult(
            requirement=golden.requirement,
            task_type=golden.expected_task_type,
            model_family=family,
            reasoning="x",
            abstained=False,
        )
        assert model_family_acceptable(result, golden).score == 1.0


def test_model_family_acceptable_scores_0_for_a_family_outside_the_accepted_set() -> None:
    golden = load_model_selection_golden()[0]
    result = ModelSelectionResult(
        requirement=golden.requirement,
        task_type=golden.expected_task_type,
        model_family="definitely-not-accepted",
        reasoning="x",
        abstained=False,
    )
    assert model_family_acceptable(result, golden).score == 0.0


def test_model_family_acceptable_scores_0_on_abstain() -> None:
    golden = load_model_selection_golden()[0]
    abstained = ModelSelectionResult(
        requirement=golden.requirement, abstained=True, abstain_reason="x"
    )
    assert model_family_acceptable(abstained, golden).score == 0.0


def _llm_with(responses: list[object]) -> LLMClient:
    llm = LLMClient(api_key="sk-test-not-real")
    llm._client.messages = FakeMessagesResource(responses)  # type: ignore[attr-defined]
    return llm


def test_reasoning_grounded_scores_1_when_the_judge_says_grounded() -> None:
    llm = _llm_with([structured_response({"grounded": True})])
    score = reasoning_grounded(llm, "forecast demand", "ets", "monthly history, no labels")
    assert score.score == 1.0
    assert score.key == "reasoning_grounded"


def test_reasoning_grounded_scores_0_when_the_judge_says_not_grounded() -> None:
    llm = _llm_with([structured_response({"grounded": False})])
    score = reasoning_grounded(llm, "forecast demand", "ets", "generic ML boilerplate")
    assert score.score == 0.0
