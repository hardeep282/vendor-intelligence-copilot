"""Chroma vector store with idempotent upserts.

Purpose : persist chunk embeddings so retrieval doesn't re-embed the whole corpus on every
          request, and so re-running the index build after a content edit only re-embeds what
          actually changed.
Inputs  : Chunk objects (copilot.rag.chunking) and an Embedder (copilot.rag.embeddings).
Outputs : a Chroma collection on disk (default: data/chroma/, gitignored -- same
          never-commit-derived-data posture as the data/snapshot/ Parquet files) queryable by
          vector similarity. Hybrid fusion with BM25 (step 4) and the permission filter
          (step 5) both build on top of the plain vector `query()` here.

Idempotency key: `content_hash`, not `chunk_id`. The property that actually matters is "the
same chunk text is embedded and stored exactly once, however many times the index build runs" --
keying on chunk_id alone would re-embed every chunk every run (wasted compute, and for an API
embedder, wasted money); keying on content_hash means an unchanged chunk is skipped even if the
whole corpus is rebuilt from scratch, while a chunk whose *text* changed under the same chunk_id
(an edited doc, same version number -- shouldn't happen here, but) is correctly re-embedded
rather than silently treated as unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence  # noqa: F401 -- used only inside string-quoted cast() types
from pathlib import Path
from typing import cast

import chromadb
from chromadb.api import ClientAPI
from pydantic import BaseModel

from copilot.guardrails.policy import DataClass, Role
from copilot.rag.chunking import Chunk
from copilot.rag.embeddings import Embedder
from copilot.settings import REPO_ROOT

DEFAULT_CHROMA_DIR = REPO_ROOT / "data" / "chroma"
DEFAULT_COLLECTION_NAME = "knowledge"
_HEADING_SEP = " > "  # heading_path join separator; chosen not to collide with real headings
_ROLE_SEP = "|"


class UpsertReport(BaseModel):
    total: int
    upserted: int  # new, or content_hash changed
    unchanged: int  # already stored under this chunk_id with the same content_hash


def get_chroma_client(path: Path = DEFAULT_CHROMA_DIR) -> ClientAPI:
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path))


def _to_metadata(chunk: Chunk) -> dict[str, str | int]:
    """Flatten a Chunk's fields to Chroma metadata (str/int/float/bool values only -- lists like
    allowed_roles and heading_path are joined into delimited strings and split back out in
    `_roles_from_metadata`/`_heading_path_from_metadata`).
    """
    return {
        "doc_type": chunk.doc_type,
        "vendor": chunk.vendor or "",
        "version": chunk.version,
        "data_class": chunk.data_class,
        "allowed_roles": _ROLE_SEP.join(chunk.allowed_roles),
        "heading_path": _HEADING_SEP.join(chunk.heading_path),
        "chunk_index": chunk.chunk_index,
        "content_hash": chunk.content_hash,
    }


def roles_from_metadata(metadata: dict[str, object]) -> tuple[Role, ...]:
    """Caller's responsibility: only ever call this on metadata this module itself wrote via
    `_to_metadata` -- the cast below trusts that, it does not re-validate it.
    """
    raw = cast(str, metadata.get("allowed_roles", ""))
    return cast(tuple[Role, ...], tuple(raw.split(_ROLE_SEP))) if raw else ()


def data_class_from_metadata(metadata: dict[str, object]) -> DataClass:
    """Same caller contract as `roles_from_metadata` above."""
    return cast(DataClass, metadata["data_class"])


class ChunkStore:
    """Thin wrapper over one Chroma collection of chunk embeddings."""

    def __init__(
        self, client: ClientAPI, collection_name: str = DEFAULT_COLLECTION_NAME
    ) -> None:
        # embedding_function=None: we always supply our own vectors (via Embedder), so Chroma
        # must never fall back to its default embedding function, which would both silently
        # change what gets stored and try to download a model of its own.
        self._collection = client.get_or_create_collection(
            collection_name,
            embedding_function=None,
            metadata={"hnsw:space": "cosine"},
        )

    def count(self) -> int:
        return self._collection.count()

    def upsert(self, chunks: list[Chunk], embedder: Embedder) -> UpsertReport:
        """Embed and store every chunk whose content_hash isn't already stored under its
        chunk_id; skip the rest. Returns a report of what happened, for the build script to
        print.
        """
        if not chunks:
            return UpsertReport(total=0, upserted=0, unchanged=0)

        ids = [c.chunk_id for c in chunks]
        existing = self._collection.get(ids=ids, include=["metadatas"])
        existing_metadatas = existing["metadatas"] or [{} for _ in existing["ids"]]
        existing_hash_by_id = {
            existing_id: metadata.get("content_hash")
            for existing_id, metadata in zip(existing["ids"], existing_metadatas, strict=True)
        }

        to_write = [c for c in chunks if existing_hash_by_id.get(c.chunk_id) != c.content_hash]
        if to_write:
            vectors = embedder.embed([c.text for c in to_write])
            self._collection.upsert(
                ids=[c.chunk_id for c in to_write],
                embeddings=cast("list[Sequence[float]]", vectors),
                documents=[c.text for c in to_write],
                metadatas=[_to_metadata(c) for c in to_write],
            )
        return UpsertReport(
            total=len(chunks), upserted=len(to_write), unchanged=len(chunks) - len(to_write)
        )

    def query(
        self, query_vector: list[float], n_results: int = 5
    ) -> list[tuple[str, str, dict[str, object], float]]:
        """Plain vector-similarity search: no permission filtering (step 5) and no BM25 fusion
        (step 4) -- both wrap this. Returns (chunk_id, text, metadata, distance) tuples, nearest
        first.
        """
        result = self._collection.query(
            query_embeddings=cast("list[Sequence[float]]", [query_vector]),
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
        ids = result["ids"][0]
        docs = result["documents"][0] if result["documents"] else [""] * len(ids)
        metadatas = result["metadatas"][0] if result["metadatas"] else [{}] * len(ids)
        distances = result["distances"][0] if result["distances"] else [0.0] * len(ids)
        return list(
            zip(ids, docs, cast("list[dict[str, object]]", metadatas), distances, strict=True)
        )
