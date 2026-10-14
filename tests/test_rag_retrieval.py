"""Tests for hybrid BM25 + vector retrieval (Day 4 step 4). Uses an in-memory Chroma client and
FakeEmbedder throughout, same posture as test_rag_store.py -- the real embedder/model only runs
on your machine.

FakeEmbedder is not semantically aware (see its docstring), so "vector search finds this chunk"
is only reliably controllable in these tests by making the query text exactly equal a chunk's
text (FakeEmbedder maps identical text to an identical vector, i.e. distance 0 -- the nearest
possible). That is used deliberately below to prove the one property that matters for this step:
a chunk with *zero lexical overlap* with the query (BM25 score 0, dropped entirely) can still be
retrieved because the vector ranking found it -- which is the whole reason this module fuses two
rankings instead of relying on BM25 alone.
"""

from __future__ import annotations

import uuid

import chromadb
import pytest

from copilot.rag.chunking import Chunk
from copilot.rag.embeddings import FakeEmbedder
from copilot.rag.retrieval import DEFAULT_RRF_K, BM25Index, HybridRetriever, reciprocal_rank_fusion
from copilot.rag.store import ChunkStore


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


# ---------------------------------------------------------------------------------------
# BM25Index
# ---------------------------------------------------------------------------------------


def test_bm25_ranks_more_overlapping_terms_higher() -> None:
    chunks = [
        _chunk("c1", "amber ale bottling schedule for diageo"),
        _chunk("c2", "amber ale tasting notes"),
        _chunk("c3", "unrelated contract clause about payment terms"),
    ]
    index = BM25Index(chunks)
    results = index.search("amber ale bottling schedule", n_results=10)
    ranked_ids = [chunk_id for chunk_id, _ in results]
    assert ranked_ids[0] == "c1"  # most term overlap
    assert "c3" not in ranked_ids  # zero overlap -> score 0 -> dropped, not just ranked last


def test_bm25_index_over_empty_corpus_returns_nothing() -> None:
    index = BM25Index([])
    assert index.search("anything", n_results=5) == []


def test_bm25_respects_n_results() -> None:
    # Each chunk's text must vary (not just by id) -- a term that appears in every single
    # document gives BM25's idf term a non-positive value, which the library floors near zero
    # and this module's `score > 0` filter then (correctly) drops as "no real match".
    chunks = [_chunk(f"c{i}", f"alpha bravo charlie filler-{i}") for i in range(10)]
    index = BM25Index(chunks)
    assert len(index.search("alpha bravo charlie", n_results=3)) == 3


# ---------------------------------------------------------------------------------------
# reciprocal_rank_fusion
# ---------------------------------------------------------------------------------------


def test_rrf_matches_the_formula_directly() -> None:
    rankings = [["a", "b", "c"], ["c", "a", "b"]]
    fused = reciprocal_rank_fusion(rankings, k=10)
    assert fused["a"] == pytest.approx(1 / 11 + 1 / 12)
    assert fused["b"] == pytest.approx(1 / 12 + 1 / 13)
    assert fused["c"] == pytest.approx(1 / 13 + 1 / 11)


def test_rrf_promotes_an_item_present_in_both_rankings() -> None:
    # "a" is rank 1 in the only ranking it appears in; "b" is only rank 2 in one ranking and
    # rank 1 in the other, but appears in both. RRF should still favour "b" -- this is the
    # whole point of fusing two signals instead of trusting either one alone.
    rankings = [["a", "b"], ["b"]]
    fused = reciprocal_rank_fusion(rankings)
    assert fused["b"] > fused["a"]


def test_rrf_default_k_is_60() -> None:
    assert DEFAULT_RRF_K == 60


def test_rrf_item_missing_from_a_ranking_gets_no_penalty_only_no_credit() -> None:
    only_in_one = reciprocal_rank_fusion([["x"]])
    also_fused = reciprocal_rank_fusion([["x"], ["y", "z"]])
    assert only_in_one["x"] == also_fused["x"]  # "x"'s own contribution is unaffected


# ---------------------------------------------------------------------------------------
# HybridRetriever
# ---------------------------------------------------------------------------------------


@pytest.fixture
def populated_store() -> tuple[ChunkStore, list[Chunk]]:
    client = chromadb.EphemeralClient()
    store = ChunkStore(client, collection_name=f"test-{uuid.uuid4().hex}")
    chunks = [
        _chunk("c-lexical", "amber ale bottling schedule for diageo vendor code 4471"),
        _chunk("c-vector-exact", "a payment clause with no shared vocabulary whatsoever"),
        _chunk("c-noise-1", "quarterly volume rebate tier definitions"),
        _chunk("c-noise-2", "cold chain logistics temperature excursion policy"),
    ]
    store.upsert(chunks, FakeEmbedder())
    return store, chunks


def test_retrieve_surfaces_a_pure_vector_match_bm25_alone_would_miss(
    populated_store: tuple[ChunkStore, list[Chunk]],
) -> None:
    store, chunks = populated_store
    retriever = HybridRetriever(chunks, store, FakeEmbedder())

    # Query text exactly equals c-vector-exact's text, so FakeEmbedder gives it distance 0 (the
    # nearest possible vector match). It shares zero tokens with the query's own text is moot --
    # the point is it shares nothing with the *other* chunks, so BM25 alone (given a different,
    # unrelated query) would never surface it; here it surfaces purely via the vector ranking.
    query = "a payment clause with no shared vocabulary whatsoever"
    results = retriever.retrieve(query, n_results=4)

    top = results[0]
    assert top.chunk.chunk_id == "c-vector-exact"
    assert top.vector_rank == 1


def test_retrieve_surfaces_a_strong_lexical_match(
    populated_store: tuple[ChunkStore, list[Chunk]],
) -> None:
    store, chunks = populated_store
    retriever = HybridRetriever(chunks, store, FakeEmbedder())

    results = retriever.retrieve("amber ale bottling schedule diageo", n_results=4)
    ids = [r.chunk.chunk_id for r in results]
    assert "c-lexical" in ids
    lexical_hit = next(r for r in results if r.chunk.chunk_id == "c-lexical")
    assert lexical_hit.bm25_rank == 1


def test_retrieve_respects_n_results(populated_store: tuple[ChunkStore, list[Chunk]]) -> None:
    store, chunks = populated_store
    retriever = HybridRetriever(chunks, store, FakeEmbedder())
    results = retriever.retrieve("amber ale bottling", n_results=2)
    assert len(results) == 2


def test_retrieve_is_deterministic(populated_store: tuple[ChunkStore, list[Chunk]]) -> None:
    store, chunks = populated_store
    retriever = HybridRetriever(chunks, store, FakeEmbedder())
    first = retriever.retrieve("amber ale bottling", n_results=3)
    second = retriever.retrieve("amber ale bottling", n_results=3)
    assert [r.chunk.chunk_id for r in first] == [r.chunk.chunk_id for r in second]


def test_retrieve_over_empty_chunk_list_returns_nothing() -> None:
    client = chromadb.EphemeralClient()
    store = ChunkStore(client, collection_name=f"test-{uuid.uuid4().hex}")
    retriever = HybridRetriever([], store, FakeEmbedder())
    assert retriever.retrieve("anything", n_results=5) == []
