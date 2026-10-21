"""Model Selection Agent (Day 5 step 6, Addendum A1): LangGraph propose -> critique -> revise ->
abstain, same shape as `copilot.rag.corrective.CorrectiveRagService` applied to picking a model
instead of grounding an answer.

Purpose : Addendum A1 (agreed 13 Oct) calls for "LangGraph agents that pick a data-science model
          for a requirement and scrutinize the choice via CRAG/Self-RAG-style methods." This is
          that agent -- the direct precedent is Day 4's Corrective RAG loop: propose a candidate
          (there: retrieve chunks; here: a model choice), judge whether it actually holds up
          (there: grade relevance; here: critique the choice), and either accept it, revise and
          retry with the critique's feedback folded in, or abstain once the retry budget is
          spent -- never hand back a choice nobody has scrutinized.
Inputs  : a plain-text requirement (e.g. "classify SKUs as at-risk or healthy from tabular
          features", "forecast next quarter's portfolio demand").
Outputs : a `ModelSelectionResult` -- the accepted `task_type`/`model_family`/`reasoning`, or an
          explicit abstention with the reason, plus cost/latency/call accounting (same shape as
          `CorrectiveRagResult`/`TextToSqlResult`).

**The catalog is fixed and closed on purpose** (`MODEL_CATALOG` below): the agent picks from a
named list, it never invents a model family. `random_forest`/`xgboost` and `ets`/`naive` are
backed by real tools already built in this repo (`copilot.ml.risk_classifier`,
`copilot.ml.forecast`); `kmeans`/`logistic_regression`/`linear_regression` are catalog entries
only -- not yet implemented as callable tools here (K-Means already exists in the analytics
repo per ADR-000 item 1; logistic/linear regression are the sprint doc's own worked examples for
classification/regression) -- so a choice landing on one of those three is a correct *category*
pick today, with the actual implementation still ahead of this agent, not a defect in it.

**One deliberate simplification versus `CorrectiveRagService`:** that loop's "rewrite" step
needs its own LLM call because reformulating a *search query* is a creative task. Here, the
"revise" step only has to forward the critique's already-structured `concerns`/
`suggested_model_family` into the next proposal's feedback block -- plain string formatting of
output the critique call already produced, not a new reasoning task -- so `_revise` is a pure
bookkeeping node with no LLM call of its own, cheaper per revision than the RAG loop's
equivalent step.

No new ADR for this module: the LangGraph propose/critique/revise/abstain shape, the retry-
budget-then-abstain posture, and the "evaluate the free part with pure logic, the part a free
check can't see with an LLM judge" eval split (`copilot.evals.model_selection_metrics` /
`model_selection_quality`) all follow directly from decisions this repo already made (ADR-002's
abstain-rather-than-guess posture, `copilot.sql.service`'s self-correction loop, Day 4's
Corrective RAG loop and its eval-harness split) -- same reasoning Day 4's reranker/embedding-
model/vector-store choices used to skip a new ADR.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict, cast

from anthropic.types import MessageParam
from langgraph.graph import END, StateGraph
from pydantic import BaseModel

from copilot.llm.client import Effort, LLMClient
from copilot.llm.prompts import load_prompt
from copilot.llm.types import CallMetrics

# Mirrors copilot.rag.corrective.MAX_CORRECTIONS / copilot.sql.service.MAX_SELF_CORRECTIONS:
# the first proposal plus up to this many revisions, then abstain rather than hand back a model
# choice that's still failed scrutiny.
MAX_REVISIONS = 2

TaskType = Literal["classification", "clustering", "regression", "forecasting"]
Verdict = Literal["correct", "incorrect", "ambiguous"]
_Route = Literal["accept", "revise", "abstain"]

# Fixed, closed catalog -- see module docstring for which families are backed by a real tool in
# this repo today versus a category-correct pick awaiting its own implementation.
MODEL_CATALOG: dict[TaskType, tuple[str, ...]] = {
    "classification": ("random_forest", "xgboost", "logistic_regression"),
    "clustering": ("kmeans",),
    "regression": ("linear_regression",),
    "forecasting": ("ets", "naive"),
}

_CATALOG_NOTES: dict[str, str] = {
    "random_forest": "backed by copilot.ml.risk_classifier (built, Day 5)",
    "xgboost": "backed by copilot.ml.risk_classifier (built, Day 5)",
    "logistic_regression": "catalog entry only -- not yet implemented as a tool here",
    "kmeans": "already exists in the analytics repo (ADR-000 item 1); not yet a tool here",
    "linear_regression": "catalog entry only -- not yet implemented as a tool here",
    "ets": "backed by copilot.ml.forecast (built, Day 5)",
    "naive": "backed by copilot.ml.forecast (built, Day 5)",
}


def _catalog_block() -> str:
    lines = []
    for task_type, families in MODEL_CATALOG.items():
        for family in families:
            lines.append(f"- {task_type}: {family} ({_CATALOG_NOTES[family]})")
    return "\n".join(lines)


def all_model_families() -> frozenset[str]:
    """Every model family in the catalog, across all task types -- used by tests/evals to
    confirm a proposal never names something outside it."""
    return frozenset(f for families in MODEL_CATALOG.values() for f in families)


class ModelProposal(BaseModel):
    """Forced structured output for the model_selection_propose prompt."""

    task_type: TaskType
    model_family: str
    reasoning: str


class ModelCritique(BaseModel):
    """Forced structured output for the model_selection_critique prompt."""

    verdict: Verdict
    concerns: str
    suggested_model_family: str | None = None


class ModelSelectionResult(BaseModel):
    requirement: str
    task_type: TaskType | None = None
    model_family: str | None = None
    reasoning: str | None = None
    revisions: int = 0
    rejected_proposals: list[str] = []
    abstained: bool
    abstain_reason: str | None = None
    total_cost_usd: float = 0.0
    total_latency_s: float = 0.0
    llm_calls: int = 0


class _State(TypedDict):
    requirement: str
    attempt: int
    feedback: str
    proposal: ModelProposal | None
    last_critique: ModelCritique | None
    rejected_proposals: list[str]
    total_cost_usd: float
    total_latency_s: float
    llm_calls: int
    result: ModelSelectionResult | None


class ModelSelectionAgent:
    """Wraps an `LLMClient` in the propose/critique/revise/accept/abstain loop, compiled once as
    a LangGraph graph in `__init__` -- same construction pattern as `CorrectiveRagService`.
    """

    def __init__(self, llm: LLMClient, effort: Effort | None = None) -> None:
        self._llm = llm
        self._effort = effort
        self._graph = self._build_graph()

    def select(self, requirement: str) -> ModelSelectionResult:
        initial: _State = {
            "requirement": requirement,
            "attempt": 0,
            "feedback": "",
            "proposal": None,
            "last_critique": None,
            "rejected_proposals": [],
            "total_cost_usd": 0.0,
            "total_latency_s": 0.0,
            "llm_calls": 0,
            "result": None,
        }
        final_state = cast("_State", self._graph.invoke(initial))
        result = final_state["result"]
        if result is None:
            # Can't happen: every path through the graph (accept, abstain) sets "result" before
            # reaching END -- raised rather than asserted so it survives -O, same posture as
            # CorrectiveRagService.answer()'s equivalent guard.
            raise RuntimeError("model selection graph reached END without producing a result")
        return result

    # -- graph construction --------------------------------------------------------------

    def _build_graph(self) -> Any:  # noqa: ANN401 -- see CorrectiveRagService._build_graph's
        # identical comment: only ever used via the narrow .invoke() call below.
        graph: StateGraph[_State] = StateGraph(_State)
        graph.add_node("propose", self._propose)
        graph.add_node("critique", self._critique)
        graph.add_node("revise", self._revise)
        graph.add_node("accept", self._accept)
        graph.add_node("abstain", self._abstain)
        graph.set_entry_point("propose")
        graph.add_edge("propose", "critique")
        graph.add_conditional_edges(
            "critique",
            self._route_after_critique,
            {"accept": "accept", "revise": "revise", "abstain": "abstain"},
        )
        graph.add_edge("revise", "propose")
        graph.add_edge("accept", END)
        graph.add_edge("abstain", END)
        return graph.compile()

    # -- nodes -----------------------------------------------------------------------------

    def _propose(self, state: _State) -> dict[str, object]:
        prompt = load_prompt("model_selection_propose")
        feedback_block = state["feedback"] or (
            "This is the first proposal for this requirement; no prior feedback yet."
        )
        system = prompt.render_system(catalog_block=_catalog_block(), feedback_block=feedback_block)
        messages: list[MessageParam] = [
            {"role": "user", "content": prompt.render_user(requirement=state["requirement"])}
        ]
        proposal, metrics = cast(
            "tuple[ModelProposal, CallMetrics]",
            self._llm.structured(
                model=prompt.model,
                system=system,
                messages=messages,
                output_model=ModelProposal,
                max_tokens=prompt.max_tokens,
                effort=self._effort or prompt.effort,
                cache_system=prompt.cache_system,
                prompt_name=prompt.name,
                prompt_version=prompt.version,
            ),
        )
        return {
            "proposal": proposal,
            "total_cost_usd": state["total_cost_usd"] + metrics.cost_usd,
            "total_latency_s": state["total_latency_s"] + metrics.total_latency_s,
            "llm_calls": state["llm_calls"] + 1,
        }

    def _critique(self, state: _State) -> dict[str, object]:
        proposal = state["proposal"]
        if proposal is None:
            raise RuntimeError("_critique reached without a proposal -- _propose must run first")
        prompt = load_prompt("model_selection_critique")
        system = prompt.render_system(
            requirement=state["requirement"],
            task_type=proposal.task_type,
            model_family=proposal.model_family,
            reasoning=proposal.reasoning,
        )
        messages: list[MessageParam] = [{"role": "user", "content": prompt.render_user()}]
        critique, metrics = cast(
            "tuple[ModelCritique, CallMetrics]",
            self._llm.structured(
                model=prompt.model,
                system=system,
                messages=messages,
                output_model=ModelCritique,
                max_tokens=prompt.max_tokens,
                effort=self._effort or prompt.effort,
                cache_system=prompt.cache_system,
                prompt_name=prompt.name,
                prompt_version=prompt.version,
            ),
        )
        return {
            "last_critique": critique,
            "total_cost_usd": state["total_cost_usd"] + metrics.cost_usd,
            "total_latency_s": state["total_latency_s"] + metrics.total_latency_s,
            "llm_calls": state["llm_calls"] + 1,
        }

    def _route_after_critique(self, state: _State) -> _Route:
        critique = state["last_critique"]
        if critique is None:
            raise RuntimeError(
                "_route_after_critique reached without a critique -- _critique must run first"
            )
        if critique.verdict == "correct":
            return "accept"
        if state["attempt"] >= MAX_REVISIONS:
            return "abstain"
        return "revise"

    def _revise(self, state: _State) -> dict[str, object]:
        """Pure bookkeeping, no LLM call -- see module docstring on why this differs from
        CorrectiveRagService's "rewrite" node."""
        proposal = state["proposal"]
        critique = state["last_critique"]
        if proposal is None or critique is None:
            raise RuntimeError("_revise reached without a proposal and critique")
        suggestion = (
            f" Consider instead: {critique.suggested_model_family}."
            if critique.suggested_model_family
            else ""
        )
        feedback = (
            f"A previous proposal (task_type={proposal.task_type}, "
            f"model_family={proposal.model_family}) was rejected: {critique.concerns}."
            f"{suggestion}"
        )
        return {
            "feedback": feedback,
            "rejected_proposals": [*state["rejected_proposals"], proposal.model_family],
            "attempt": state["attempt"] + 1,
        }

    def _accept(self, state: _State) -> dict[str, object]:
        proposal = state["proposal"]
        if proposal is None:
            raise RuntimeError("_accept reached without a proposal")
        result = ModelSelectionResult(
            requirement=state["requirement"],
            task_type=proposal.task_type,
            model_family=proposal.model_family,
            reasoning=proposal.reasoning,
            revisions=state["attempt"],
            rejected_proposals=state["rejected_proposals"],
            abstained=False,
            total_cost_usd=state["total_cost_usd"],
            total_latency_s=state["total_latency_s"],
            llm_calls=state["llm_calls"],
        )
        return {"result": result}

    def _abstain(self, state: _State) -> dict[str, object]:
        critique = state["last_critique"]
        if critique is None:
            raise RuntimeError("_abstain reached without a critique")
        reason = (
            f"no proposal passed scrutiny after {state['attempt']} revision(s); "
            f"last concern: {critique.concerns}"
        )
        result = ModelSelectionResult(
            requirement=state["requirement"],
            revisions=state["attempt"],
            rejected_proposals=state["rejected_proposals"],
            abstained=True,
            abstain_reason=reason,
            total_cost_usd=state["total_cost_usd"],
            total_latency_s=state["total_latency_s"],
            llm_calls=state["llm_calls"],
        )
        return {"result": result}
