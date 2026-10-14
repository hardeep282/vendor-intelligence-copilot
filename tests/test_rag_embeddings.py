"""Tests for the embedder interface (Day 4 step 3). Uses only FakeEmbedder -- no network, no
sentence-transformers model download. SentenceTransformerEmbedder's lazy-load path is exercised
only by its dimension-mismatch guard, which raises before any network call would happen.
"""

import math

import pytest

from copilot.rag.embeddings import DEFAULT_MODEL_DIMENSION, Embedder, FakeEmbedder


def test_fake_embedder_satisfies_embedder_protocol() -> None:
    embedder: Embedder = FakeEmbedder()
    assert isinstance(embedder, Embedder)


def test_fake_embedder_is_deterministic() -> None:
    embedder = FakeEmbedder()
    v1 = embedder.embed(["hello world"])
    v2 = embedder.embed(["hello world"])
    assert v1 == v2


def test_fake_embedder_different_text_different_vector() -> None:
    embedder = FakeEmbedder()
    v1, v2 = embedder.embed(["hello", "goodbye"])
    assert v1 != v2


def test_fake_embedder_respects_dimension() -> None:
    embedder = FakeEmbedder(dimension=16)
    (vector,) = embedder.embed(["anything"])
    assert len(vector) == 16


def test_fake_embedder_vectors_are_unit_norm() -> None:
    embedder = FakeEmbedder()
    (vector,) = embedder.embed(["normalise me"])
    norm = math.sqrt(sum(x * x for x in vector))
    assert norm == pytest.approx(1.0, abs=1e-6)


def test_fake_embedder_preserves_input_order() -> None:
    embedder = FakeEmbedder()
    texts = ["a", "b", "c"]
    vectors = embedder.embed(texts)
    for text, vector in zip(texts, vectors, strict=True):
        assert embedder.embed([text])[0] == vector


def test_sentence_transformer_embedder_does_not_load_model_on_construction() -> None:
    # Constructing must never trigger a download by itself -- only calling embed() should.
    from copilot.rag.embeddings import SentenceTransformerEmbedder

    embedder = SentenceTransformerEmbedder()
    assert embedder._model is None


def test_sentence_transformer_embedder_rejects_dimension_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    from copilot.rag.embeddings import SentenceTransformerEmbedder

    class _FakeModel:
        def get_sentence_embedding_dimension(self) -> int:
            return DEFAULT_MODEL_DIMENSION + 1  # deliberately wrong

        def encode(self, texts: list[str], normalize_embeddings: bool = True) -> list[list[float]]:
            return [[0.0] * (DEFAULT_MODEL_DIMENSION + 1) for _ in texts]

    # Inject a fake `sentence_transformers` module so the mismatch guard is exercised without
    # ever reaching the network (this build sandbox's proxy blocks huggingface.co -- see the
    # module docstring).
    fake_module = types.ModuleType("sentence_transformers")
    fake_module.SentenceTransformer = lambda name: _FakeModel()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    embedder = SentenceTransformerEmbedder(dimension=DEFAULT_MODEL_DIMENSION)
    with pytest.raises(ValueError, match="dimension"):
        embedder.embed(["anything"])
