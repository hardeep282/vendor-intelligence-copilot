"""Tests for the RAG golden set loader and relevance resolver (Day 4 step 7)."""

from __future__ import annotations

from copilot.evals.rag_golden import load_rag_golden, relevant_chunk_ids
from copilot.rag.chunking import chunk_corpus
from copilot.rag.corpus import load_corpus


def test_loads_twenty_questions() -> None:
    questions = load_rag_golden()
    assert len(questions) == 20
    assert len({q.id for q in questions}) == 20  # ids are unique


def test_every_question_s_role_may_see_its_own_data_class() -> None:
    # This dataset measures retrieval quality, not permission correctness (see module
    # docstring) -- every question's role must already be allowed to see its data_class, or a
    # low score here would be ambiguous between "bad ranking" and "role can't see this anyway."
    from copilot.guardrails.policy import load_policy

    policy = load_policy()
    for q in load_rag_golden():
        assert policy.can_view(q.role, q.data_class), f"{q.id}: {q.role} can't view {q.data_class}"


def test_every_question_resolves_to_exactly_one_chunk_against_the_real_corpus() -> None:
    chunks = chunk_corpus(load_corpus())
    for q in load_rag_golden():
        resolved = relevant_chunk_ids(q, chunks)
        assert len(resolved) == 1, f"{q.id} resolved to {len(resolved)} chunks, expected 1"


def test_relevant_chunk_ids_respects_doc_type_and_vendor_filters() -> None:
    chunks = chunk_corpus(load_corpus())
    questions = {q.id: q for q in load_rag_golden()}

    diageo_question = questions["q01"]
    resolved = relevant_chunk_ids(diageo_question, chunks)
    (chunk_id,) = resolved
    resolved_chunk = next(c for c in chunks if c.chunk_id == chunk_id)
    assert resolved_chunk.doc_type == "vendor_contract"
    assert resolved_chunk.vendor == "DIAGEO NORTH AMERICA INC"


def test_relevant_chunk_ids_is_case_insensitive() -> None:
    chunks = chunk_corpus(load_corpus())
    q = next(q for q in load_rag_golden() if q.id == "q11")
    lowered = q.model_copy(update={"must_contain": q.must_contain.upper()})
    assert relevant_chunk_ids(q, chunks) == relevant_chunk_ids(lowered, chunks)
