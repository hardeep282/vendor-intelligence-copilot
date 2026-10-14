"""Build (or incrementally update) the RAG vector index from knowledge/.

Purpose : load the knowledge corpus, chunk it, embed every chunk with the real local
          sentence-transformers model, and upsert into a persistent Chroma collection at
          data/chroma/ -- idempotently, so re-running this after editing one knowledge doc only
          re-embeds the chunks that actually changed.
Run     : uv run python scripts/build_rag_index.py
          (first run downloads the model, ~90MB, from the Hugging Face Hub -- this build
          sandbox's proxy blocks huggingface.co, so this script is one of the "run on your
          machine" scripts, same pattern as Day 3's effort/tokenization labs. No API key is
          needed -- the model is local and free to run -- just normal internet access.)
"""

from __future__ import annotations

import time

from copilot.rag.chunking import chunk_corpus
from copilot.rag.corpus import check_corpus_against_policy, load_corpus
from copilot.rag.embeddings import SentenceTransformerEmbedder
from copilot.rag.store import ChunkStore, get_chroma_client


def main() -> None:
    print("Loading knowledge corpus from knowledge/ ...")
    docs = load_corpus()
    check_corpus_against_policy(docs)  # fails loudly if a doc's roles have drifted from policy
    print(f"  {len(docs)} documents loaded and checked against policies/disclosure.yaml.")

    print("Chunking ...")
    chunks = chunk_corpus(docs)
    print(f"  {len(chunks)} chunks.")

    print(f"Loading embedder ({SentenceTransformerEmbedder().model_name}) ...")
    print("  (first run downloads the model from the Hugging Face Hub -- can take a minute)")
    embedder = SentenceTransformerEmbedder()

    client = get_chroma_client()
    store = ChunkStore(client)

    print("Embedding and upserting ...")
    start = time.monotonic()
    report = store.upsert(chunks, embedder)
    elapsed = time.monotonic() - start

    print(
        f"Done in {elapsed:.1f}s: {report.upserted} embedded and written, "
        f"{report.unchanged} already up to date, {report.total} total chunks. "
        f"Collection now has {store.count()} chunks."
    )


if __name__ == "__main__":
    main()
