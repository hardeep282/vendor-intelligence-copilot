"""Hybrid retrieval: BM25 (lexical) + vector search, fused with Reciprocal Rank Fusion.

Purpose : neither signal alone is reliable for this corpus. Vector search catches paraphrase
          and synonymy ("payment terms" vs. "settlement window") but misses exact identifiers
          that matter here -- a vendor code, a clause number, a specific dollar figure, a
          contract's version tag -- because those tokens rarely sit near each other in
          embedding space the way their *meaning* would suggest. BM25 catches exact-term hits
          but misses paraphrase entirely. Fusing both rankings is the standard fix, and RRF
          (Cormack, Clarke & Buettcher, 2009, "Reciprocal Rank Fusion outperforms Condorcet and
          individual Rank Learning Methods") is the standard fusion method: it combines *rank*
          rather than raw scores, so it needs no score normalisation between BM25's unbounded
          term-frequency scores and Chroma's cosine distances, which live on entirely different
          scales and would otherwise have to be calibrated against each other first.
Inputs  : a fixed list of Chunk (copilot.rag.chunking) to index for BM25, a ChunkStore
          (copilot.rag.store) already populated with the same chunks' vectors, and an Embedder
          (copilot.rag.embeddings) to embed the query text at retrieval time.
Outputs : a ranked list of RetrievedChunk, each carrying the fused RRF score and which of the
          two underlying rankings it came from (for debugging retrieval quality).

Cut from this step (see docs/PROJECT_PROGRESS.md, Day 4 step 4): a cross-encoder reranker on
top of the fused candidates. A reranker is a real quality lever (it scores the actual
query-chunk pair instead of relying on two independently-computed rankings), but it is also a
second model to download, load and run per query, and this step's job is specifically to prove
the fusion mechanics -- BM25 index, RRF math, candidate pool sizing -- are correct first. It can
be added later as a third stage after `retrieve()` without changing this module's contract:
RetrievedChunk already carries the chunk's full text, which is all a reranker needs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from copilot.rag.chunking import Chunk
from copilot.rag.embeddings import Embedder
from copilot.rag.store import ChunkStore

# RRF's smoothing constant. 60 is the value Cormack et al. used and the value most hybrid-search
# writeups since have kept as a default; it discounts how much a #1-vs-#2 rank difference matters
# at the top of a long ranking without needing a corpus-specific tune. Not treated as an ADR-level
# decision -- it is the standard default, not a build-vs-buy choice with real alternatives measured
# against it, same posture as the embedding model and vector store (see docs/COMMANDS.md Day 4).
DEFAULT_RRF_K = 60

# How many hits each underlying ranking contributes before fusion. Wider than `n_results` on
# purpose: RRF can only promote a chunk that appears in at least one input ranking, so a chunk
# that BM25 ranks #18 (a weak lexical match) but vector search ranks #2 (a strong semantic match)
# needs BM25's pool to reach at least 18 to be considered for fusion at all.
DEFAULT_CANDIDATE_POOL = 20

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Lowercase, alphanumeric-run tokenizer. Good enough for BM25 over this corpus's English
    prose and identifiers (vendor codes, clause numbers); no stemming or stopword removal --
    both are optimisations BM25's own term-frequency weighting already partially subsumes, and
    adding them here would be tuning before there's an eval (step 7) to tune against.
    """
    return _TOKEN_RE.findall(text.lower())


class BM25Index:
    """Lexical index over a fixed list of chunks. Rebuilt from scratch, in memory, whenever the
    chunk list changes -- BM25 has no incremental-update story worth using at this corpus size
    (hundreds of chunks, not millions), unlike the vector store's idempotent upsert in step 3.
    """

    def __init__(self, chunks: list[Chunk]) -> None:
        self._ids = [c.chunk_id for c in chunks]
        tokenized_corpus = [_tokenize(c.text) for c in chunks]
        # BM25Okapi raises on an empty corpus; an empty index is a valid state (e.g. a role with
        # no visible chunks upstream of this module), so guard it rather than let it crash.
        self._bm25 = BM25Okapi(tokenized_corpus) if tokenized_corpus else None

    def search(self, query: str, n_results: int) -> list[tuple[str, float]]:
        """Chunk IDs ranked by BM25 score, highest first. Chunks that share no token with the
        query score 0 and are dropped -- a 0 score is not a weak match, it is no match, and
        keeping it in the ranking would let RRF give it undeserved credit for being, say, rank
        #20 out of sheer corpus size rather than any lexical relevance.
        """
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(_tokenize(query))
        ranked = sorted(zip(self._ids, scores, strict=True), key=lambda pair: pair[1], reverse=True)
        return [(chunk_id, score) for chunk_id, score in ranked[:n_results] if score > 0]


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = DEFAULT_RRF_K) -> dict[str, float]:
    """Fuse any number of ID rankings (best first) into one score per ID: sum of 1/(k + rank)
    across every ranking the ID appears in, rank starting at 1. An ID missing from a ranking
    simply contributes nothing from that ranking, rather than being penalised -- a chunk found
    only by BM25 is not assumed irrelevant to vector search, just outside the candidate pool
    vector search happened to return.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    rrf_score: float
    bm25_rank: int | None  # None: this chunk didn't surface in BM25's candidate pool
    vector_rank: int | None  # None: this chunk didn't surface in the vector candidate pool


class HybridRetriever:
    """Combines one BM25Index with one ChunkStore (step 3) over the same chunk list. Owns no
    permission logic itself -- the permission filter (step 5) wraps this, it doesn't live here --
    so this module's only job is "best chunks for this query text," full stop.
    """

    def __init__(
        self,
        chunks: list[Chunk],
        store: ChunkStore,
        embedder: Embedder,
        rrf_k: int = DEFAULT_RRF_K,
    ) -> None:
        self._chunk_by_id = {c.chunk_id: c for c in chunks}
        self._bm25 = BM25Index(chunks)
        self._store = store
        self._embedder = embedder
        self._rrf_k = rrf_k

    def retrieve(
        self,
        query: str,
        n_results: int = 5,
        candidate_pool: int = DEFAULT_CANDIDATE_POOL,
    ) -> list[RetrievedChunk]:
        bm25_ranking = [chunk_id for chunk_id, _ in self._bm25.search(query, candidate_pool)]

        query_vector = self._embedder.embed([query])[0]
        vector_hits = self._store.query(query_vector, n_results=candidate_pool)
        vector_ranking = [chunk_id for chunk_id, _, _, _ in vector_hits]

        fused = reciprocal_rank_fusion([bm25_ranking, vector_ranking], k=self._rrf_k)
        bm25_rank_by_id = {chunk_id: rank for rank, chunk_id in enumerate(bm25_ranking, start=1)}
        vector_rank_by_id = {
            chunk_id: rank for rank, chunk_id in enumerate(vector_ranking, start=1)
        }

        ordered_ids = sorted(fused, key=lambda chunk_id: fused[chunk_id], reverse=True)
        results: list[RetrievedChunk] = []
        for chunk_id in ordered_ids:
            chunk = self._chunk_by_id.get(chunk_id)
            if chunk is None:
                # Defensive only: can't happen when the BM25 index and the store were built from
                # the same chunk list, which is this class's one constructor contract.
                continue
            results.append(
                RetrievedChunk(
                    chunk=chunk,
                    rrf_score=fused[chunk_id],
                    bm25_rank=bm25_rank_by_id.get(chunk_id),
                    vector_rank=vector_rank_by_id.get(chunk_id),
                )
            )
            if len(results) == n_results:
                break
        return results
