"""Tests for the Corrective RAG loop (Day 4 step 6). No network and no API key, same convention
as tests/test_sql_service.py and tests/test_insight_service.py: the LLM side is
FakeMessagesResource, queued in the exact order the graph is expected to call it in, and the
retrieval side is a minimal stub implementing `copilot.rag.corrective.Retriever`'s one method
-- this module's own tests (test_rag_retrieval.py, test_rag_permissions.py) already cover
retrieval and permission filtering in depth, so there's no value re-exercising Chroma/BM25 here.
"""

from __future__ import annotations

from copilot.guardrails.policy import Role
from copilot.llm.client import LLMClient
from copilot.rag.chunking import Chunk
from copilot.rag.corrective import MAX_CORRECTIONS, CorrectiveRagService
from copilot.rag.retrieval import RetrievedChunk
from tests.fakes.anthropic_fakes import FakeMessagesResource, structured_response


def _chunk(chunk_id: str, text: str, **overrides: object) -> Chunk:
    defaults: dict[str, object] = {
        "chunk_id": chunk_id,
        "doc_type": "methodology",
        "vendor": None,
        "version": 1,
        "data_class": "public",
        "allowed_roles": ("viewer", "analyst"),
        "heading_path": ("Title", "Section"),
        "chunk_index": 0,
        "text": text,
        "content_hash": f"hash-of-{text}",
    }
    defaults.update(overrides)
    return Chunk(**defaults)  # type: ignore[arg-type]


def _retrieved(chunk: Chunk) -> RetrievedChunk:
    return RetrievedChunk(chunk=chunk, rrf_score=1.0, bm25_rank=1, vector_rank=1)


class _StubRetriever:
    """Returns a pre-programmed result per query text; records every call it saw."""

    def __init__(self, by_query: dict[str, list[RetrievedChunk]]) -> None:
        self._by_query = by_query
        self.calls: list[tuple[str, Role]] = []

    def retrieve(
        self, query: str, role: Role, n_results: int = 5, candidate_pool: int = 20
    ) -> list[RetrievedChunk]:
        self.calls.append((query, role))
        return self._by_query.get(query, [])


def _llm_with(responses: list[object]) -> LLMClient:
    llm = LLMClient(api_key="sk-test-not-real")
    llm._client.messages = FakeMessagesResource(responses)  # type: ignore[attr-defined]
    return llm


def test_answers_directly_when_the_first_retrieval_grades_relevant() -> None:
    c1 = _chunk("c1", "DIAGEO's standard payment terms are net 30 days.")
    retriever = _StubRetriever({"what are diageo's payment terms?": [_retrieved(c1)]})
    llm = _llm_with(
        [
            structured_response({"grades": [{"chunk_id": "c1", "relevant": True}]}),
            structured_response({"answer": "Net 30 days.", "cited_chunk_ids": ["c1"]}),
        ]
    )
    service = CorrectiveRagService(llm, retriever)

    result = service.answer("what are diageo's payment terms?", "analyst")

    assert result.abstained is False
    assert result.answer == "Net 30 days."
    assert result.cited_chunk_ids == ["c1"]
    assert result.corrections == 0
    assert result.llm_calls == 2
    assert retriever.calls == [("what are diageo's payment terms?", "analyst")]


def test_rewrites_once_then_succeeds_on_the_better_query() -> None:
    c_irrelevant = _chunk("c-irrelevant", "cold chain logistics temperature excursion policy")
    c_relevant = _chunk("c-relevant", "settlement window for vendor code 4471 is 45 days")
    retriever = _StubRetriever(
        {
            "original question": [_retrieved(c_irrelevant)],
            "rewritten query": [_retrieved(c_relevant)],
        }
    )
    llm = _llm_with(
        [
            structured_response({"grades": [{"chunk_id": "c-irrelevant", "relevant": False}]}),
            structured_response({"rewritten_query": "rewritten query", "reasoning": "broadened"}),
            structured_response({"grades": [{"chunk_id": "c-relevant", "relevant": True}]}),
            structured_response({"answer": "45 days.", "cited_chunk_ids": ["c-relevant"]}),
        ]
    )
    service = CorrectiveRagService(llm, retriever)

    result = service.answer("original question", "viewer")

    assert result.abstained is False
    assert result.answer == "45 days."
    assert result.corrections == 1
    assert result.rewritten_queries == ["rewritten query"]
    assert result.llm_calls == 4
    assert [q for q, _role in retriever.calls] == ["original question", "rewritten query"]


def test_abstains_after_exhausting_the_retry_budget() -> None:
    c1 = _chunk("c1", "always irrelevant text")
    retriever = _StubRetriever(
        {
            "q": [_retrieved(c1)],
            "r1": [_retrieved(c1)],
            "r2": [_retrieved(c1)],
        }
    )
    llm = _llm_with(
        [
            structured_response({"grades": [{"chunk_id": "c1", "relevant": False}]}),
            structured_response({"rewritten_query": "r1", "reasoning": "x"}),
            structured_response({"grades": [{"chunk_id": "c1", "relevant": False}]}),
            structured_response({"rewritten_query": "r2", "reasoning": "x"}),
            structured_response({"grades": [{"chunk_id": "c1", "relevant": False}]}),
        ]
    )
    service = CorrectiveRagService(llm, retriever)

    result = service.answer("q", "analyst")

    assert result.abstained is True
    assert result.answer is None
    assert result.corrections == MAX_CORRECTIONS
    assert result.llm_calls == 5
    assert result.abstain_reason is not None


def test_abstains_without_an_llm_call_to_grade_when_nothing_is_ever_retrieved() -> None:
    # The retriever returns nothing for every query the loop ever tries -- grading an empty
    # list would waste an LLM call on a list with nothing in it, so the grade step must skip it.
    retriever = _StubRetriever({})
    llm = _llm_with(
        [
            structured_response({"rewritten_query": "r1", "reasoning": "x"}),
            structured_response({"rewritten_query": "r2", "reasoning": "x"}),
        ]
    )
    service = CorrectiveRagService(llm, retriever)

    result = service.answer("q", "viewer")

    assert result.abstained is True
    assert result.llm_calls == 2  # two rewrites, zero grade calls
    assert len(retriever.calls) == 3  # original + 2 rewritten queries


def test_never_cites_a_chunk_id_the_model_was_not_actually_shown() -> None:
    c1 = _chunk("c1", "the only chunk actually shown")
    retriever = _StubRetriever({"q": [_retrieved(c1)]})
    llm = _llm_with(
        [
            structured_response({"grades": [{"chunk_id": "c1", "relevant": True}]}),
            structured_response(
                {"answer": "An answer.", "cited_chunk_ids": ["c1", "c-never-shown"]}
            ),
        ]
    )
    service = CorrectiveRagService(llm, retriever)

    result = service.answer("q", "analyst")

    assert result.cited_chunk_ids == ["c1"]


def test_ignores_a_grade_for_a_chunk_id_outside_the_retrieved_set() -> None:
    # A grade naming an id that wasn't retrieved can't be a real judgement of real text --
    # must not count towards MIN_RELEVANT_CHUNKS or let the loop skip straight to generate.
    c1 = _chunk("c1", "real retrieved text")
    retriever = _StubRetriever({"q": [_retrieved(c1)], "rewritten": [_retrieved(c1)]})
    llm = _llm_with(
        [
            structured_response({"grades": [{"chunk_id": "c-not-retrieved", "relevant": True}]}),
            structured_response({"rewritten_query": "rewritten", "reasoning": "x"}),
            structured_response({"grades": [{"chunk_id": "c1", "relevant": True}]}),
            structured_response({"answer": "ok", "cited_chunk_ids": ["c1"]}),
        ]
    )
    service = CorrectiveRagService(llm, retriever)

    result = service.answer("q", "analyst")

    assert result.abstained is False
    assert result.corrections == 1  # had to rewrite once -- the bogus grade didn't count
