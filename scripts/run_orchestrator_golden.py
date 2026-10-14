"""Day 6 step 7: run the 10 multi-hop golden questions end to end through the real
Orchestrator -- real specialists, real Anthropic API calls, real Verifier loop.

This makes REAL Anthropic API calls and costs real money -- run it on your machine with your
own ANTHROPIC_API_KEY loaded from .env (keys never go in chat; see docs/HANDOFF.md). It also
needs the real snapshot (`uv run python scripts/build_snapshot.py`) and the real Chroma index
(`uv run python scripts/build_rag_index.py`) already built.

Per question, this prints: the Orchestrator's own answer, whether it passed verification
(and how many redraft attempts it took), which specialists actually ran vs. which the golden
question expected (plan coverage -- a structural check, not an answer-accuracy grade: see
copilot.evals.orchestrator_golden's module docstring for why this dataset doesn't carry a
reference answer to diff against), and cost/latency. A SQLite checkpoint for every run is left
at data/orchestrator_checkpoints.sqlite (Day 6 step 6) so any run can be inspected afterwards.

Usage: uv run python scripts/run_orchestrator_golden.py [--questions oq-001,oq-003]
"""

from __future__ import annotations

import argparse
import sys

from copilot.agents.contracts import AgentBudget
from copilot.agents.orchestrator import Orchestrator
from copilot.agents.wiring import build_executors
from copilot.data import store
from copilot.evals.orchestrator_golden import load_orchestrator_golden
from copilot.guardrails.policy import load_policy
from copilot.llm.client import LLMClient
from copilot.rag.chunking import chunk_corpus
from copilot.rag.corpus import load_corpus
from copilot.rag.corrective import CorrectiveRagService
from copilot.rag.embeddings import SentenceTransformerEmbedder
from copilot.rag.permissions import PermissionedRetriever
from copilot.rag.store import ChunkStore, get_chroma_client
from copilot.settings import REPO_ROOT, get_settings
from copilot.sql.service import TextToSqlService
from copilot.sql.validator import load_rules

CHECKPOINT_PATH = str(REPO_ROOT / "data" / "orchestrator_checkpoints.sqlite")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--questions", default=None, help="comma-separated golden question ids (default: all 10)"
    )
    args = parser.parse_args()

    if not (get_settings().snapshot_dir / "MANIFEST.json").exists():
        print(
            "error: data/snapshot/ is empty -- run `uv run python scripts/build_snapshot.py` "
            "first",
            file=sys.stderr,
        )
        return 1

    all_questions = load_orchestrator_golden()
    if args.questions:
        wanted = {i.strip() for i in args.questions.split(",") if i.strip()}
        questions = [q for q in all_questions if q.id in wanted]
        missing = wanted - {q.id for q in questions}
        if missing:
            print(f"error: unknown question id(s): {sorted(missing)}", file=sys.stderr)
            return 1
    else:
        questions = all_questions

    print(f"Running {len(questions)} multi-hop question(s) end to end through the real "
          "Orchestrator (real LLM calls)...\n")

    llm = LLMClient()
    policy = load_policy()
    con = store.connect()
    sql_service = TextToSqlService(llm, con=con, policy=policy, rules=load_rules())

    chunks = chunk_corpus(load_corpus())
    chunk_store = ChunkStore(get_chroma_client())
    if chunk_store.count() == 0:
        print(
            "error: data/chroma/ is empty -- run `uv run python scripts/build_rag_index.py` "
            "first",
            file=sys.stderr,
        )
        return 1
    retriever = PermissionedRetriever(chunks, chunk_store, SentenceTransformerEmbedder(), policy)
    rag_service = CorrectiveRagService(llm, retriever)

    executors = build_executors(
        llm=llm, sql_service=sql_service, rag_service=rag_service, retriever=retriever, con=con,
        policy=policy,
    )
    orch = Orchestrator(
        llm,
        executors=executors,
        default_budget=AgentBudget(max_latency_s=60.0),
        checkpoint_path=CHECKPOINT_PATH,
    )

    passed_coverage = 0
    passed_verification = 0
    for q in questions:
        result = orch.answer(q.question, role=q.role, thread_id=q.id)
        actual_agents = {r.agent for r in result.results}
        missing_agents = set(q.expected_agents) - actual_agents
        coverage_ok = not missing_agents
        passed_coverage += coverage_ok
        passed_verification += result.verified

        print(f"--- {q.id} ---")
        print(f"  question: {q.question}")
        print(f"  answer: {result.answer}")
        print(
            f"  verified={result.verified} (attempts={result.verify_attempts}) "
            f"coverage={'ok' if coverage_ok else f'MISSING {sorted(missing_agents)}'}"
        )
        if result.conflicts_noted:
            print(f"  conflicts_noted: {result.conflicts_noted}")
        failed = [r.agent for r in result.results if r.status == "failed"]
        if failed:
            print(f"  failed specialists: {failed}")
        print(
            f"  cost=${result.total_cost_usd:.4f} latency={result.total_latency_s:.1f}s "
            f"llm_calls={result.llm_calls}\n"
        )

    print(
        f"=== plan coverage: {passed_coverage}/{len(questions)}  "
        f"verified: {passed_verification}/{len(questions)} ==="
    )
    print(f"(checkpoints at {CHECKPOINT_PATH}, thread_id = question id)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
