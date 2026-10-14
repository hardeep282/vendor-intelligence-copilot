"""Push the golden set to LangSmith as a dataset (Day 3 step 6).

Purpose : keep one LangSmith dataset in sync with `evals/datasets/golden_v2.jsonl` so the
          effort lab, the tokenization lab and any future eval run can target a dataset
          instead of re-reading the JSONL by hand each time. Sync is a full replace, not an
          incremental diff -- the set is 46 rows, so delete-and-recreate is simpler to reason
          about than matching stale examples one by one, and it's what `scripts/
          push_golden_to_langsmith.py` runs on your machine (needs your own LANGSMITH_API_KEY;
          never run from here -- see docs/HANDOFF.md: keys never go in chat).
Inputs  : a LangSmith `Client` (real or a test fake with the same method surface) and the
          golden questions to push.
Outputs : a `SyncResult` with what changed -- created, deleted, and the final example count.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

from copilot.evals.golden import GoldenQuestion

DATASET_NAME = "vendor-copilot-golden-v2"
DATASET_DESCRIPTION = (
    "Vendor Intelligence Copilot golden set v2: v1's 40 questions plus 6 text-to-SQL trap "
    "questions (docs/specs/text_to_sql_safety.md). v1 stays frozen; this dataset always "
    "mirrors evals/datasets/golden_v2.jsonl exactly."
)


class LangSmithClient(Protocol):
    """The subset of `langsmith.Client` this module calls -- lets tests pass a fake."""

    def has_dataset(self, *, dataset_name: str) -> bool: ...
    def read_dataset(self, *, dataset_name: str) -> Any: ...
    def create_dataset(self, dataset_name: str, *, description: str) -> Any: ...
    def list_examples(self, *, dataset_id: Any) -> Any: ...
    def delete_examples(self, example_ids: list[Any]) -> None: ...
    def create_examples(self, *, dataset_id: Any, examples: list[dict[str, Any]]) -> Any: ...


class SyncResult(BaseModel):
    dataset_name: str
    created_dataset: bool
    examples_deleted: int
    examples_created: int


def _to_example(q: GoldenQuestion) -> dict[str, Any]:
    return {
        "inputs": {"question": q.question, "role": q.role},
        "outputs": {
            "expect": q.expect,
            "sql": q.sql,
            "expected_rows": q.expected_rows,
            "reference_answer": q.reference_answer,
        },
        "metadata": {
            "id": q.id,
            "split": q.split,
            "category": q.category,
            "difficulty": q.difficulty,
            "data_class": q.data_class,
        },
    }


def sync_golden_dataset(
    client: LangSmithClient,
    questions: list[GoldenQuestion],
    dataset_name: str = DATASET_NAME,
) -> SyncResult:
    """Make the named LangSmith dataset exactly match `questions`: clear it (or create it)
    then re-create every example fresh, so the dataset never silently drifts from the file."""
    created_dataset = not client.has_dataset(dataset_name=dataset_name)
    if created_dataset:
        dataset = client.create_dataset(dataset_name, description=DATASET_DESCRIPTION)
    else:
        dataset = client.read_dataset(dataset_name=dataset_name)

    existing = list(client.list_examples(dataset_id=dataset.id))
    if existing:
        client.delete_examples([e.id for e in existing])

    examples = [_to_example(q) for q in questions]
    if examples:
        client.create_examples(dataset_id=dataset.id, examples=examples)

    return SyncResult(
        dataset_name=dataset_name,
        created_dataset=created_dataset,
        examples_deleted=len(existing),
        examples_created=len(examples),
    )
