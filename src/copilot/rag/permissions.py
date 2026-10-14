"""Permission filter inside the vector query (Day 4 step 5).

Purpose : make disclosure fail closed at retrieval time -- a confidential vendor contract clause
          must never come back for a role the policy says can't see it, however relevant it is
          to the query. "Inside the vector query" (not a post-hoc drop step after the fact)
          matters mechanically: filtering eligible chunks out of an *already fixed-size* result
          set silently returns fewer than n_results whenever permissions trim the field --
          "ask for 5, lose 3 to permissions, get back 2" -- whereas pushing the restriction into
          the ANN search itself (a Chroma `where` clause) means every one of the n_results
          chunks that comes back was already eligible.
Inputs  : the same inputs as HybridRetriever (a fixed Chunk list, a ChunkStore, an Embedder),
          plus the live DisclosurePolicy and a Role, both supplied per call -- a role argument,
          not a constructor argument, because one long-lived retriever instance (one chat
          session, one process) can serve more than one role across its calls.
Outputs : list[RetrievedChunk], same shape as HybridRetriever's -- a chunk a role may not see
          simply never appears in the ranking fed into RRF, rather than being fused in and
          filtered out afterwards.

BM25 has no per-call metadata filter to push the restriction into (BM25Okapi, see
retrieval.BM25Index, scores a fixed in-memory corpus; it takes no `where`-equivalent). The same
"filter before ranking, not after" principle still applies, enforced one layer up instead: the
role-scoped BM25 index is built from only the chunks that role may see in the first place, so
every hit it can possibly return is already eligible, for the identical reason the vector side's
`where` clause is a query-time filter and not a result-time one.

Authority for "can this role see this chunk" is `DisclosurePolicy.can_view(role, data_class)` --
re-derived from the live policy on every call, not read off the chunk's own `allowed_roles`
field (even though `copilot.rag.corpus.check_corpus_against_policy` already checks at ingest
time that the two agree). Trusting the policy as the one source of truth here, rather than a
value stored on the chunk, is the same posture that check_corpus_against_policy takes toward the
whole corpus -- a disclosure boundary should have exactly one place that can say yes, and a
stale `allowed_roles` value should never be able to stand in for it.
"""

from __future__ import annotations

from copilot.guardrails.policy import DataClass, DisclosurePolicy, Role
from copilot.rag.chunking import Chunk
from copilot.rag.embeddings import Embedder
from copilot.rag.retrieval import (
    DEFAULT_CANDIDATE_POOL,
    DEFAULT_RRF_K,
    BM25Index,
    RetrievedChunk,
    fuse_rankings,
)
from copilot.rag.store import ChunkStore


class PermissionedRetriever:
    """Role-aware counterpart to HybridRetriever: identical fusion mechanics, but every chunk
    either underlying ranking can return is first scoped to what `role` may see.
    """

    def __init__(
        self,
        chunks: list[Chunk],
        store: ChunkStore,
        embedder: Embedder,
        policy: DisclosurePolicy,
        rrf_k: int = DEFAULT_RRF_K,
    ) -> None:
        self._chunks = chunks
        self._store = store
        self._embedder = embedder
        self._policy = policy
        self._rrf_k = rrf_k

    def _visible_chunks(self, role: Role) -> list[Chunk]:
        return [c for c in self._chunks if self._policy.can_view(role, c.data_class)]

    def retrieve(
        self,
        query: str,
        role: Role,
        n_results: int = 5,
        candidate_pool: int = DEFAULT_CANDIDATE_POOL,
    ) -> list[RetrievedChunk]:
        visible = self._visible_chunks(role)
        if not visible:
            return []
        chunk_by_id = {c.chunk_id: c for c in visible}

        # BM25 side: index built only from this role's visible chunks, so every hit is already
        # eligible -- see module docstring for why this mirrors the vector side's `where` clause.
        bm25_ranking = [
            chunk_id for chunk_id, _ in BM25Index(visible).search(query, candidate_pool)
        ]

        # Vector side: push the identical restriction into the Chroma query itself.
        visible_classes: list[DataClass] = sorted({c.data_class for c in visible})
        query_vector = self._embedder.embed([query])[0]
        vector_hits = self._store.query(
            query_vector,
            n_results=candidate_pool,
            where={"data_class": {"$in": visible_classes}},
        )
        # The `chunk_id in chunk_by_id` guard is defensive only -- the `where` clause above
        # should already guarantee it. Kept anyway: a disclosure boundary is exactly the kind of
        # thing this project doesn't trust to a single enforcement point (see corpus.py's own
        # drift check against the same policy).
        vector_ranking = [chunk_id for chunk_id, _, _, _ in vector_hits if chunk_id in chunk_by_id]

        return fuse_rankings(bm25_ranking, vector_ranking, chunk_by_id, self._rrf_k, n_results)

    def chunk_by_id(self, chunk_id: str) -> Chunk | None:
        """Look up one chunk's full metadata (notably `data_class`) by id, from the full
        corpus this retriever was built with -- regardless of which role's call last ran.
        Added for Day 6's Knowledge specialist (`copilot.agents.specialists.run_knowledge`),
        which needs each *cited* chunk's class after the fact; `CorrectiveRagResult` reports
        only chunk ids, not the chunks themselves, so the specialist looks them back up here
        rather than `CorrectiveRagService` growing a field it has no other use for.
        """
        for c in self._chunks:
            if c.chunk_id == chunk_id:
                return c
        return None
