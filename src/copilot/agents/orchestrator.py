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

**Day 6 step 5: per-agent budgets, enforced.** `TaskSpec.budget` (an `AgentBudget`) was defined
in step 1 but only ever checked by `AgentResult.exceeds()`, which nothing called -- step 5 is
that call site. `_run_specialist` now (a) waits on the executor through a thread pool bounded by
`budget.max_latency_s`, turning a stuck specialist into a `status="failed"` result instead of an
unbounded hang (the Orchestrator stops *waiting*; it cannot forcibly stop arbitrary synchronous
Python code, so a runaway specialist's thread may still be running in the background -- same
honest limitation `concurrent.futures`-based timeouts always have), and (b) downgrades an
otherwise-`ok` result to `partial` with the specific overage named in `gaps` when
`AgentResult.exceeds(budget)` is true, so a specialist that quietly blew its cost/call budget
is never reported as if nothing happened.

**Day 7 step 4: the Guardian, non-bypassable.** `finalize` no longer edges straight to `END`;
it now edges to a new `guardian` node (`copilot.guardrails.guardian.Guardian`). There is exactly
one path through this graph from `plan` to `END`, and it always passes through `guardian` --
see `test_orchestrator.py`'s topology test for the proof. `OrchestratorResult.answer` is the
Guardian's `safe_answer` by the time `answer()` returns it to a caller; the full verdict is kept
on `OrchestratorResult.guardian_verdict`.

**Day 7 step 5: the approval gate (master prompt C5).** An Action draft (a renegotiation email,
a reorder recommendation -- `run_action` never sends anything itself) that the Guardian didn't
already BLOCK/ESCALATE stops one node short of `END`: `_approval_gate` calls LangGraph's
`interrupt()`, pausing the graph with the draft and verdict as the interrupt payload, until a
human with the `approver`/`admin` role calls `resume_approval()`. `_route_after_guardian` is the
conditional edge that decides whether a run needs this stop at all -- no Action draft, or the
Guardian already BLOCKed/ESCALATEd it, routes straight to `END` instead, same as before this
step. `interrupt()`/`Command(resume=...)` require a checkpointer (confirmed with a throwaway
smoke script against `SqliteSaver` before wiring this in -- resuming without one raises
`RuntimeError` from LangGraph itself); an `Orchestrator` built without `checkpoint_path` (most
existing tests, and any one-shot caller that never intends to resume a paused run) skips the
gate entirely rather than pausing on a run nothing can ever resume -- same "real thing needs
real infrastructure, skip it gracefully otherwise" posture `_run_specialist`'s budget timeouts
and Day 6's Studio cut-first already take. An `edit` decision is re-run through
`self._guardian.review()` before its text is accepted, because an approver's edit is new,
unreviewed text -- see `_approval_gate`'s own docstring. `resume_approval()` checks
`approver_role` in Python *before* touching the graph at all, so a non-approver can't resume a
paused thread even by guessing its `thread_id`.

**Day 7 step 6: the input gate.** `answer()`'s first line of work, before `plan` or anything
else: `self._input_gate.review(question, role)` (`copilot.guardrails.input_gate.InputGate`) --
kill switch, input length, injection heuristics, scope, rate limit, daily spend cap, cheapest
first. A BLOCK returns an `OrchestratorResult` with the gate's safe message straight away; the
graph never even starts, so nothing was spent. On a normal run, `answer()` records the real
`total_cost_usd` the run spent against the role's daily cap once it's known (`InputGate.
record_spend`) -- the gate can only ever check *past* spend against the cap, since it runs before
this request's own cost exists yet.
"""

from __future__ import annotations

import operator
import sqlite3
import time
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Annotated, Any, Literal, TypedDict, cast

from anthropic.types import MessageParam
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, Send, interrupt
from langsmith.run_helpers import LangSmithExtra
from pydantic import BaseModel, Field

from copilot.agents.contracts import AgentBudget, AgentName, AgentResult, TaskSpec
from copilot.guardrails.audit_log import log_approval, log_decision
from copilot.guardrails.canary import canary_line
from copilot.guardrails.guardian import Guardian, GuardianVerdict
from copilot.guardrails.input_gate import GateVerdict as InputGateVerdict
from copilot.guardrails.input_gate import InputGate
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


class PendingReview(BaseModel):
    """Day 8, ADR-006 question 2: set on `OrchestratorResult` whenever the Guardian's outcome is
    ESCALATE, so a caller (the `/ask` API, the UI) can render a visible "pending review" status
    instead of the Day-7-shipped behaviour of silently withholding the result until someone
    manually finds it in `guardian_log.jsonl`. `answer` on the result is still the Guardian's
    `_ESCALATE_MESSAGE` text either way -- this is the structured, reason-coded companion to it,
    not a replacement for it.
    """

    review_id: str
    reason_codes: list[str]


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
    # Day 7 step 4: set by the graph's mandatory "guardian" node, the one place between
    # "finalize" and END (see `_build_graph`/the topology test in test_orchestrator.py). `answer`
    # above is already the Guardian's `safe_answer` by the time a caller sees this object --
    # `guardian_verdict` is kept alongside it as the full record (outcome, every finding, reason
    # codes), not a second, possibly-unsafe copy of the original draft.
    guardian_verdict: GuardianVerdict | None = None
    # Day 7 step 5: set by `answer()` when the graph paused inside `_approval_gate` (an Action
    # draft the Guardian allowed/redacted, awaiting an approver) -- `answer` above is still the
    # Guardian's `safe_answer` at that point; it only changes once `resume_approval()` runs.
    pending_approval: bool = False
    approval_decision: Literal["approved", "edited", "rejected"] | None = None
    # Day 7 step 6: set by `answer()` when the input gate blocked this request before the graph
    # ever ran -- `plan`/`results` stay empty and `total_cost_usd` stays 0.0 in that case, since
    # nothing was spent. `None` means the gate allowed the request through (its ALLOW verdict
    # isn't worth keeping -- there's nothing to show for it).
    input_gate_verdict: InputGateVerdict | None = None
    # Day 8, ADR-006 question 2: set by `_guardian_node` when `guardian_verdict.outcome ==
    # "escalate"` -- see `PendingReview`'s own docstring. `None` for every other outcome.
    pending_review: PendingReview | None = None


class StreamEvent(BaseModel):
    """Day 8 step 3: one update from `Orchestrator.stream_answer()` -- a thin, already-typed
    wrapper the API's `/ask` SSE endpoint serializes straight onto the wire, one JSON object per
    server-sent event, no translation layer in `copilot.api` needing to know this graph's node
    names or internal state shape.

    `type="node"` fires once per graph node that actually ran (`node` names one of this
    module's own node methods -- "plan", "run_specialist", "draft", "verify", "revise_draft",
    "finalize", "guardian", "approval_gate" -- in the order LangGraph's own `.stream(stream_mode
    ="updates")` reports them, which is execution order). It carries no payload beyond the name:
    the point is "the agent is now doing X", a progress indicator for a caller who would
    otherwise stare at a blank screen for the seconds a multi-specialist run can take, not a
    partial answer to render early (the Guardian hasn't seen anything yet).

    `type="result"` fires exactly once, last, carrying the same `OrchestratorResult` `answer()`
    has always returned -- `pending_review`/`pending_approval` on it are what the caller checks
    for an ESCALATE-pending or approval-pending run, same fields, same meaning, whether reached
    through `answer()` or `stream_answer()`.
    """

    type: Literal["node", "result"]
    node: str | None = None
    result: OrchestratorResult | None = None


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
    draft -> verify loop, compiled once as a LangGraph graph in `__init__` -- same construction
    pattern `CorrectiveRagService`/`ModelSelectionAgent` already use.

    **Day 6 step 6: a local SQLite checkpointer.** Passing `checkpoint_path` compiles the graph
    with a `SqliteSaver` over that file, so a run's state is durable across process restarts and
    inspectable afterwards (e.g. with `sqlite3 <path> "select * from checkpoints"`) -- the thing
    LangGraph Studio would otherwise visualize; Studio itself is this step's cut-first item per
    the sprint doc (an external tool to point at this process, not code to build). `answer()`
    then takes an optional `thread_id` (LangGraph's checkpoint key) so a caller can resume or
    inspect one specific run; a fresh one is generated when the caller doesn't need to.

    **Day 8 step 7: a pre-built checkpointer, for Postgres.** Pass `checkpointer` instead of
    `checkpoint_path` to compile the graph against any `BaseCheckpointSaver` the caller already
    constructed -- a `PostgresSaver` over the deployed Postgres instance, in the API server's
    case (`copilot.api.dependencies.get_orchestrator`), so checkpoint state survives a process
    restart or a redeploy rather than living on one container's local disk. Building *which*
    checkpointer, and from what connection string, is deliberately the caller's job, not this
    class's -- this module stays storage-agnostic and only ever calls the `BaseCheckpointSaver`
    interface. `checkpoint_path` is kept, unchanged, for local dev and every existing test: it's
    simpler than standing up Postgres for a unit test, and SQLite's simplicity is exactly the
    point there. If both are passed, `checkpointer` wins.
    """

    def __init__(
        self,
        llm: LLMClient,
        executors: dict[AgentName, SpecialistExecutor],
        effort: Effort | None = None,
        default_budget: AgentBudget | None = None,
        checkpoint_path: str | None = None,
        checkpointer: BaseCheckpointSaver[str] | None = None,
        guardian: Guardian | None = None,
        input_gate: InputGate | None = None,
    ) -> None:
        self._llm = llm
        self._executors = executors
        self._effort = effort
        self._default_budget = default_budget or AgentBudget()
        self._checkpointer = checkpointer or (
            SqliteSaver(sqlite3.connect(checkpoint_path, check_same_thread=False))
            if checkpoint_path is not None
            else None
        )
        # Day 7 step 4: constructed once (same posture as `self._llm`/`self._executors` --
        # expensive setup, cheap reuse), injected rather than hardcoded so tests can pass a
        # Guardian built from a fake/minimal policy without touching the real
        # policies/disclosure.yaml.
        self._guardian = guardian or Guardian()
        # Day 7 step 6: same posture -- injected so tests can pass an InputGate built with a
        # fake RateLimiter/SpendTracker rather than touching real settings or `data/spend/`.
        self._input_gate = input_gate or InputGate()
        self._graph = self._build_graph()

    def answer(self, question: str, role: Role, thread_id: str | None = None) -> OrchestratorResult:
        """Run to completion and return the final result -- the pre-Day-8 interface, unchanged
        for every existing caller. Drains `stream_answer()` rather than duplicating its gate/
        graph/spend-recording logic; see that method for what actually runs.
        """
        result: OrchestratorResult | None = None
        for event in self.stream_answer(question, role, thread_id=thread_id):
            if event.type == "result":
                result = event.result
        if result is None:
            # Can't happen: stream_answer() always yields exactly one type="result" event,
            # whichever path it takes (gate block, normal finish, or paused for approval).
            # Raised rather than asserted so it survives -O, same posture as the guard it
            # replaces and CorrectiveRagService.answer()'s/ModelSelectionAgent.select()'s.
            raise RuntimeError("stream_answer() finished without yielding a result event")
        return result

    def stream_answer(
        self, question: str, role: Role, thread_id: str | None = None
    ) -> Iterator[StreamEvent]:
        """Day 8 step 3: the same run `answer()` does, but yielding a `StreamEvent` as each
        graph node completes, for the API's `/ask` SSE endpoint to forward live instead of the
        caller waiting on one blocking call for the whole multi-specialist run. `answer()` is
        now just this generator, drained for its final event -- there is exactly one place the
        input-gate check, the graph run and the spend recording happen, not two copies that
        could drift.

        Yields zero or more `type="node"` events (one per node LangGraph's own `.stream(stream_
        mode="updates")` reports, in execution order) followed by exactly one `type="result"`
        event, whether the run finished normally, was blocked at the input gate before "plan"
        ever ran, or paused inside "approval_gate" awaiting a human (see `StreamEvent`'s own
        docstring for what each carries).
        """
        # Day 7 step 6: the input gate runs before anything else -- a blocked request never
        # reaches "plan", never spends an LLM call, and never touches a specialist. See
        # `copilot.guardrails.input_gate`'s module docstring for why this list of checks and why
        # BLOCK-only (no redact/escalate) makes sense on the input side.
        gate_verdict = self._input_gate.review(question, role)
        if gate_verdict.outcome == "block":
            yield StreamEvent(
                type="result",
                result=OrchestratorResult(
                    question=question,
                    role=role,
                    answer=gate_verdict.message,
                    input_gate_verdict=gate_verdict,
                ),
            )
            return
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
        config: dict[str, Any] = {}
        if self._checkpointer is not None:
            config = {"configurable": {"thread_id": thread_id or str(uuid.uuid4())}}
        last_result: OrchestratorResult | None = None
        interrupted = False
        for update in self._graph.stream(initial, config=config, stream_mode="updates"):
            for node_name, partial in update.items():
                if node_name == "__interrupt__":
                    # Day 7 step 5: the graph paused inside "approval_gate" rather than reaching
                    # END -- "partial" here is LangGraph's own Interrupt payload, not this
                    # graph's state; nothing new to report as a node event, but the already-
                    # captured "result" (set by "guardian", the node just before this one on
                    # every path that can pause) needs flagging before it's handed back.
                    interrupted = True
                    continue
                yield StreamEvent(type="node", node=node_name)
                if isinstance(partial, dict) and partial.get("result") is not None:
                    last_result = partial["result"]
        if last_result is None:
            # Can't happen: "draft" always sets "result" before END -- raised rather than
            # asserted so it survives -O, same posture as CorrectiveRagService.answer()'s and
            # ModelSelectionAgent.select()'s equivalent guards.
            raise RuntimeError("orchestrator graph reached END without producing a result")
        result = last_result
        if interrupted:
            result = result.model_copy(update={"pending_approval": True})
        # Day 7 step 6: the spend-cap half of the gate. Recorded only once the run has actually
        # finished (not before the graph starts, and not again on a resumed/paused thread --
        # resume_approval() doesn't call this), against the real total this specific run spent,
        # not an estimate.
        self._input_gate.record_spend(role, result.total_cost_usd)
        yield StreamEvent(type="result", result=result)

    def resume_approval(
        self,
        thread_id: str,
        decision: Literal["approve", "edit", "reject"],
        *,
        approver_role: Role,
        edited_answer: str | None = None,
    ) -> OrchestratorResult:
        """Day 7 step 5: the only way a paused Action-draft approval gate is ever resumed.

        `approver_role` is checked here, in plain Python, *before* `Command(resume=...)` ever
        touches the graph -- master prompt C5 names "approver role" as who may act on this gate,
        and the check has to live on this side of the boundary: `_approval_gate` only runs again
        once this call has already decided to resume it, so putting the check inside that node
        would be too late to stop an unauthorized resume from happening at all. A caller who
        doesn't hold `thread_id` has no way to resume anything; one who does but isn't an
        approver/admin is stopped right here, before touching the paused thread's state.
        """
        if approver_role not in ("approver", "admin"):
            raise PermissionError(
                f"role '{approver_role}' may not approve, edit or reject an Action draft "
                "(requires 'approver' or 'admin')"
            )
        if self._checkpointer is None:
            # Can't happen in practice: nothing can be paused-and-resumable without a
            # checkpointer in the first place (answer() never sets pending_approval=True for an
            # Orchestrator built without checkpoint_path). Guarded anyway rather than letting
            # LangGraph's own "Cannot use Command(resume=...) without checkpointer" RuntimeError
            # surface from deeper in the stack.
            raise RuntimeError(
                "resume_approval requires an Orchestrator built with checkpoint_path set"
            )
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        final_state = cast(
            "_State",
            self._graph.invoke(
                Command(resume={"decision": decision, "edited_answer": edited_answer}),
                config=config,
            ),
        )
        result = final_state["result"]
        if result is None:
            # Can't happen: "_approval_gate" always sets "result" before returning. Raised, not
            # asserted, for the same -O-survival reason as the other guards in this module.
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
        graph.add_node("guardian", self._guardian_node)
        graph.add_node("approval_gate", self._approval_gate)
        graph.set_entry_point("plan")
        graph.add_conditional_edges("plan", self._fan_out, ["run_specialist", "draft"])
        graph.add_edge("run_specialist", "draft")
        graph.add_edge("draft", "verify")
        graph.add_conditional_edges(
            "verify", self._route_after_verify, ["finalize", "revise_draft"]
        )
        graph.add_edge("revise_draft", "draft")
        # Day 7 step 4: "guardian" is the single node between "finalize" and END -- every path
        # through this graph reaches END only via "guardian". See `test_orchestrator.py`'s
        # `test_every_path_to_end_passes_through_guardian` for the topology proof.
        graph.add_edge("finalize", "guardian")
        # Day 7 step 5: "guardian" no longer edges straight to END -- an allowed/redacted Action
        # draft routes through "approval_gate" first (`_route_after_guardian` decides per-run;
        # everything else still goes straight to END, same as before this step).
        graph.add_conditional_edges("guardian", self._route_after_guardian, ["approval_gate", END])
        graph.add_edge("approval_gate", END)
        return graph.compile(checkpointer=self._checkpointer)

    # -- nodes -----------------------------------------------------------------------------

    @staticmethod
    def _ls_extra(node: str, role: Role, **extra_tags: str) -> LangSmithExtra:
        """Day 6 step 6: per-agent LangSmith run names and tags. `LLMClient.structured`/
        `.complete` are already `@traceable`, but every call surfaced under the same generic
        name/tags -- indistinguishable in a trace. `langsmith_extra` is `traceable`'s own
        call-time override (no change needed to `LLMClient` itself): it renames this one run
        `orchestrator.<node>` and tags it `orchestrator`, the node, and the requesting role, so
        a LangSmith trace can be filtered by agent the same way `AgentResult.agent` lets code
        filter by agent. A no-op (not an error) when tracing isn't configured -- same
        `langsmith_tracing`/`langsmith_api_key` gate `LLMClient._configure_tracing` already
        checks.
        """
        tags = ["orchestrator", node, f"role:{role}", *(f"{k}:{v}" for k, v in extra_tags.items())]
        return cast("LangSmithExtra", {"name": f"orchestrator.{node}", "tags": tags})

    def _plan(self, state: _State) -> dict[str, object]:
        prompt = load_prompt("orchestrator_plan")
        system = prompt.render_system(roster_block=_roster_block()) + canary_line(
            "orchestrator_plan"
        )
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
                prompt_name=prompt.name,
                prompt_version=prompt.version,
                langsmith_extra=self._ls_extra("plan", state["role"]),
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
        return [Send("run_specialist", {**state, "current_task": task}) for task in state["plan"]]

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

        t0 = time.perf_counter()
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(executor, task)
                result = future.result(timeout=task.budget.max_latency_s)
        except FutureTimeoutError:
            result = AgentResult(
                task_id=task.task_id,
                agent=task.agent,
                status="failed",
                findings=(
                    f"specialist exceeded its {task.budget.max_latency_s:.0f}s latency budget"
                ),
                gaps=[f"timed out after {task.budget.max_latency_s:.0f}s"],
                confidence="low",
                latency_s=time.perf_counter() - t0,
            )
        except Exception as exc:  # noqa: BLE001 -- one specialist's failure must not crash the
            # whole plan; see module docstring.
            result = AgentResult(
                task_id=task.task_id,
                agent=task.agent,
                status="failed",
                findings=f"specialist raised: {exc}",
                gaps=[str(exc)],
                confidence="low",
                latency_s=time.perf_counter() - t0,
            )
        else:
            if result.status == "ok" and result.exceeds(task.budget):
                overages = []
                if result.cost_usd > task.budget.max_cost_usd:
                    overages.append(
                        f"cost ${result.cost_usd:.4f} > ${task.budget.max_cost_usd:.4f}"
                    )
                if result.latency_s > task.budget.max_latency_s:
                    overages.append(
                        f"latency {result.latency_s:.1f}s > {task.budget.max_latency_s:.1f}s"
                    )
                if result.llm_calls > task.budget.max_llm_calls:
                    overages.append(f"llm_calls {result.llm_calls} > {task.budget.max_llm_calls}")
                result = result.model_copy(
                    update={
                        "status": "partial",
                        "gaps": [*result.gaps, "exceeded budget: " + "; ".join(overages)],
                    }
                )
        return {"results": [result]}

    def _draft(self, state: _State) -> dict[str, object]:
        results = state["results"]
        findings_block = (
            "\n".join(
                f"[{r.task_id}] {r.agent} (status={r.status}, confidence={r.confidence}): "
                f"{r.findings}" + (f" | gaps: {'; '.join(r.gaps)}" if r.gaps else "")
                for r in results
            )
            or "(no specialists were needed for this question)"
        )

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
        system = prompt.render_system(role=state["role"]) + canary_line("orchestrator_draft")
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
                prompt_name=prompt.name,
                prompt_version=prompt.version,
                langsmith_extra=self._ls_extra(
                    "draft", state["role"], attempt=str(state["verify_attempt"])
                ),
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
        findings_block = (
            "\n".join(
                f"[{r.task_id}] {r.agent} (status={r.status}, confidence={r.confidence}): "
                f"{r.findings}" + (f" | gaps: {'; '.join(r.gaps)}" if r.gaps else "")
                for r in results
            )
            or "(no specialists were needed for this question)"
        )

        prompt = load_prompt("orchestrator_verify")
        system = prompt.render_system(
            question=state["question"],
            findings_block=findings_block,
            draft_answer=draft.answer,
            cited_tasks=", ".join(draft.cited_tasks) or "(none cited)",
        ) + canary_line("orchestrator_verify")
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
                prompt_name=prompt.name,
                prompt_version=prompt.version,
                langsmith_extra=self._ls_extra(
                    "verify", state["role"], attempt=str(state["verify_attempt"])
                ),
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

    def _guardian_node(self, state: _State) -> dict[str, object]:
        """Day 7 steps 1/3/4: the mandatory final pass. Reads the `OrchestratorResult` `finalize`
        just produced, runs every Guardian check against it, and replaces `answer` with the
        verdict's `safe_answer` -- callers of `Orchestrator.answer()` only ever see Guardian-
        reviewed text, never the raw draft. The full verdict (every finding, not just the
        winning outcome) is kept on `guardian_verdict` and written to the audit log
        (`copilot.guardrails.audit_log`) before this node returns; a logging failure there is
        reported via `log_decision`'s own return value, never raised into the graph (an audit
        write problem must not itself block an already-reviewed answer from reaching the user).
        """
        result = state["result"]
        if result is None:
            # Can't happen: "guardian" only ever runs after "finalize" has set "result" (the
            # same -O-survival guard `answer()`'s own check at the bottom of this class uses).
            raise RuntimeError("guardian invoked with no result to review")
        verdict = self._guardian.review(result)
        # Day 8, ADR-006 question 2: generate the join key *before* logging, so the audit-log
        # row and the `PendingReview` the caller sees carry the identical id -- only when this
        # decision actually needs a reviewer; every other outcome logs review_id=None (nothing
        # to review, nothing to join on).
        review_id = str(uuid.uuid4()) if verdict.outcome == "escalate" else None
        log_decision(verdict, question=result.question, role=result.role, review_id=review_id)
        pending_review = (
            PendingReview(review_id=review_id, reason_codes=verdict.reason_codes)
            if review_id is not None
            else None
        )
        reviewed = result.model_copy(
            update={
                "answer": verdict.safe_answer,
                "guardian_verdict": verdict,
                "pending_review": pending_review,
            }
        )
        return {"result": reviewed}

    def _route_after_guardian(self, state: _State) -> str:
        """Pure routing function (no LLM call, no state mutation, mirrors
        `_route_after_verify`): decides whether this run needs the human approval gate at all.

        Three independent reasons route straight to `END` instead of `"approval_gate"`:
        (a) no checkpointer -- `interrupt()`/`Command(resume=...)` need one to actually pause-
        and-resume (confirmed against a real `SqliteSaver` before this was wired in; without
        one, LangGraph itself raises `RuntimeError` on resume, and a pause nothing can ever
        resume is worse than skipping it); (b) no Action draft in this run's results --
        `run_action` is the only specialist that drafts an outbound renegotiation email/reorder
        recommendation, so nothing here needs a human's sign-off before being shown; (c) the
        Guardian already BLOCKed or ESCALATEd -- a draft that already failed Guardian review
        isn't "awaiting approval", it's already been handled, and routing it to the gate would
        put an approver in the position of approving text the user never even sees (`answer` is
        already the Guardian's safe generic message by this point).
        """
        if self._checkpointer is None:
            return END
        result = state["result"]
        if result is None or result.guardian_verdict is None:
            # Can't happen: "guardian" always sets both before this router runs.
            return END
        if result.guardian_verdict.outcome not in ("allow", "redact"):
            return END
        if not any(r.agent == "action" for r in result.results):
            return END
        return "approval_gate"

    def _approval_gate(self, state: _State) -> dict[str, object]:
        """Day 7 step 5: master prompt C5's "Action draft behind interrupt -> Guardian ->
        approver approves/edits/rejects". Only ever reached when `_route_after_guardian` has
        already confirmed there's a checkpointer and an Action draft the Guardian didn't already
        BLOCK/ESCALATE (see that method's docstring) -- so everything below can assume both.

        Calls `interrupt()` with the draft and verdict as the payload, pausing the graph until
        `Orchestrator.resume_approval()` sends back `Command(resume={"decision": ..., "edited_
        answer": ...})`. LangGraph re-runs this node from the top on resume, so everything above
        the `interrupt()` call must stay cheap and side-effect-free -- it is (just reading
        `state["result"]`); nothing here was logged or mutated before the pause.

        **Why an "edit" is re-reviewed, not trusted:** the Guardian already blessed the ORIGINAL
        draft as `safe_answer`. An approver's edited text is new, never-reviewed content -- it
        could just as easily reintroduce a restricted name or PII the original draft never had.
        Re-running `self._guardian.review()` on the edited result keeps the same non-bypassable
        guarantee step 4 established: no text reaches `answer` without a Guardian pass over it,
        approver edits included.
        """
        result = state["result"]
        if result is None:
            # Can't happen: "_approval_gate" only ever runs after "guardian" has set "result".
            raise RuntimeError("approval_gate invoked with no result to review")

        verdict = result.guardian_verdict
        decision_payload = interrupt(
            {
                "question": result.question,
                "draft": result.answer,
                "guardian_outcome": verdict.outcome if verdict else None,
                "reason_codes": verdict.reason_codes if verdict else [],
            }
        )
        decision = decision_payload.get("decision") if isinstance(decision_payload, dict) else None

        if decision == "reject":
            updated = result.model_copy(
                update={
                    "answer": "This action draft was rejected by an approver and will not be sent.",
                    "approval_decision": "rejected",
                }
            )
            log_approval(
                question=updated.question,
                role=updated.role,
                decision="rejected",
                final_answer=updated.answer or "",
            )
            return {"result": updated}

        if decision == "edit":
            edited_text = (
                decision_payload.get("edited_answer") or result.answer
                if isinstance(decision_payload, dict)
                else result.answer
            )
            edited_result = result.model_copy(update={"answer": edited_text})
            new_verdict = self._guardian.review(edited_result)
            # Same ADR-006-question-2 join-key logic as `_guardian_node` above: an approver's
            # edit can re-trigger ESCALATE just as easily as it could reintroduce a leak, and
            # that needs the same visible pending-review status, not a second silent path.
            new_review_id = str(uuid.uuid4()) if new_verdict.outcome == "escalate" else None
            log_decision(
                new_verdict,
                question=edited_result.question,
                role=edited_result.role,
                review_id=new_review_id,
            )
            new_pending_review = (
                PendingReview(review_id=new_review_id, reason_codes=new_verdict.reason_codes)
                if new_review_id is not None
                else None
            )
            updated = edited_result.model_copy(
                update={
                    "answer": new_verdict.safe_answer,
                    "guardian_verdict": new_verdict,
                    "approval_decision": "edited",
                    "pending_review": new_pending_review,
                }
            )
            log_approval(
                question=updated.question,
                role=updated.role,
                decision="edited",
                final_answer=updated.answer or "",
            )
            return {"result": updated}

        # Anything else (including the expected "approve") keeps the Guardian's safe_answer
        # as-is -- approving means "send what the Guardian already allowed/redacted", not a
        # fresh draft.
        updated = result.model_copy(update={"approval_decision": "approved"})
        log_approval(
            question=updated.question,
            role=updated.role,
            decision="approved",
            final_answer=updated.answer or "",
        )
        return {"result": updated}


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
