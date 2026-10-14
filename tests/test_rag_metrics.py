"""Tests for recall@k and MRR (Day 4 step 7). Pure arithmetic -- no fakes, no network needed."""

from __future__ import annotations

from copilot.evals.rag_metrics import (
    mean_recall_at_k,
    mean_reciprocal_rank,
    recall_at_k,
    reciprocal_rank,
    score_retrieval,
)


def test_recall_at_k_full_credit_when_relevant_chunk_is_in_top_k() -> None:
    assert recall_at_k(["c1", "c2", "c3"], {"c2"}, k=3) == 1.0


def test_recall_at_k_zero_when_relevant_chunk_is_beyond_k() -> None:
    assert recall_at_k(["c1", "c2", "c3", "c4"], {"c4"}, k=2) == 0.0


def test_recall_at_k_is_a_fraction_for_multiple_relevant_ids() -> None:
    assert recall_at_k(["c1", "c2", "c3"], {"c1", "c99"}, k=3) == 0.5


def test_recall_at_k_zero_for_an_empty_relevant_set() -> None:
    assert recall_at_k(["c1", "c2"], set(), k=5) == 0.0


def test_reciprocal_rank_of_first_hit() -> None:
    assert reciprocal_rank(["c1", "c2", "c3"], {"c3"}) == 1.0 / 3


def test_reciprocal_rank_uses_the_first_relevant_hit_not_a_later_one() -> None:
    assert reciprocal_rank(["c1", "c2", "c3"], {"c2", "c3"}) == 1.0 / 2


def test_reciprocal_rank_zero_when_nothing_relevant_was_retrieved() -> None:
    assert reciprocal_rank(["c1", "c2"], {"c99"}) == 0.0


def test_score_retrieval_bundles_both_metrics() -> None:
    score = score_retrieval("q1", ["c1", "c2"], {"c2"}, k=5)
    assert score.question_id == "q1"
    assert score.recall_at_k == 1.0
    assert score.reciprocal_rank == 0.5


def test_mean_recall_and_mrr_average_across_questions() -> None:
    scores = [
        score_retrieval("q1", ["c1"], {"c1"}),  # recall 1.0, rr 1.0
        score_retrieval("q2", ["c2", "c3"], {"c3"}),  # recall 1.0, rr 0.5
        score_retrieval("q3", ["c9"], {"c-missing"}),  # recall 0.0, rr 0.0
    ]
    assert mean_recall_at_k(scores) == (1.0 + 1.0 + 0.0) / 3
    assert mean_reciprocal_rank(scores) == (1.0 + 0.5 + 0.0) / 3


def test_mean_functions_return_zero_for_an_empty_list() -> None:
    assert mean_recall_at_k([]) == 0.0
    assert mean_reciprocal_rank([]) == 0.0
