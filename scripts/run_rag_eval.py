"""RAG eval (Day 4 step 7): recall@5, MRR, and (optionally) faithfulness/context_recall over
the 20-question golden set (evals/datasets/rag_golden_v1.jsonl).

Retrieval metrics (recall@k, MRR) are free and run against whatever Chroma index already
exists at data/chroma/ -- build it first with `scripts/build_rag_index.py` if it's empty.
Quality metrics (faithfulness, context_recall -- the cut-down Ragas pair, see
copilot.evals.rag_quality) make REAL Anthropic API calls through CorrectiveRagService (one
retrieve/grade/[rewrite]/generate pass per question) plus two judge calls per answered
question, and cost real money -- off by default, pass --quality to run them, with your own
ANTHROPIC_API_KEY loaded from .env (keys never go in chat; see docs/HANDOFF.md).

Usage: uv run python scripts/run_rag_eval.py [--n-results N] [--questions q01,q02] [--quality]
"""

from __future__ import annotations

import argparse
import sys

from copilot.evals.rag_golden import load_rag_golden, relevant_chunk_ids
from copilot.evals.rag_metrics import mean_recall_at_k, mean_reciprocal_rank, score_retrieval
from copilot.evals.rag_quality import context_recall, faithfulness
from copilot.guardrails.policy import load_policy
from copilot.llm.client import LLMClient
from copilot.rag.chunking import chunk_corpus
from copilot.rag.corpus import load_corpus
from copilot.rag.corrective import CorrectiveRagService
from copilot.rag.embeddings import SentenceTransformerEmbedder
from copilot.rag.permissions import PermissionedRetriever
from copilot.rag.store import ChunkStore, get_chroma_client


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-results", type=int, default=5, help="k for recall@k (default: 5)")
    parser.add_argument(
        "--questions", default=None, help="comma-separated golden question ids (default: all 20)"
    )
    parser.add_argument(
        "--quality",
        action="store_true",
        help="also run faithfulness/context_recall via real LLM calls (costs money)",
    )
    args = parser.parse_args()

    all_questions = load_rag_golden()
    if args.questions:
        wanted = {i.strip() for i in args.questions.split(",") if i.strip()}
        questions = [q for q in all_questions if q.id in wanted]
        missing = wanted - {q.id for q in questions}
        if missing:
            print(f"error: unknown question id(s): {sorted(missing)}", file=sys.stderr)
            return 1
    else:
        questions = all_questions

    chunks = chunk_corpus(load_corpus())
    store = ChunkStore(get_chroma_client())
    if store.count() == 0:
        print(
            "error: data/chroma/ is empty -- run `uv run python scripts/build_rag_index.py` "
            "first to build the real index",
            file=sys.stderr,
        )
        return 1

    policy = load_policy()
    embedder = SentenceTransformerEmbedder()
    retriever = PermissionedRetriever(chunks, store, embedder, policy)

    print(f"=== Retrieval: recall@{args.n_results} and MRR over {len(questions)} questions ===")
    retrieval_scores = []
    for q in questions:
        retrieved = retriever.retrieve(q.question, q.role, n_results=args.n_results)
        relevant = relevant_chunk_ids(q, chunks)
        score = score_retrieval(
            q.id, [r.chunk.chunk_id for r in retrieved], relevant, k=args.n_results
        )
        retrieval_scores.append(score)
        recall, rr = score.recall_at_k, score.reciprocal_rank
        print(f"  {q.id}: recall@{args.n_results}={recall:.2f}  rr={rr:.2f}")

    print(f"mean recall@{args.n_results}: {mean_recall_at_k(retrieval_scores):.3f}")
    print(f"MRR: {mean_reciprocal_rank(retrieval_scores):.3f}")

    if not args.quality:
        print("\n(skipped faithfulness/context_recall -- pass --quality to run them)")
        return 0

    print(f"\n=== Quality: faithfulness + context_recall over {len(questions)} questions ===")
    llm = LLMClient()
    crag = CorrectiveRagService(llm, retriever)
    faithfulness_scores: list[float] = []
    context_recall_scores: list[float] = []
    for q in questions:
        result = crag.answer(q.question, q.role)
        if result.abstained:
            print(f"  {q.id}: abstained ({result.abstain_reason}) -- skipped")
            continue
        cited = [c.text for c in chunks if c.chunk_id in result.cited_chunk_ids]
        context_texts = cited or [
            r.chunk.text for r in retriever.retrieve(q.question, q.role, n_results=args.n_results)
        ]
        f_score = faithfulness(llm, result.answer or "", context_texts)
        cr_score = context_recall(llm, q.must_contain, context_texts)
        faithfulness_scores.append(f_score.score)
        context_recall_scores.append(cr_score.score)
        print(f"  {q.id}: faithfulness={f_score.score:.1f}  context_recall={cr_score.score:.1f}")

    if faithfulness_scores:
        print(f"mean faithfulness: {sum(faithfulness_scores) / len(faithfulness_scores):.3f}")
    if context_recall_scores:
        print(f"mean context_recall: {sum(context_recall_scores) / len(context_recall_scores):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
