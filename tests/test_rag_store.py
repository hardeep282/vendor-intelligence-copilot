"""Tests for the Chroma chunk store (Day 4 step 3). Uses an in-memory Chroma client (no disk,
no network) and FakeEmbedder throughout -- the real SentenceTransformerEmbedder + persistent
on-disk store is scripts/build_rag_index.py, run on your machine.
"""

from __future__ import annotations

import uuid

import chromadb
import pytest

from copilot.rag.chunking import Chunk
from copilot.rag.embeddings import FakeEmbedder
from copilot.rag.store import ChunkStore, data_class_from_metadata, roles_from_metadata


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
def store() -> ChunkStore:
    # EphemeralClient's backing storage is process-wide, keyed by collection name -- not
    # isolated per client instance -- so each test gets its own unique collection name to avoid
    # seeing another test's chunks.
    client = chromadb.EphemeralClient()
    return ChunkStore(client, collection_name=f"test-{uuid.uuid4().hex}")


def test_upsert_stores_new_chunks(store: ChunkStore) -> None:
    chunks = [_chunk("c1", "alpha"), _chunk("c2", "beta")]
    report = store.upsert(chunks, FakeEmbedder())
    assert report.total == 2
    assert report.upserted == 2
    assert report.unchanged == 0
    assert store.count() == 2


def test_upsert_is_idempotent_for_unchanged_content(store: ChunkStore) -> None:
    chunks = [_chunk("c1", "alpha")]
    store.upsert(chunks, FakeEmbedder())
    report = store.upsert(chunks, FakeEmbedder())
    assert report.upserted == 0
    assert report.unchanged == 1
    assert store.count() == 1


def test_upsert_re_embeds_when_content_hash_changes(store: ChunkStore) -> None:
    store.upsert([_chunk("c1", "alpha", content_hash="hash-v1")], FakeEmbedder())
    report = store.upsert([_chunk("c1", "alpha-edited", content_hash="hash-v2")], FakeEmbedder())
    assert report.upserted == 1
    assert report.unchanged == 0
    assert store.count() == 1  # same chunk_id, so this is an update not a new row


def test_upsert_mixed_batch_only_re_embeds_the_changed_ones(store: ChunkStore) -> None:
    store.upsert(
        [_chunk("c1", "alpha", content_hash="h1"), _chunk("c2", "beta", content_hash="h2")],
        FakeEmbedder(),
    )
    report = store.upsert(
        [
            _chunk("c1", "alpha", content_hash="h1"),  # unchanged
            _chunk("c2", "beta-edited", content_hash="h2-new"),  # changed
            _chunk("c3", "gamma", content_hash="h3"),  # new
        ],
        FakeEmbedder(),
    )
    assert report.total == 3
    assert report.upserted == 2  # c2 (changed) + c3 (new)
    assert report.unchanged == 1  # c1


def test_upsert_empty_list_is_a_no_op(store: ChunkStore) -> None:
    report = store.upsert([], FakeEmbedder())
    assert report == store.upsert([], FakeEmbedder())
    assert report.total == 0
    assert store.count() == 0


def test_query_returns_nearest_first(store: ChunkStore) -> None:
    embedder = FakeEmbedder()
    chunks = [_chunk("c1", "alpha"), _chunk("c2", "beta"), _chunk("c3", "gamma")]
    store.upsert(chunks, embedder)

    (query_vector,) = embedder.embed(["alpha"])
    results = store.query(query_vector, n_results=3)

    assert results[0][0] == "c1"  # exact match should be nearest
    assert len(results) == 3


def test_query_respects_n_results(store: ChunkStore) -> None:
    embedder = FakeEmbedder()
    store.upsert([_chunk(f"c{i}", f"text {i}") for i in range(5)], embedder)
    (query_vector,) = embedder.embed(["text 0"])
    results = store.query(query_vector, n_results=2)
    assert len(results) == 2


def test_stored_metadata_round_trips_roles_and_data_class(store: ChunkStore) -> None:
    chunk = _chunk(
        "c1",
        "confidential text",
        data_class="confidential",
        allowed_roles=("analyst", "approver", "admin"),
    )
    embedder = FakeEmbedder()
    store.upsert([chunk], embedder)

    (query_vector,) = embedder.embed(["confidential text"])
    ((_id, _text, metadata, _distance),) = store.query(query_vector, n_results=1)

    assert data_class_from_metadata(metadata) == "confidential"
    assert roles_from_metadata(metadata) == ("analyst", "approver", "admin")


def test_two_stores_on_separate_collections_do_not_interfere() -> None:
    client = chromadb.EphemeralClient()
    suffix = uuid.uuid4().hex
    store_a = ChunkStore(client, collection_name=f"store-a-{suffix}")
    store_b = ChunkStore(client, collection_name=f"store-b-{suffix}")
    store_a.upsert([_chunk("c1", "alpha")], FakeEmbedder())
    assert store_a.count() == 1
    assert store_b.count() == 0
