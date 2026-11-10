"""Learning script for session 3: RAG, the document-search layer behind the Knowledge agent.

Purpose : run the real retrieval code in eight small, numbered steps, so you can watch it work
          in VS Code's debugger. Steps 1-5 and 8 are plain Python: no Claude calls, no model
          download, free and the same every time. Steps 6 and 7 use your local search index
          (`data/chroma/`, built by `uv run python scripts/build_rag_index.py`) and the local
          embedding model; if the index isn't there they explain and skip. No step calls Claude:
          the Corrective RAG loop's three AI calls are only described (step 8).
Inputs  : the knowledge/ documents and policies/disclosure.yaml (both in the repo); optionally
          the local search index.
Outputs : plain-English printout of each step. Nothing is written anywhere.

How to use it in VS Code (see the Code Trail page, chapter 4): put a red dot on the first line
inside any `step_...` function, press F5, pick "Python Debugger: Current File", then F10 / F11.
Or just run it:
    uv run python scripts/learn/session3_rag.py
Set LEARN_SKIP_EMBEDDINGS=1 to skip steps 6-7 (the test suite does, to stay fast).

Added 10 Nov 2026 for the learning sessions. It only *uses* the copilot's code; it changes
nothing about how the copilot behaves.
"""

from __future__ import annotations

import os
from collections import Counter

from copilot.cli import use_utf8_output
from copilot.guardrails.policy import DisclosurePolicy, Role, load_policy
from copilot.llm.prompts import load_prompt
from copilot.rag.chunking import DEFAULT_MAX_CHARS, DEFAULT_OVERLAP_CHARS, Chunk, chunk_corpus
from copilot.rag.corpus import KnowledgeDoc, check_corpus_against_policy, load_corpus
from copilot.rag.corrective import MAX_CORRECTIONS, MIN_RELEVANT_CHUNKS
from copilot.rag.retrieval import DEFAULT_CANDIDATE_POOL, DEFAULT_RRF_K, BM25Index
from copilot.rag.retrieval import reciprocal_rank_fusion as rrf
from copilot.rag.store import DEFAULT_CHROMA_DIR

QUESTION = "What are Diageo's payment terms?"


def heading(n: int, title: str) -> None:
    print(f"\n{'=' * 72}\nSTEP {n}: {title}\n{'=' * 72}")


def step_1_load_the_documents(policy: DisclosurePolicy) -> list[KnowledgeDoc]:
    """The 14 documents, each tagged with who may read it (rag/corpus.py)."""
    heading(1, "Load the documents and check their tags against the policy")
    docs = load_corpus()
    check_corpus_against_policy(docs)  # raises if a document's roles drift from the policy
    for doc in docs:
        name = doc.vendor or doc.doc_type
        print(f"  {name:<28} v{doc.version}  {doc.data_class:<12} {', '.join(doc.allowed_roles)}")
    print(f"\n  {len(docs)} documents. The 10 contracts are synthetic (invented for this project).")
    return docs


def step_2_chunk_them(docs: list[KnowledgeDoc]) -> list[Chunk]:
    """Split at headings; split again only if a section is over the size limit."""
    heading(2, "Chunk by heading (rag/chunking.py)")
    chunks = chunk_corpus(docs)
    per_doc = Counter(c.chunk_id.rsplit(":", 1)[0] for c in chunks)
    for key, n in per_doc.most_common(5):
        print(f"  {key:<44} {n:>3} chunks")
    print(f"  ... {len(chunks)} chunks in all, from {len(per_doc)} documents")
    example = chunks[0]
    print(f"\n  one chunk id: {example.chunk_id}")
    print(f"  its heading path: {' > '.join(example.heading_path)}")
    print(f"  size limit {DEFAULT_MAX_CHARS} characters; {DEFAULT_OVERLAP_CHARS} overlap, used")
    print("  only when one long section has to be split.")
    return chunks


def step_3_keyword_search(chunks: list[Chunk]) -> list[str]:
    """BM25: exact-word matching, good at names and codes (rag/retrieval.py)."""
    heading(3, f"Keyword search (BM25) for {QUESTION!r}")
    hits = BM25Index(chunks).search(QUESTION, n_results=5)
    for rank, (chunk_id, score) in enumerate(hits, start=1):
        print(f"  #{rank}  score {score:5.2f}  {chunk_id}")
    return [chunk_id for chunk_id, _ in hits]


def step_4_fuse_two_rankings_by_hand() -> None:
    """Reciprocal Rank Fusion: add up 1 / (60 + rank) from each list."""
    heading(4, f"Fuse two rankings with RRF (k = {DEFAULT_RRF_K})")
    keyword = ["A", "B", "C"]
    meaning = ["C", "A", "D"]
    print(f"  keyword ranking: {keyword}\n  meaning ranking: {meaning}")
    for chunk_id, score in sorted(rrf([keyword, meaning]).items(), key=lambda kv: -kv[1]):
        print(f"    {chunk_id}: {score:.5f}")
    print("\n  A wins: 1st and 2nd beats C's 3rd and 1st. Only ranks are used, never raw")
    print("  scores, so BM25 scores and vector distances never need to be compared.")


def step_5_who_can_see_what(chunks: list[Chunk], policy: DisclosurePolicy) -> None:
    """The permission filter is applied before ranking, never after (rag/permissions.py)."""
    heading(5, "Which chunks each role can search")
    roles: tuple[Role, ...] = ("anonymous", "viewer", "analyst")
    for role in roles:
        visible = [c for c in chunks if policy.can_view(role, c.data_class)]
        classes = sorted({c.data_class for c in visible})
        print(f"  {role:<10} {len(visible):>3} of {len(chunks)} chunks  ({', '.join(classes)})")
        if role == "viewer":
            top = BM25Index(visible).search(QUESTION, n_results=1)
            print(f"             best keyword hit for the Diageo question: {top[0][0]}")
    print("\n  A viewer's search never even contains the contracts, so it can't leak them.")


def _index_available() -> bool:
    if os.environ.get("LEARN_SKIP_EMBEDDINGS") == "1":
        print("  skipped: LEARN_SKIP_EMBEDDINGS=1")
        return False
    if not DEFAULT_CHROMA_DIR.exists():
        print("  skipped: no local search index yet. Run scripts/build_rag_index.py first.")
        return False
    return True


def step_6_hybrid_search(chunks: list[Chunk], policy: DisclosurePolicy) -> None:
    """The real thing: keyword + meaning search, fused, per role."""
    heading(6, "Hybrid search on your local index, for two roles")
    if not _index_available():
        return
    from copilot.rag.embeddings import SentenceTransformerEmbedder
    from copilot.rag.permissions import PermissionedRetriever
    from copilot.rag.store import ChunkStore, get_chroma_client

    retriever = PermissionedRetriever(
        chunks, ChunkStore(get_chroma_client()), SentenceTransformerEmbedder(), policy
    )
    roles: tuple[Role, ...] = ("viewer", "analyst")
    for role in roles:
        print(f"\n  role = {role}")
        for hit in retriever.retrieve(QUESTION, role=role, n_results=3):
            print(
                f"    {hit.chunk.chunk_id:<46} keyword #{hit.bm25_rank or '-'}"
                f"  meaning #{hit.vector_rank or '-'}"
            )


def step_7_stale_chunks_in_the_index(chunks: list[Chunk]) -> None:
    """Does the index still hold chunks from older versions of a document?"""
    heading(7, "Check the index for chunks from older document versions")
    if not _index_available():
        return
    from copilot.rag.store import ChunkStore, get_chroma_client

    store = ChunkStore(get_chroma_client())
    stored = set(store._collection.get(include=[])["ids"])
    current = {c.chunk_id for c in chunks}
    stale = sorted(stored - current)
    print(f"  stored in the index: {len(stored)}   current chunks: {len(current)}")
    print(f"  stale (from older versions): {len(stale)}")
    for key, n in Counter(s.rsplit(":", 1)[0] for s in stale).most_common(6):
        print(f"    {key:<40} {n:>3}")
    if stale:
        pool = DEFAULT_CANDIDATE_POOL
        print(f"\n  Each search asks the index for {pool} candidates. Stale ones are thrown")
        print("  away afterwards (they're not current chunks), so they can crowd out real")
        print("  ones. Logged as RAID R15 (10 Nov).")


def step_8_the_corrective_loop() -> None:
    """Corrective RAG: grade what was found, rewrite the question if needed, or give up."""
    heading(8, "The Corrective RAG loop's settings (described, not called)")
    print(f"  at most {MAX_CORRECTIONS} rewrites; needs {MIN_RELEVANT_CHUNKS}+ relevant passage(s)")
    for name in ("crag_grade", "crag_rewrite", "crag_generate"):
        p = load_prompt(name)
        print(
            f"  {p.name:<14} v{p.version}  model {p.model}  effort {p.effort}  "
            f"max_tokens {p.max_tokens}"
        )
    print("\n  Each of these three is an AI call. That's why Knowledge counts as an agent.")


def main() -> None:
    use_utf8_output()
    policy = load_policy()
    docs = step_1_load_the_documents(policy)
    chunks = step_2_chunk_them(docs)
    step_3_keyword_search(chunks)
    step_4_fuse_two_rankings_by_hand()
    step_5_who_can_see_what(chunks, policy)
    step_6_hybrid_search(chunks, policy)
    step_7_stale_chunks_in_the_index(chunks)
    step_8_the_corrective_loop()
    print("\nDone. Every step above used the copilot's real code, and no AI call was made.")


if __name__ == "__main__":
    main()
