"""Free (no-LLM) correctness checks for the Model Selection Agent's output against a golden
question (Day 5 step 6 eval harness).

Purpose : whether `task_type`/`model_family` are correct is a closed-catalog membership check
          (`copilot.agents.model_selection.MODEL_CATALOG` is finite and fixed), not something
          that needs an LLM to judge -- same split as the RAG eval harness (recall@k/MRR free,
          faithfulness/context_recall judged): score what pure logic can see for free, reserve
          the LLM judge (`copilot.evals.model_selection_quality`) for what it can't.
Inputs  : a `ModelSelectionResult` (what `copilot.agents.model_selection.ModelSelectionAgent`
          returned) and the `ModelSelectionGoldenQuestion` it was asked to satisfy.
Outputs : `EvalScore` (copilot.evals.evaluators), reused rather than a third score type.
"""

from __future__ import annotations

from copilot.agents.model_selection import ModelSelectionResult
from copilot.evals.evaluators import EvalScore
from copilot.evals.model_selection_golden import ModelSelectionGoldenQuestion


def task_type_correct(
    result: ModelSelectionResult, golden: ModelSelectionGoldenQuestion
) -> EvalScore:
    """1.0 if the agent didn't abstain and picked the golden's expected task type."""
    if result.abstained:
        return EvalScore(key="task_type_correct", score=0.0, comment="agent abstained")
    ok = result.task_type == golden.expected_task_type
    comment = (
        "task type matches"
        if ok
        else f"got {result.task_type!r}, expected {golden.expected_task_type!r}"
    )
    return EvalScore(key="task_type_correct", score=1.0 if ok else 0.0, comment=comment)


def model_family_acceptable(
    result: ModelSelectionResult, golden: ModelSelectionGoldenQuestion
) -> EvalScore:
    """1.0 if the agent didn't abstain and its model family is one of the golden's accepted
    set -- not a single exact match, see module docstring."""
    if result.abstained:
        return EvalScore(key="model_family_acceptable", score=0.0, comment="agent abstained")
    ok = result.model_family in golden.acceptable_model_families
    comment = (
        "model family is an accepted choice"
        if ok
        else f"got {result.model_family!r}, accepted: {golden.acceptable_model_families}"
    )
    return EvalScore(key="model_family_acceptable", score=1.0 if ok else 0.0, comment=comment)
