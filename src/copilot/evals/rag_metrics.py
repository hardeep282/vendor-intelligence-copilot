"""Retrieval metrics for the RAG golden set (Day 4 step 7): recall@5 and MRR.

Purpose : score a retriever's output against `copilot.evals.rag_golden`'s labelled relevant
          sets. Pure arithmetic, no LLM call -- these run for real in CI or this sandbox, with
          `FakeEmbedder`'s vectors or the real embedding model alike; only the *meaning* of the
          number depends on which embedder produced the ranking being scored (see
          `scripts/run_rag_eval.py`, which runs this against the real index on your machine).
Inputs  : a ranked list of retrieved chunk ids (best first) and the set of relevant chunk ids
          for one question.
Outputs : per-question scores (`RagRetrievalScore`) and the two aggregate numbers the sprint
          doc asks for, `mean_recall_at_k()` and `mean_reciprocal_rank()`.
"""

from __future__ import annotations

from pydantic import BaseModel

DEFAULT_K = 5


def recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int = DEFAULT_K) -> float:
    """Fraction of the relevant set found within the top k retrieved ids. 0.0 when there's
    nothing relevant to find (an empty `relevant_ids` is a labelling bug, not a perfect score).
    """
    if not relevant_ids:
        return 0.0
    found = set(retrieved_ids[:k]) & relevant_ids
    return len(found) / len(relevant_ids)


def reciprocal_rank(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    """1 / (rank of the first relevant id), rank starting at 1; 0.0 if none of the retrieved
    ids are relevant at all (ranked beyond the retrieved list, or genuinely not retrieved).
    """
    for rank, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in relevant_ids:
            return 1.0 / rank
    return 0.0


class RagRetrievalScore(BaseModel):
    question_id: str
    recall_at_k: float
    reciprocal_rank: float


def score_retrieval(
    question_id: str, retrieved_ids: list[str], relevant_ids: set[str], k: int = DEFAULT_K
) -> RagRetrievalScore:
    return RagRetrievalScore(
        question_id=question_id,
        recall_at_k=recall_at_k(retrieved_ids, relevant_ids, k),
        reciprocal_rank=reciprocal_rank(retrieved_ids, relevant_ids),
    )


def mean_recall_at_k(scores: list[RagRetrievalScore]) -> float:
    if not scores:
        return 0.0
    return sum(s.recall_at_k for s in scores) / len(scores)


def mean_reciprocal_rank(scores: list[RagRetrievalScore]) -> float:
    if not scores:
        return 0.0
    return sum(s.reciprocal_rank for s in scores) / len(scores)
