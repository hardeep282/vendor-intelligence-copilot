"""Embedders for the RAG store.

Purpose : turn chunk text into vectors. The project's chosen embedder is a local
          sentence-transformers model -- no API key, no per-call cost, runs on CPU, and keeps
          embeddings reproducible offline once the model is cached (contrast with an API
          embedder, whose vectors depend on a provider that can change the model under you).
Inputs  : chunk text (or a query string, at retrieval time).
Outputs : a list of float vectors, one per input text, each of length `Embedder.dimension`.

Why there are two implementations: this build sandbox's proxy allowlist does not include
huggingface.co (confirmed by trying -- the same restriction Day 3 hit when `tiktoken` and the
Hugging Face tokenizer tried to download their vocab files). `SentenceTransformerEmbedder`'s
model weights are pulled from the Hub on first use, so like the Day 3 tokenization and effort
labs, the real embedding run happens on your machine: `scripts/build_rag_index.py`. Every test
in this repo uses `FakeEmbedder` instead -- deterministic, dependency-free, no network -- to
exercise the store and retrieval logic without needing the real model at all.
"""

from __future__ import annotations

import hashlib
import struct
from typing import Protocol, runtime_checkable

DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_MODEL_DIMENSION = 384


@runtime_checkable
class Embedder(Protocol):
    """The only interface the rest of copilot.rag depends on."""

    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order, each of length `dimension`."""
        ...


class SentenceTransformerEmbedder:
    """Local sentence-transformers embedder. The model is loaded lazily, on first `embed()`
    call, not in `__init__` -- so constructing this object (e.g. while wiring up the app) never
    triggers a download by itself, only actually embedding something does.
    """

    def __init__(
        self, model_name: str = DEFAULT_MODEL_NAME, dimension: int = DEFAULT_MODEL_DIMENSION
    ) -> None:
        self.model_name = model_name
        self.dimension = dimension
        self._model: object | None = None

    def _load(self) -> object:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # local import, see docstring

            self._model = SentenceTransformer(self.model_name)
            loaded_dim = self._model.get_sentence_embedding_dimension()
            if loaded_dim != self.dimension:
                raise ValueError(
                    f"{self.model_name} embeds at dimension {loaded_dim}, "
                    f"but this embedder was constructed with dimension={self.dimension}"
                )
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(texts, normalize_embeddings=True)  # type: ignore[attr-defined]
        return [[float(x) for x in row] for row in vectors]


class FakeEmbedder:
    """Deterministic, offline stand-in for tests: a normalised pseudo-random unit vector derived
    from each text's sha256 hash. Not a real embedding -- semantically similar texts are not
    nearby in this space -- but same text always maps to the same vector, which is everything
    the store and upsert-idempotency logic need from an embedder to be tested without network
    access or the real dependency installed.
    """

    def __init__(self, dimension: int = 8) -> None:
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        needed = self.dimension * 4  # 4 bytes per float
        stream = (digest * (needed // len(digest) + 1))[:needed]
        raw = [v / 2**31 - 1.0 for v in struct.unpack(f"<{self.dimension}I", stream)]
        norm = sum(v * v for v in raw) ** 0.5 or 1.0
        return [v / norm for v in raw]
