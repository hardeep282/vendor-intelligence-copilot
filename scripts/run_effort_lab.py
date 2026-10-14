"""Effort lab (Day 3 step 8): sweep `effort` across its 5 values on the same questions.

Why `effort` and not temperature: this model generation's Messages API has no `temperature`,
`top_p` or `top_k` parameter (confirmed against the installed SDK -- see
copilot.llm.client's module docstring and docs/adr/005-llm-provider.md). `effort` is the
nearest per-call lever this generation exposes, and it trades reasoning depth for
latency/cost rather than output diversity at fixed sampling -- which is exactly the
difference this script measures, not assumes.

Metrics per effort level: execution accuracy, leakage-free rate, SQL diversity across repeats
(only meaningful with --repeats > 1), average cost, average latency.

Usage   : uv run python scripts/run_effort_lab.py [--repeats N] [--questions gq-001,gq-045,gq-042]

This makes REAL Anthropic API calls and costs real money -- run it on your machine with your
own ANTHROPIC_API_KEY loaded from .env (keys never go in chat; see docs/HANDOFF.md). With the
defaults (3 questions x 5 effort levels x 1 repeat = 15 calls), expect roughly what a single
InsightService call cost (docs/BUILD_LOG.md: ~$0.011), times 15.
"""

from __future__ import annotations

import argparse
import sys

from copilot.data import store
from copilot.evals.effort_lab import EFFORT_LEVELS, run_effort_lab
from copilot.evals.golden import GOLDEN_V2_PATH, load_golden
from copilot.guardrails.policy import load_policy
from copilot.llm.client import LLMClient
from copilot.sql.service import TextToSqlService
from copilot.sql.validator import load_rules

# A deliberately small, varied set: a plain lookup, a ratio-of-sums aggregation (the kind of
# question where more reasoning should matter most), and a trap that should abstain outright.
DEFAULT_QUESTION_IDS = ["gq-001", "gq-045", "gq-042"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="repeats per question per effort level; >1 measures output diversity but "
        "multiplies the cost (default: 1)",
    )
    parser.add_argument(
        "--questions",
        default=",".join(DEFAULT_QUESTION_IDS),
        help=f"comma-separated golden question ids to sweep (default: {DEFAULT_QUESTION_IDS})",
    )
    args = parser.parse_args()

    wanted_ids = {i.strip() for i in args.questions.split(",") if i.strip()}
    all_questions = load_golden(GOLDEN_V2_PATH)
    questions = [q for q in all_questions if q.id in wanted_ids]
    missing = wanted_ids - {q.id for q in questions}
    if missing:
        print(f"error: unknown question id(s): {sorted(missing)}", file=sys.stderr)
        return 1

    n_calls = len(EFFORT_LEVELS) * len(questions) * args.repeats
    print(
        f"Running {n_calls} real LLM call(s): {len(EFFORT_LEVELS)} effort levels x "
        f"{len(questions)} question(s) x {args.repeats} repeat(s)...\n"
    )

    llm = LLMClient()
    policy = load_policy()
    rules = load_rules()
    service = TextToSqlService(llm, con=store.connect(), policy=policy, rules=rules)

    report = run_effort_lab(service, questions, policy, rules, repeats=args.repeats)

    show_diversity = args.repeats > 1
    header = (
        f"{'effort':<8} {'runs':>5} {'exec_acc':>9} {'leak_free':>10} {'avg_cost':>10} {'avg_s':>7}"
    )
    if show_diversity:
        header += f" {'diversity':>10}"
    print(header)
    for s in report.by_effort:
        row = (
            f"{s.effort:<8} {s.runs:>5} {s.execution_accuracy_rate:>9.2f} "
            f"{s.leakage_free_rate:>10.2f} ${s.avg_cost_usd:>9.5f} {s.avg_latency_s:>7.2f}"
        )
        if show_diversity:
            row += f" {s.sql_diversity:>10.2f}" if s.sql_diversity is not None else f" {'n/a':>10}"
        print(row)

    total_cost = sum(r.cost_usd for r in report.records)
    print(f"\nTotal spend this run: ${total_cost:.5f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
