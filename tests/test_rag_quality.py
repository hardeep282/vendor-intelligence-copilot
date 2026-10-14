"""Tests for the cut-down Ragas pair -- faithfulness and context_recall (Day 4 step 7). Same
fakes convention as the rest of this repo's LLM-calling tests: FakeMessagesResource, no network,
no API key.
"""

from __future__ import annotations

from copilot.evals.rag_quality import context_recall, faithfulness
from copilot.llm.client import LLMClient
from tests.fakes.anthropic_fakes import FakeMessagesResource, structured_response


def _llm_with(responses: list[object]) -> LLMClient:
    llm = LLMClient(api_key="sk-test-not-real")
    llm._client.messages = FakeMessagesResource(responses)  # type: ignore[attr-defined]
    return llm


def test_faithfulness_scores_one_when_the_grade_says_faithful() -> None:
    llm = _llm_with([structured_response({"faithful": True, "unsupported_claims": []})])
    score = faithfulness(llm, "Net 45 days.", ["payment terms are net 45 days"])
    assert score.key == "faithfulness"
    assert score.score == 1.0


def test_faithfulness_scores_zero_and_reports_unsupported_claims() -> None:
    llm = _llm_with(
        [structured_response({"faithful": False, "unsupported_claims": ["the rebate rate is 10%"]})]
    )
    score = faithfulness(llm, "Net 45 days, with a 10% rebate.", ["payment terms are net 45 days"])
    assert score.score == 0.0
    assert "10%" in score.comment


def test_context_recall_scores_one_when_context_is_sufficient() -> None:
    llm = _llm_with([structured_response({"sufficient": True, "missing_information": None})])
    score = context_recall(llm, "Net 45 days.", ["payment terms are net 45 days"])
    assert score.key == "context_recall"
    assert score.score == 1.0


def test_context_recall_scores_zero_and_reports_what_is_missing() -> None:
    llm = _llm_with(
        [
            structured_response(
                {"sufficient": False, "missing_information": "no mention of payment terms"}
            )
        ]
    )
    score = context_recall(llm, "Net 45 days.", ["an unrelated passage about freight"])
    assert score.score == 0.0
    assert "payment terms" in score.comment
