"""Answer-quality evaluators for the RAG golden set (Day 4 step 7): faithfulness and context
recall, judged by an LLM -- the cut-down Ragas pair.

Purpose : recall@5/MRR (copilot.evals.rag_metrics) score retrieval; they say nothing about
          whether a *generated answer* actually stuck to its context or whether the context
          handed to the model was enough to answer at all. The sprint doc asks for the full
          Ragas suite (faithfulness, answer relevancy, context precision, context recall);
          its own cut-first note (docs/HANDOFF.md) allows reducing that to faithfulness and
          context recall only, which is what's built here.
Inputs  : for `faithfulness`, a generated answer plus the context chunks it was grounded in;
          for `context_recall`, a reference answer plus the context chunks retrieval actually
          returned. Both go through `copilot.llm.client.LLMClient`, same as every other
          LLM-judged check in this repo.
Outputs : `EvalScore` (copilot.evals.evaluators), reused rather than a second score type --
          same binary 1.0/0.0 shape `execution_accuracy`/`leakage_free` already use, and the
          same thing `langsmith.evaluate()` expects from a custom evaluator function.

Built as two small, typed structured-output calls through the existing `LLMClient`, rather than
pulling in the `ragas` package directly: this project's evaluators (copilot.evals.evaluators)
are already hand-written against this exact pattern (a Pydantic grade model, one LLMClient call,
one EvalScore out), and `ragas` brings its own LLM-wrapper and dependency surface (LangChain
chat-model adapters, its own cost/latency accounting) that would sit alongside -- not replace --
the LLMClient wrapper this repo already standardised on in Day 3. Logged here, not as a new ADR,
for the same reason the embedding model and vector store weren't: it's a "use what's already
standard here" choice, not a build-vs-buy decision with real alternatives measured against it.

Like the effort/tokenization labs and `scripts/build_rag_index.py`, real judged scores need a
live `ANTHROPIC_API_KEY` and run on your machine (`scripts/run_rag_eval.py`); every test here
uses the same `FakeMessagesResource` fake as the rest of the LLM-calling code in this repo.
"""

from __future__ import annotations

from typing import cast

from anthropic.types import MessageParam
from pydantic import BaseModel

from copilot.evals.evaluators import EvalScore
from copilot.llm.client import Effort, LLMClient
from copilot.llm.prompts import load_prompt
from copilot.llm.types import CallMetrics


class FaithfulnessGrade(BaseModel):
    """Forced structured output for the rag_faithfulness prompt."""

    faithful: bool
    unsupported_claims: list[str] = []


class ContextRecallGrade(BaseModel):
    """Forced structured output for the rag_context_recall prompt."""

    sufficient: bool
    missing_information: str | None = None


def faithfulness(
    llm: LLMClient,
    answer: str,
    context_chunks: list[str],
    effort: Effort | None = None,
) -> EvalScore:
    """1.0 if every claim in `answer` is supported by `context_chunks`, 0.0 otherwise -- binary,
    not a fraction, so one unsupported claim fails the check the same way the SQL evaluators
    treat any violation as a fail rather than averaging it away.
    """
    prompt = load_prompt("rag_faithfulness")
    system = prompt.render_system(context_block="\n\n".join(context_chunks))
    messages: list[MessageParam] = [{"role": "user", "content": prompt.render_user(answer=answer)}]
    grade, _metrics = cast(
        "tuple[FaithfulnessGrade, CallMetrics]",
        llm.structured(
            model=prompt.model,
            system=system,
            messages=messages,
            output_model=FaithfulnessGrade,
            max_tokens=prompt.max_tokens,
            effort=effort or prompt.effort,
            cache_system=prompt.cache_system,
        ),
    )
    comment = (
        "every claim supported by the given context"
        if grade.faithful
        else f"unsupported claims: {'; '.join(grade.unsupported_claims) or '(unspecified)'}"
    )
    return EvalScore(key="faithfulness", score=1.0 if grade.faithful else 0.0, comment=comment)


def context_recall(
    llm: LLMClient,
    reference_answer: str,
    context_chunks: list[str],
    effort: Effort | None = None,
) -> EvalScore:
    """1.0 if the retrieved context contains enough information to produce `reference_answer`,
    0.0 otherwise -- measures the retrieval step's sufficiency independent of what any
    particular generation call then did with it.
    """
    prompt = load_prompt("rag_context_recall")
    system = prompt.render_system(context_block="\n\n".join(context_chunks))
    messages: list[MessageParam] = [
        {"role": "user", "content": prompt.render_user(reference_answer=reference_answer)}
    ]
    grade, _metrics = cast(
        "tuple[ContextRecallGrade, CallMetrics]",
        llm.structured(
            model=prompt.model,
            system=system,
            messages=messages,
            output_model=ContextRecallGrade,
            max_tokens=prompt.max_tokens,
            effort=effort or prompt.effort,
            cache_system=prompt.cache_system,
        ),
    )
    comment = grade.missing_information or "context was sufficient"
    return EvalScore(key="context_recall", score=1.0 if grade.sufficient else 0.0, comment=comment)
