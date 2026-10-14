"""Day 6 step 3: the Orchestrator -- typed plan, `Send` fan-out for independent tasks, join,
merge and (logged-only, per the sprint doc's cut-first) conflict handling.

Purpose : master prompt C3's main agent. Turns one user question into a typed plan (a list of
          `TaskSpec`s, one per specialist needed), runs every planned task -- independent ones
          in parallel via LangGraph's `Send` -- collects their `AgentResult`s, and drafts the
          one answer the user actually sees. The Orchestrator is the only agent that talks to
          the user (C3); specialists never do.
Inputs  : a plain-text question + a Role. Also, at construction time, an `LLMClient` and a
          mapping of `AgentName -> SpecialistExecutor` -- the already-built, already-tested
          `run_*` functions from `copilot.agents.specialists`, wired in by the caller.
Outputs : an `OrchestratorResult` -- the plan, every specialist's `AgentResult`, the drafted
          answer, any conflicts noted (logged, not resolved -- see below), and cost/latency/
          call accounting across the whole run.

**Why specialists are injected as a dict of callables, not constructed here:** each specialist
needs a different real dependency (`TextToSqlService`, a DuckDB connection, a
`CorrectiveRagService` + its `PermissionedRetriever`, an `LLMClient`) -- the Orchestrator's job
is coordination, not reproducing Day 3-5's service wiring a second time. This also makes the
Orchestrator trivially testable: tests inject fake executors and never need a real snapshot,
Chroma index, or API key to exercise the plan/fan-out/merge/draft logic itself (the specialists'
own correctness is Day 6 step 2's job, already covered there).

**Conflict handling is logged only, not resolved** (sprint doc Day 6 cut-first list): the draft
step asks the model to name any disagreement it notices between specialists' findings in
`conflicts_noted`, but nothing here re-queries a specialist or arbitrates between them. A later
day can act on `conflicts_noted` without this module changing.

**A specialist executor raising is caught, not let crash the graph:** one specialist's bug
(or Day 5's known "needs a real API key" case) shouldn't take down every other task in the plan.
A raised exception becomes a `status="failed"` `AgentResult` with the exception message in
`gaps`, so the draft step can say plainly what's missing -- same posture `run_data_analyst`/
`run_knowledge` already take toward their own services' abstentions.

**Day 6 step 4: the Verifier.** After `draft`, a separate judge call (`orchestrator_verify`)
checks the drafted answer against the specialist findings it was supposed to be built from --
numeric grounding, citations, sufficiency, contradictions between agents -- same propose/
critique/revise/accept shape `ModelSelectionAgent` already uses (`_verify` is the critique,
`_revise_draft` is the pure, LLM-free bookkeeping step that folds the verdict's feedback back
into state, mirroring `_revise`/`MAX_REVISIONS` there). If the draft fails verification, it loops
back to `draft` with that feedback for a redraft, up to `MAX_VERIFICATION_LOOPS` times; after
that it finalizes anyway with `verified=False` rather than looping forever -- a worse answer
delivered honestly-flagged beats no answer at all.
"""

from __future__ import annotations

import operator
import time
from collections.abc import Callable
from typing import Annotated, Any, TypedDict, cast

from anthropic.types import MessageParam
from langgraph.graph import END, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from copilot.agents.contracts import AgentBudget, AgentName, AgentResult, TaskSpec
from copilot.guardrails.policy import Role
from copilot.llm.client import Effort, LLMClient
from copilot.llm.prompts import load_prompt
from copilot.llm.types import CallMetrics

SpecialistExecutor = Callable[[TaskSpec], AgentResult]

MAX_VERIFICATION_LOOPS = 2

_ROSTER = {
    "data_analyst": "figures from the database via text-to-SQL (lookups, aggregations)",
    "forecasting_risk": "demand forecasts and SKU risk scores",
    "inventory_planning": "safety stock, reorder point, EOQ -- needs forecasting_risk's output",
    "knowledge": "definitions, methodology, contract terms via grounded document retrieval",
    "action": "drafts a renegotiation email or reorder recommendation -- never sends anything",
}


def _roster_block() -> str:
    return "\n".join(f"- {name}: {desc}" for name, desc in _ROSTER.items())


class PlannedTask(BaseModel):
    """One task in the Orchestrator's plan -- becomes a `TaskSpec` once a role/budget are
    attached (the plan itself doesn't carry those; they're the Orchestrator's to set).
    """

    agent: AgentName
    objective: str
    constraints: dict[str, str] = Field(default_factory=dict)


class OrchestratorPlan(BaseModel):
    """Forced structured output for the orchestrator_plan prompt."""

    tasks: list[PlannedTask]


class DraftAnswer(BaseModel):
    """Forced structured output for the orchestrator_draft prompt."""

    answer: str
    cited_tasks: list[str] = Field(default_factory=list)
    conflicts_noted: list[str] = Field(default_factory=list)


class VerifierVerdict(BaseModel):
    """Forced structured output for the orchestrator_verify prompt (Day 6 step 4)."""

    grounded: bool
    citations_ok: bool
    sufficient: bool
    contradictions: list[str] = Field(default_factory=list)
    feedback: str = ""

    @property
    def passed(self) -> bool:
        return self.grounded and self.citations_ok and self.sufficient and not self.contradictions


class OrchestratorResult(BaseModel):
    question: str
    role: Role
    plan: list[TaskSpec] = Field(default_factory=list)
    results: list[AgentResult] = Field(default_factory=list)
    answer: str | None = None
    conflicts_noted: list[str] = Field(default_factory=list)
    verified: bool = False
    verify_attempts: int = 0
    total_cost_usd: float = 0.0
    total_latency_s: float = 0.0
    llm_calls: int = 0


class _State(TypedDict):
    question: str
    role: Role
    plan: list[TaskSpec]
    current_task: TaskSpec | None
    results: Annotated[list[AgentResult], operator.add]
    draft: DraftAnswer | None
    verify_attempt: int
    verify_feedback: str
    last_verdict: VerifierVerdict | None
    result: OrchestratorResult | None
    total_cost_usd: float
    total_latency_s: float
    llm_calls: int


class Orchestrator:
    """Wraps an `LLMClient` and a specialist-executor map in the plan -> fan-out -> join ->
    draft loop, compiled once as a LangGraph graph in `__init__` -- same construction pattern
    `CorrectiveRagService`/`ModelSelectionAgent` already use.
    """

    def __init__(
        self,
        llm: LLMClient,
        executors: dict[AgentName, SpecialistExecutor],
        effort: Effort | None = None,
        default_budget: AgentBudget | None = None,
    ) -> None:
        self._llm = llm
        self._executors = executors
        self._effort = effort
        self._default_budget = default_budget or AgentBudget()
        self._graph = self._build_graph()

    def answer(self, question: str, role: Role) -> OrchestratorResult:
        initial: _State = {
            "question": question,
            "role": role,
            "plan": [],
            "current_task": None,
            "results": [],
            "draft": None,
            "verify_attempt": 0,
            "verify_feedback": "",
            "last_verdict": None,
            "result": None,
            "total_cost_usd": 0.0,
            "total_latency_s": 0.0,
            "llm_calls": 0,
        }
        final_state = cast("_State", self._graph.invoke(initial))
        result = final_state["result"]
        if result is None:
            # Can't happen: "draft" always sets "result" before END -- raised rather than
            # asserted so it survives -O, same posture as CorrectiveRagService.answer()'s and
            # ModelSelectionAgent.select()'s equivalent guards.
            raise RuntimeError("orchestrator graph reached END without producing a result")
        return result

    # -- graph construction --------------------------------------------------------------

    def _build_graph(self) -> Any:  # noqa: ANN401 -- only ever used via the narrow .invoke()
        # call above; see CorrectiveRagService._build_graph's identical comment.
        graph: StateGraph[_State] = StateGraph(_State)
        graph.add_node("plan", self._plan)
        graph.add_node("run_specialist", self._run_specialist)
        graph.add_node("draft", self._draft)
        graph.add_node("verify", self._verify)
        graph.add_node("revise_draft", self._revise_draft)
        graph.add_node("finalize", self._finalize)
        graph.set_entry_point("plan")
        graph.add_conditional_edges("plan", self._fan_out, ["run_specialist", "draft"])
        graph.add_edge("run_specialist", "draft")
        graph.add_edge("draft", "verify")
        graph.add_conditional_edges(
            "verify", self._route_after_verify, ["finalize", "revise_draft"]
        )
        graph.add_edge("revise_draft", "draft")
        graph.add_edge("finalize", END)
        return graph.compile()

    # -- nodes -----------------------------------------------------------------------------

    def _plan(self, state: _State) -> dict[str, object]:
        prompt = load_prompt("orchestrator_plan")
        system = prompt.render_system(roster_block=_roster_block())
        messages: list[MessageParam] = [
            {
                "role": "user",
                "content": prompt.render_user(question=state["question"], role=state["role"]),
            }
        ]
        planned, metrics = cast(
            "tuple[OrchestratorPlan, CallMetrics]",
            self._llm.structured(
                model=prompt.model,
                system=system,
                messages=messages,
                output_model=OrchestratorPlan,
                max_tokens=prompt.max_tokens,
                effort=self._effort or prompt.effort,
                cache_system=prompt.cache_system,
            ),
        )
        tasks = [
            TaskSpec(
                task_id=f"t{i}",
                agent=t.agent,
                objective=t.objective,
                constraints=t.constraints,
                role=state["role"],
                budget=self._default_budget,
            )
            for i, t in enumerate(planned.tasks)
        ]
        return {
            "plan": tasks,
            "total_cost_usd": state["total_cost_usd"] + metrics.cost_usd,
            "total_latency_s": state["total_latency_s"] + metrics.total_latency_s,
            "llm_calls": state["llm_calls"] + 1,
        }

    def _fan_out(self, state: _State) -> list[Send]:
        """Routing function (not a node): dispatches one `Send` per planned task, so
        independent tasks run as separate parallel invocations of `run_specialist` -- the
        `Send` mechanism LangGraph gives for exactly this (C3's "Send fan-out for independent
        tasks"). Each `Send` carries its own `current_task`, read back out in `_run_specialist`.

        An empty plan (the question needed no specialist) sends straight to `draft` instead --
        `run_specialist` is a no-op for zero tasks, and a conditional-edge router that returns
        no `Send` at all leaves the graph with nothing left to traverse, since `run_specialist`
        never runs to carry it on to `draft` via the static edge.
        """
        if not state["plan"]:
            return [Send("draft", state)]
        return [
            Send("run_specialist", {**state, "current_task": task}) for task in state["plan"]
        ]

    def _run_specialist(self, state: _State) -> dict[str, object]:
        task = state["current_task"]
        if task is None:
            # Can't happen: _fan_out never sends without a task. Raised, not asserted, for the
            # same -O-survival reason as the guards above.
            raise RuntimeError("run_specialist invoked with no current_task")
        executor = self._executors.get(task.agent)
        if executor is None:
            result = AgentResult(
                task_id=task.task_id,
                agent=task.agent,
                status="failed",
                findings=f"no executor registered for agent '{task.agent}'",
                gaps=[f"no executor registered for agent '{task.agent}'"],
                confidence="low",
            )
            return {"results": [result]}

        t0 = time.monotonic()
        try:
            result = executor(task)
        except Exception as exc:  # noqa: BLE001 -- one specialist's failure must not crash the
            # whole plan; see module docstring.
            result = AgentResult(
                task_id=task.task_id,
                agent=task.agent,
                status="failed",
                findings=f"specialist raised: {exc}",
                gaps=[str(exc)],
                confidence="low",
                latency_s=time.monotonic() - t0,
            )
        return {"results": [result]}

    def _draft(self, state: _State) -> dict[str, object]:
        results = state["results"]
        findings_block = "\n".join(
            f"[{r.task_id}] {r.agent} (status={r.status}, confidence={r.confidence}): "
            f"{r.findings}" + (f" | gaps: {'; '.join(r.gaps)}" if r.gaps else "")
            for r in results
        ) or "(no specialists were needed for this question)"

        # Only present on a redraft (loop back from _revise_draft); on the first pass the
        # specialists haven't been second-guessed yet, so the prompt gets a plain default line
        # rather than an empty section -- same reasoning the module docstring gives for
        # `orchestrator_draft`'s feedback_block.
        feedback_block = (
            f"The previous draft failed verification -- fix this: {state['verify_feedback']}"
            if state["verify_feedback"]
            else "This is the first draft; no prior verifier feedback."
        )

        prompt = load_prompt("orchestrator_draft")
        system = prompt.render_system(role=state["role"])
        messages: list[MessageParam] = [
            {
                "role": "user",
                "content": prompt.render_user(
                    question=state["question"],
                    findings_block=findings_block,
                    feedback_block=feedback_block,
                ),
            }
        ]
        draft, metrics = cast(
            "tuple[DraftAnswer, CallMetrics]",
            self._llm.structured(
                model=prompt.model,
                system=system,
                messages=messages,
                output_model=DraftAnswer,
                max_tokens=prompt.max_tokens,
                effort=self._effort or prompt.effort,
                cache_system=prompt.cache_system,
            ),
        )
        return {
            "draft": draft,
            "total_cost_usd": state["total_cost_usd"] + metrics.cost_usd,
            "total_latency_s": state["total_latency_s"] + metrics.total_latency_s,
            "llm_calls": state["llm_calls"] + 1,
        }

    def _verify(self, state: _State) -> dict[str, object]:
        draft = state["draft"]
        if draft is None:
            # Can't happen: "draft" always runs before "verify". Raised, not asserted, for the
            # same -O-survival reason as the other guards in this module.
            raise RuntimeError("verify invoked with no draft")

        results = state["results"]
        findings_block = "\n".join(
            f"[{r.task_id}] {r.agent} (status={r.status}, confidence={r.confidence}): "
            f"{r.findings}" + (f" | gaps: {'; '.join(r.gaps)}" if r.gaps else "")
            for r in results
        ) or "(no specialists were needed for this question)"

        prompt = load_prompt("orchestrator_verify")
        system = prompt.render_system(
            question=state["question"],
            findings_block=findings_block,
            draft_answer=draft.answer,
            cited_tasks=", ".join(draft.cited_tasks) or "(none cited)",
        )
        messages: list[MessageParam] = [{"role": "user", "content": prompt.render_user()}]
        verdict, metrics = cast(
            "tuple[VerifierVerdict, CallMetrics]",
            self._llm.structured(
                model=prompt.model,
                system=system,
                messages=messages,
                output_model=VerifierVerdict,
                max_tokens=prompt.max_tokens,
                effort=self._effort or prompt.effort,
                cache_system=prompt.cache_system,
            ),
        )
        return {
            "last_verdict": verdict,
            "total_cost_usd": state["total_cost_usd"] + metrics.cost_usd,
            "total_latency_s": state["total_latency_s"] + metrics.total_latency_s,
            "llm_calls": state["llm_calls"] + 1,
        }

    def _route_after_verify(self, state: _State) -> str:
        """Pure routing function (no LLM call, no state mutation) -- mirrors
        `ModelSelectionAgent._route_after_critique`. Finalizes on a pass, or once
        `MAX_VERIFICATION_LOOPS` redrafts have already been spent; otherwise loops back for
        one more attempt via `_revise_draft`.
        """
        verdict = state["last_verdict"]
        if verdict is not None and verdict.passed:
            return "finalize"
        if state["verify_attempt"] >= MAX_VERIFICATION_LOOPS:
            return "finalize"
        return "revise_draft"

    def _revise_draft(self, state: _State) -> dict[str, object]:
        """Pure bookkeeping node (no LLM call) -- mirrors `ModelSelectionAgent._revise`: turns
        the verifier's verdict into feedback text for the next `_draft` pass and advances the
        retry counter.
        """
        verdict = state["last_verdict"]
        feedback_parts: list[str] = []
        if verdict is not None:
            if verdict.feedback:
                feedback_parts.append(verdict.feedback)
            if verdict.contradictions:
                feedback_parts.append(
                    "Unresolved contradictions: " + "; ".join(verdict.contradictions)
                )
        return {
            "verify_feedback": " ".join(feedback_parts) or "verification failed",
            "verify_attempt": state["verify_attempt"] + 1,
        }

    def _finalize(self, state: _State) -> dict[str, object]:
        draft = state["draft"]
        if draft is None:
            # Can't happen: "verify" (and therefore "finalize") only ever runs after "draft"
            # has set it. Raised, not asserted, for the same -O-survival reason as above.
            raise RuntimeError("finalize invoked with no draft")
        results = state["results"]
        verdict = state["last_verdict"]

        result = OrchestratorResult(
            question=state["question"],
            role=state["role"],
            plan=state["plan"],
            results=results,
            answer=draft.answer,
            conflicts_noted=draft.conflicts_noted,
            verified=bool(verdict is not None and verdict.passed),
            verify_attempts=state["verify_attempt"],
            total_cost_usd=state["total_cost_usd"] + sum(r.cost_usd for r in results),
            total_latency_s=state["total_latency_s"] + sum(r.latency_s for r in results),
            llm_calls=state["llm_calls"] + sum(r.llm_calls for r in results),
        )
        return {"result": result}


__all__ = [
    "MAX_VERIFICATION_LOOPS",
    "DraftAnswer",
    "Orchestrator",
    "OrchestratorPlan",
    "OrchestratorResult",
    "PlannedTask",
    "SpecialistExecutor",
    "VerifierVerdict",
]
