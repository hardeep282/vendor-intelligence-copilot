"""LLM-judged reasoning-quality check for the Model Selection Agent (Day 5 step 6 eval harness,
Addendum A1: "evaluated with LLM evals").

Purpose : `copilot.evals.model_selection_metrics` scores whether `task_type`/`model_family` are
          correct for free, by catalog membership -- but a free check can't see whether the
          agent's final *reasoning* is actually grounded in what this specific requirement
          said, or generic ML boilerplate that would read the same for any requirement sharing
          its task type (which would still pass the free checks while saying nothing useful to
          a reviewer). That's the gap an LLM judge closes, same role Day 4's faithfulness/
          context_recall judges play for RAG retrieval metrics.
Inputs  : the original requirement text, the accepted `model_family`, and the accepted
          `reasoning` (all from a non-abstained `ModelSelectionResult`).
Outputs : `EvalScore` (copilot.evals.evaluators), reused rather than a fourth score type.

Built as one small structured-output call through the existing `LLMClient`, same pattern as
`copilot.evals.rag_quality` -- see that module's docstring for why this repo writes its own
judge calls rather than pulling in a separate eval-framework dependency.
"""

from __future__ import annotations

from typing import cast

from anthropic.types import MessageParam
from pydantic import BaseModel

from copilot.evals.evaluators import EvalScore
from copilot.llm.client import Effort, LLMClient
from copilot.llm.prompts import load_prompt
from copilot.llm.types import CallMetrics


class ReasoningGrade(BaseModel):
    """Forced structured output for the model_selection_judge prompt."""

    grounded: bool


def reasoning_grounded(
    llm: LLMClient,
    requirement: str,
    model_family: str,
    reasoning: str,
    effort: Effort | None = None,
) -> EvalScore:
    """1.0 if the judge finds the reasoning grounded in this requirement's stated
    characteristics, 0.0 if it reads as generic or misstates the requirement."""
    prompt = load_prompt("model_selection_judge")
    system = prompt.render_system(
        requirement=requirement, model_family=model_family, reasoning=reasoning
    )
    messages: list[MessageParam] = [{"role": "user", "content": prompt.render_user()}]
    grade, _metrics = cast(
        "tuple[ReasoningGrade, CallMetrics]",
        llm.structured(
            model=prompt.model,
            system=system,
            messages=messages,
            output_model=ReasoningGrade,
            max_tokens=prompt.max_tokens,
            effort=effort or prompt.effort,
            cache_system=prompt.cache_system,
        ),
    )
    comment = (
        "reasoning is grounded in the stated requirement"
        if grade.grounded
        else "reasoning reads as generic or misstates the requirement"
    )
    return EvalScore(
        key="reasoning_grounded", score=1.0 if grade.grounded else 0.0, comment=comment
    )
