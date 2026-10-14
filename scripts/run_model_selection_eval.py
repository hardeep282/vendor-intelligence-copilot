"""Model Selection Agent eval (Day 5 step 6): task_type_correct, model_family_acceptable, and
(optionally) the LLM-judged reasoning_grounded check, over the 8-question golden set
(evals/datasets/model_selection_golden_v1.jsonl).

Unlike the RAG eval (scripts/run_rag_eval.py), there is no free half here: producing a
ModelSelectionResult at all means running the agent's propose/critique/revise loop, which is
real Anthropic API calls every time (no retrieval step to score for free first) -- this script
needs your ANTHROPIC_API_KEY loaded from .env on every run, not only with --quality (keys never
go in chat; see docs/HANDOFF.md). --quality additionally runs one LLM-judge call per
non-abstained question for the reasoning_grounded check.

Usage: uv run python scripts/run_model_selection_eval.py [--questions msq01,msq02] [--quality]
"""

from __future__ import annotations

import argparse
import sys

from copilot.agents.model_selection import ModelSelectionAgent
from copilot.evals.model_selection_golden import load_model_selection_golden
from copilot.evals.model_selection_metrics import model_family_acceptable, task_type_correct
from copilot.evals.model_selection_quality import reasoning_grounded
from copilot.llm.client import LLMClient


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--questions", default=None, help="comma-separated golden question ids (default: all 8)"
    )
    parser.add_argument(
        "--quality",
        action="store_true",
        help="also run the reasoning_grounded LLM judge (one more call per question)",
    )
    args = parser.parse_args()

    all_questions = load_model_selection_golden()
    if args.questions:
        wanted = {i.strip() for i in args.questions.split(",") if i.strip()}
        questions = [q for q in all_questions if q.id in wanted]
        missing = wanted - {q.id for q in questions}
        if missing:
            print(f"error: unknown question id(s): {sorted(missing)}", file=sys.stderr)
            return 1
    else:
        questions = all_questions

    llm = LLMClient()
    agent = ModelSelectionAgent(llm)

    task_type_scores: list[float] = []
    model_family_scores: list[float] = []
    reasoning_scores: list[float] = []
    abstained = 0

    print(f"=== Model Selection Agent eval over {len(questions)} questions ===")
    for q in questions:
        result = agent.select(q.requirement)
        if result.abstained:
            abstained += 1
            print(f"  {q.id}: abstained ({result.abstain_reason})")
            task_type_scores.append(0.0)
            model_family_scores.append(0.0)
            continue

        tt_score = task_type_correct(result, q)
        mf_score = model_family_acceptable(result, q)
        task_type_scores.append(tt_score.score)
        model_family_scores.append(mf_score.score)
        line = (
            f"  {q.id}: task_type={result.task_type} ({tt_score.score:.0f}) "
            f"model_family={result.model_family} ({mf_score.score:.0f}) "
            f"revisions={result.revisions}"
        )
        if args.quality:
            r_score = reasoning_grounded(
                llm, q.requirement, result.model_family or "", result.reasoning or ""
            )
            reasoning_scores.append(r_score.score)
            line += f" reasoning_grounded={r_score.score:.0f}"
        print(line)

    n = len(questions)
    print(f"\nabstained: {abstained}/{n}")
    print(f"mean task_type_correct: {sum(task_type_scores) / n:.3f}")
    print(f"mean model_family_acceptable: {sum(model_family_scores) / n:.3f}")
    if args.quality and reasoning_scores:
        print(f"mean reasoning_grounded: {sum(reasoning_scores) / len(reasoning_scores):.3f}")
    elif not args.quality:
        print("(skipped reasoning_grounded -- pass --quality to run it)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
