"""Push evals/datasets/golden_v2.jsonl to LangSmith as a dataset (Day 3 step 6).

Purpose : run this on YOUR machine, with YOUR LANGSMITH_API_KEY loaded from .env (never in
          chat -- see docs/HANDOFF.md). It does nothing else: no LLM calls, no cost. It just
          makes the LangSmith dataset "vendor-copilot-golden-v2" exactly match the JSONL file.
Usage   : uv run python scripts/push_golden_to_langsmith.py
"""

from __future__ import annotations

import sys

from langsmith import Client

from copilot.evals.golden import GOLDEN_V2_PATH, load_golden
from copilot.evals.langsmith_sync import sync_golden_dataset
from copilot.settings import get_settings


def main() -> int:
    settings = get_settings()
    if not settings.langsmith_api_key:
        print(
            "error: LANGSMITH_API_KEY is not set. Add it to .env (never paste it in chat) "
            "and try again.",
            file=sys.stderr,
        )
        return 1

    questions = load_golden(GOLDEN_V2_PATH)
    client = Client(api_key=settings.langsmith_api_key.get_secret_value())
    result = sync_golden_dataset(client, questions)

    action = "Created" if result.created_dataset else "Updated"
    print(f"{action} LangSmith dataset '{result.dataset_name}'.")
    print(f"  replaced {result.examples_deleted} old example(s) with {result.examples_created}")
    print(f"  ({len(questions)} questions read from {GOLDEN_V2_PATH})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
