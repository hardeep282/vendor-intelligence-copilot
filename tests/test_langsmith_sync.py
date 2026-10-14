"""copilot.evals.langsmith_sync: tested against a fake LangSmith client, no network call and
no API key (same pattern as the Anthropic fakes in tests/fakes/)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from copilot.evals.golden import GoldenQuestion
from copilot.evals.langsmith_sync import DATASET_NAME, sync_golden_dataset


@dataclass
class FakeDataset:
    id: str
    name: str


@dataclass
class FakeExample:
    id: str


class FakeLangSmithClient:
    """Enough of langsmith.Client's surface for sync_golden_dataset, nothing more."""

    def __init__(self, existing_dataset: FakeDataset | None = None, existing_examples=None):
        self._dataset = existing_dataset
        self._examples: list[FakeExample] = list(existing_examples or [])
        self.created_examples: list[dict[str, Any]] = []
        self.deleted_ids: list[str] = []
        self.create_dataset_calls: list[tuple[str, str]] = []

    def has_dataset(self, *, dataset_name: str) -> bool:
        return self._dataset is not None and self._dataset.name == dataset_name

    def read_dataset(self, *, dataset_name: str) -> FakeDataset:
        assert self._dataset is not None
        return self._dataset

    def create_dataset(self, dataset_name: str, *, description: str) -> FakeDataset:
        self.create_dataset_calls.append((dataset_name, description))
        self._dataset = FakeDataset(id="ds-new", name=dataset_name)
        return self._dataset

    def list_examples(self, *, dataset_id: str):  # noqa: ANN001
        return list(self._examples)

    def delete_examples(self, example_ids: list[str]) -> None:
        self.deleted_ids.extend(example_ids)
        self._examples = [e for e in self._examples if e.id not in example_ids]

    def create_examples(self, *, dataset_id: str, examples: list[dict[str, Any]]) -> None:
        self.created_examples.extend(examples)


def _q(id_: str) -> GoldenQuestion:
    return GoldenQuestion(
        id=id_,
        split="dev",
        category="lookup",
        difficulty="easy",
        question=f"question for {id_}",
        role="viewer",
        expect="answer",
        sql="SELECT 1",
        expected_rows=[{"x": 1}],
        reference_answer="n/a",
        answer_source="sql",
    )


def test_creates_the_dataset_when_it_does_not_exist_yet():
    client = FakeLangSmithClient(existing_dataset=None)
    result = sync_golden_dataset(client, [_q("gq-1"), _q("gq-2")])

    assert result.created_dataset
    assert result.examples_created == 2
    assert result.examples_deleted == 0
    assert client.create_dataset_calls == [(DATASET_NAME, client.create_dataset_calls[0][1])]
    assert len(client.created_examples) == 2


def test_reuses_an_existing_dataset_without_recreating_it():
    client = FakeLangSmithClient(existing_dataset=FakeDataset(id="ds-1", name=DATASET_NAME))
    result = sync_golden_dataset(client, [_q("gq-1")])

    assert not result.created_dataset
    assert client.create_dataset_calls == []


def test_clears_stale_examples_before_recreating():
    client = FakeLangSmithClient(
        existing_dataset=FakeDataset(id="ds-1", name=DATASET_NAME),
        existing_examples=[FakeExample(id="old-1"), FakeExample(id="old-2")],
    )
    result = sync_golden_dataset(client, [_q("gq-1")])

    assert result.examples_deleted == 2
    assert set(client.deleted_ids) == {"old-1", "old-2"}
    assert result.examples_created == 1


def test_example_payload_carries_the_golden_question_fields():
    client = FakeLangSmithClient(existing_dataset=None)
    sync_golden_dataset(client, [_q("gq-1")])

    example = client.created_examples[0]
    assert example["inputs"] == {"question": "question for gq-1", "role": "viewer"}
    assert example["outputs"]["expected_rows"] == [{"x": 1}]
    assert example["metadata"]["id"] == "gq-1"


def test_empty_golden_set_clears_without_creating_anything():
    client = FakeLangSmithClient(
        existing_dataset=FakeDataset(id="ds-1", name=DATASET_NAME),
        existing_examples=[FakeExample(id="old-1")],
    )
    result = sync_golden_dataset(client, [])

    assert result.examples_deleted == 1
    assert result.examples_created == 0
    assert client.created_examples == []
