"""Model Selection Agent golden set: schema and loader (Day 5 step 6 eval harness).

Purpose : 8 requirements, 2 per task type, each naming the correct `expected_task_type` and the
          set of catalog model families that would be a defensible pick for it
          (`acceptable_model_families`, not a single family -- `copilot.agents.model_selection`'s
          own catalog offers more than one reasonable choice for classification/forecasting, so
          penalizing a correct-but-different-from-one-exemplar pick would be measuring the
          dataset's own arbitrary choice, not the agent).
Inputs  : evals/datasets/model_selection_golden_v1.jsonl.
Outputs : typed `ModelSelectionGoldenQuestion` objects.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from copilot.agents.model_selection import TaskType
from copilot.settings import REPO_ROOT

MODEL_SELECTION_GOLDEN_PATH = (
    REPO_ROOT / "evals" / "datasets" / "model_selection_golden_v1.jsonl"
)


class ModelSelectionGoldenQuestion(BaseModel):
    id: str
    requirement: str
    expected_task_type: TaskType
    acceptable_model_families: list[str]


def load_model_selection_golden(
    path: Path = MODEL_SELECTION_GOLDEN_PATH,
) -> list[ModelSelectionGoldenQuestion]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [
        ModelSelectionGoldenQuestion.model_validate_json(line) for line in lines if line.strip()
    ]
