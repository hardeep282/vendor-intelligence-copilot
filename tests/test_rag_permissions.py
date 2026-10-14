"""Tests for the permission filter inside the vector query (Day 4 step 5). Uses the real,
live `load_policy()` (same convention as tests/test_guard_and_policy.py) rather than a fake
policy object -- this module's whole point is deferring to the live policy, so testing against
a stand-in policy would prove nothing about the real disclosure boundary.
"""

from __future__ import annotations

import uuid

import chromadb
import pytest

from copilot.guardrails.policy import DisclosurePolicy, load_policy
from copilot.rag.chunking import Chunk
from copilot.rag.embeddings import FakeEmbedder
from copilot.rag.permissions import PermissionedRetriever
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


@pytest.fixture
def policy() -> DisclosurePolicy:
    return load_policy()


@pytest.fixture
def mixed_chunks() -> list[Chunk]:
    # Same lexical content across all three so a query matches all of them equally -- any
    # difference in what comes back is down to the permission filter, not term overlap.
    return [
        _chunk("c-public", "vendor code 4471 bottling schedule", data_class="public"),
        _chunk("c-internal", "vendor code 4471 bottling schedule", data_class="internal"),
        _chunk("c-confidential", "vendor code 4471 bottling schedule", data_class="confidential"),
    ]


@pytest.fixture
def mixed_store(mixed_chunks: list[Chunk]) -> ChunkStore:
    client = chromadb.EphemeralClient()
    store = ChunkStore(client, collection_name=f"test-{uuid.uuid4().hex}")
    store.upsert(mixed_chunks, FakeEmbedder())
    return store


@pytest.mark.parametrize(
    ("role", "expected_classes"),
    [
        ("anonymous", {"public"}),
        ("viewer", {"public", "internal"}),
        ("analyst", {"public", "internal", "confidential"}),
        ("approver", {"public", "internal", "confidential"}),
        ("admin", {"public", "internal", "confidential"}),
    ],
)
def test_retrieve_only_returns_classes_the_role_may_see(
    mixed_chunks: list[Chunk],
    mixed_store: ChunkStore,
    policy: DisclosurePolicy,
    role: str,
    expected_classes: set[str],
) -> None:
    retriever = PermissionedRetriever(mixed_chunks, mixed_store, FakeEmbedder(), policy)
    results = retriever.retrieve("vendor code 4471 bottling schedule", role, n_results=10)  # type: ignore[arg-type]
    got_classes = {r.chunk.data_class for r in results}
    assert got_classes == expected_classes
    assert "restricted" not in got_classes  # nobody may read restricted, per the policy itself


def test_vector_filter_is_pushed_into_the_query_not_applied_after_the_fact(
    policy: DisclosurePolicy,
) -> None:
    # Five confidential chunks plus one public chunk, all sharing the same text. A small
    # candidate_pool (1) means a post-hoc filter (retrieve top 1, then drop what's ineligible)
    # would very likely retrieve a confidential chunk and have nothing left for "anonymous" --
    # exactly the under-fill bug this step exists to avoid. Pushing the filter into the Chroma
    # `where` clause means the ANN search only ever considers the public chunk for this role, so
    # it is always found regardless of pool size.
    chunks = [
        _chunk(f"c-confidential-{i}", "settlement terms clause", data_class="confidential")
        for i in range(5)
    ] + [_chunk("c-public", "settlement terms clause", data_class="public")]
    client = chromadb.EphemeralClient()
    store = ChunkStore(client, collection_name=f"test-{uuid.uuid4().hex}")
    store.upsert(chunks, FakeEmbedder())

    retriever = PermissionedRetriever(chunks, store, FakeEmbedder(), policy)
    results = retriever.retrieve(
        "settlement terms clause", "anonymous", n_results=1, candidate_pool=1
    )

    assert len(results) == 1
    assert results[0].chunk.chunk_id == "c-public"


def test_bm25_side_excludes_ineligible_chunks_from_the_index_itself(
    policy: DisclosurePolicy,
) -> None:
    # "zephyrcode9981" appears in exactly one chunk, which is confidential. A viewer querying
    # for that exact term should get nothing back for it -- not a low-ranked hit, nothing at
    # all -- because the role-scoped BM25 index never had that chunk in it to begin with.
    chunks = [
        _chunk(
            "c-confidential",
            "the zephyrcode9981 clause governs early termination",
            data_class="confidential",
        ),
        _chunk("c-public", "general methodology notes", data_class="public"),
    ]
    client = chromadb.EphemeralClient()
    store = ChunkStore(client, collection_name=f"test-{uuid.uuid4().hex}")
    store.upsert(chunks, FakeEmbedder())

    retriever = PermissionedRetriever(chunks, store, FakeEmbedder(), policy)
    results = retriever.retrieve("zephyrcode9981", "viewer", n_results=5)

    assert all(r.chunk.chunk_id != "c-confidential" for r in results)


def test_retrieve_respects_n_results(
    mixed_chunks: list[Chunk], mixed_store: ChunkStore, policy: DisclosurePolicy
) -> None:
    retriever = PermissionedRetriever(mixed_chunks, mixed_store, FakeEmbedder(), policy)
    results = retriever.retrieve("vendor code 4471 bottling schedule", "analyst", n_results=2)
    assert len(results) == 2


def test_retrieve_with_nothing_visible_returns_empty(policy: DisclosurePolicy) -> None:
    chunks = [_chunk("c-confidential", "contract clause", data_class="confidential")]
    client = chromadb.EphemeralClient()
    store = ChunkStore(client, collection_name=f"test-{uuid.uuid4().hex}")
    store.upsert(chunks, FakeEmbedder())

    retriever = PermissionedRetriever(chunks, store, FakeEmbedder(), policy)
    assert retriever.retrieve("contract clause", "anonymous", n_results=5) == []


def test_nobody_can_retrieve_restricted_even_if_a_chunk_were_tagged_that_way(
    policy: DisclosurePolicy,
) -> None:
    # Defensive case: the real corpus never produces a restricted chunk (DisclosurePolicy itself
    # forbids any role from being granted it), but this proves the filter enforces that
    # independently rather than happening to work only because the corpus is well-behaved.
    chunks = [_chunk("c-restricted", "raw licensed row data", data_class="restricted")]
    client = chromadb.EphemeralClient()
    store = ChunkStore(client, collection_name=f"test-{uuid.uuid4().hex}")
    store.upsert(chunks, FakeEmbedder())

    retriever = PermissionedRetriever(chunks, store, FakeEmbedder(), policy)
    assert retriever.retrieve("raw licensed row data", "admin", n_results=5) == []
