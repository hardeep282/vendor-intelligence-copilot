"""Tests for the Orchestrator (Day 6 steps 3-5): typed plan, Send fan-out, join, draft,
logged-only conflict handling, the Verifier's grounding/citation/sufficiency check with its
redraft loop, and per-agent budget enforcement (timeout -> failed, overage -> partial). No
network, no real API key, same convention as tests/test_model_selection_agent.py and
tests/test_rag_corrective.py: the LLM side is FakeMessagesResource, queued in the exact order
the graph is expected to call it in; specialists are fake executors (step 2's own correctness is
covered in tests/test_agent_specialists.py).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from copilot.agents.contracts import AgentBudget, AgentResult, TaskSpec
from copilot.agents.orchestrator import MAX_VERIFICATION_LOOPS, Orchestrator
from copilot.guardrails.input_gate import InputGate
from copilot.llm.client import LLMClient
from tests.fakes.anthropic_fakes import FakeMessagesResource, structured_response


def _llm_with(responses: list[object]) -> LLMClient:
    llm = LLMClient(api_key="sk-test-not-real")
    llm._client.messages = FakeMessagesResource(responses)  # type: ignore[attr-defined]
    return llm


def _verdict(
    grounded: bool = True,
    citations_ok: bool = True,
    sufficient: bool = True,
    contradictions: list[str] | None = None,
    feedback: str = "",
) -> dict[str, object]:
    return {
        "grounded": grounded,
        "citations_ok": citations_ok,
        "sufficient": sufficient,
        "contradictions": contradictions or [],
        "feedback": feedback,
    }


_PASSING_VERDICT = structured_response(_verdict())


def _ok(agent: str, findings: str, data_classes: list[str] | None = None) -> AgentResult:
    def _run(spec: TaskSpec) -> AgentResult:
        return AgentResult(
            task_id=spec.task_id,
            agent=agent,  # type: ignore[arg-type]
            status="ok",
            findings=findings,
            data_classes=data_classes or [],  # type: ignore[arg-type]
            cost_usd=0.001,
            latency_s=0.1,
            llm_calls=1,
        )

    return _run  # type: ignore[return-value]


def test_single_specialist_plan_runs_end_to_end() -> None:
    llm = _llm_with(
        [
            structured_response(
                {
                    "tasks": [
                        {
                            "agent": "data_analyst",
                            "objective": "total freight cost",
                            "constraints": {},
                        }
                    ]
                }
            ),
            structured_response(
                {
                    "answer": "Total freight cost is $1.64M.",
                    "cited_tasks": ["t0"],
                    "conflicts_noted": [],
                }
            ),
            _PASSING_VERDICT,
        ]
    )
    orch = Orchestrator(
        llm, executors={"data_analyst": _ok("data_analyst", "freight is $1.64M", ["internal"])}
    )

    result = orch.answer("What is total freight cost?", role="analyst")

    assert len(result.plan) == 1
    assert result.plan[0].agent == "data_analyst"
    assert len(result.results) == 1
    assert result.results[0].status == "ok"
    assert result.answer == "Total freight cost is $1.64M."
    assert result.conflicts_noted == []
    assert result.verified is True
    assert result.verify_attempts == 0
    # plan(1) + draft(1) + verify(1) + the fake specialist's own llm_calls=1
    assert result.llm_calls == 4


def test_stream_answer_emits_one_node_event_per_executed_node_then_one_result() -> None:
    """Day 8 step 3: `answer()` is now `stream_answer()` drained for its last event -- this
    checks the generator's own contract directly (node events in execution order, exactly one
    trailing result event), the thing the API's SSE endpoint actually forwards.
    """
    llm = _llm_with(
        [
            structured_response(
                {"tasks": [{"agent": "data_analyst", "objective": "x", "constraints": {}}]}
            ),
            structured_response({"answer": "ok", "cited_tasks": ["t0"], "conflicts_noted": []}),
            _PASSING_VERDICT,
        ]
    )
    orch = Orchestrator(llm, executors={"data_analyst": _ok("data_analyst", "x")})

    events = list(orch.stream_answer("x?", role="analyst"))

    node_events = [e for e in events if e.type == "node"]
    result_events = [e for e in events if e.type == "result"]
    assert [e.node for e in node_events] == [
        "plan",
        "run_specialist",
        "draft",
        "verify",
        "finalize",
        "guardian",
    ]
    assert len(result_events) == 1
    assert result_events[0].result is not None
    assert result_events[0].result.answer == "ok"


def test_stream_answer_blocked_by_input_gate_yields_only_a_result_event() -> None:
    """A gate BLOCK never reaches "plan" -- no node events, just the one result event carrying
    the gate's own message, same as `answer()`'s pre-existing blocked-request behaviour."""
    gate = InputGate(kill_switch_enabled=True)
    llm = _llm_with([])
    orch = Orchestrator(llm, executors={}, input_gate=gate)

    events = list(orch.stream_answer("anything", role="analyst"))

    assert all(e.type == "result" for e in events)
    assert len(events) == 1
    assert events[0].result is not None
    assert events[0].result.input_gate_verdict is not None
    assert events[0].result.input_gate_verdict.outcome == "block"


def test_stream_answer_flags_pending_approval_on_the_final_result(tmp_path: Path) -> None:
    """The interrupt itself surfaces as an "__interrupt__" key in the underlying LangGraph
    stream, not a StreamEvent -- this checks it still turns into `pending_approval=True` on the
    one result event the caller actually sees, same as `answer()`'s equivalent check."""
    db_path = str(tmp_path / "checkpoints.sqlite")
    llm = _llm_with(_action_plan_llm())
    orch = Orchestrator(
        llm, executors={"action": _ok("action", "x", ["public"])}, checkpoint_path=db_path
    )

    events = list(orch.stream_answer("x?", role="analyst", thread_id="run-stream-approve"))

    result_events = [e for e in events if e.type == "result"]
    assert len(result_events) == 1
    assert result_events[0].result is not None
    assert result_events[0].result.pending_approval is True


def test_answer_and_stream_answer_agree_on_the_final_result() -> None:
    """Belt-and-suspenders: `answer()` is just `stream_answer()` drained -- confirm they
    actually produce the same OrchestratorResult for the same run, not just that each passes
    its own tests in isolation."""
    llm_for_answer = _llm_with(
        [
            structured_response(
                {"tasks": [{"agent": "data_analyst", "objective": "x", "constraints": {}}]}
            ),
            structured_response({"answer": "ok", "cited_tasks": ["t0"], "conflicts_noted": []}),
            _PASSING_VERDICT,
        ]
    )
    llm_for_stream = _llm_with(
        [
            structured_response(
                {"tasks": [{"agent": "data_analyst", "objective": "x", "constraints": {}}]}
            ),
            structured_response({"answer": "ok", "cited_tasks": ["t0"], "conflicts_noted": []}),
            _PASSING_VERDICT,
        ]
    )
    via_answer = Orchestrator(
        llm_for_answer, executors={"data_analyst": _ok("data_analyst", "x")}
    ).answer("x?", role="analyst")
    stream_events = list(
        Orchestrator(
            llm_for_stream, executors={"data_analyst": _ok("data_analyst", "x")}
        ).stream_answer("x?", role="analyst")
    )
    via_stream = next(e.result for e in stream_events if e.type == "result")

    assert via_stream is not None
    assert via_answer.answer == via_stream.answer
    assert via_answer.verified == via_stream.verified
    assert via_answer.llm_calls == via_stream.llm_calls


def test_two_independent_specialists_fan_out_and_join() -> None:
    llm = _llm_with(
        [
            structured_response(
                {
                    "tasks": [
                        {"agent": "data_analyst", "objective": "freight cost", "constraints": {}},
                        {
                            "agent": "knowledge",
                            "objective": "freight methodology",
                            "constraints": {},
                        },
                    ]
                }
            ),
            structured_response(
                {
                    "answer": "Freight is $1.64M, computed as MAX not SUM per vendor.",
                    "cited_tasks": ["t0", "t1"],
                    "conflicts_noted": [],
                }
            ),
            _PASSING_VERDICT,
        ]
    )
    orch = Orchestrator(
        llm,
        executors={
            "data_analyst": _ok("data_analyst", "freight is $1.64M", ["internal"]),
            "knowledge": _ok("knowledge", "freight is vendor-level, use MAX not SUM", ["public"]),
        },
    )

    result = orch.answer("What is freight cost and how is it computed?", role="analyst")

    assert {t.agent for t in result.plan} == {"data_analyst", "knowledge"}
    # join: both results present, regardless of fan-out dispatch order
    assert {r.agent for r in result.results} == {"data_analyst", "knowledge"}
    assert {r.task_id for r in result.results} == {"t0", "t1"}


def test_empty_plan_still_drafts_an_answer() -> None:
    llm = _llm_with(
        [
            structured_response({"tasks": []}),
            structured_response(
                {
                    "answer": "I don't need any specialist for that -- it's out of scope.",
                    "cited_tasks": [],
                    "conflicts_noted": [],
                }
            ),
            _PASSING_VERDICT,
        ]
    )
    orch = Orchestrator(llm, executors={})

    result = orch.answer("What's the weather today?", role="viewer")

    assert result.plan == []
    assert result.results == []
    assert result.answer is not None


def test_missing_executor_for_a_planned_agent_becomes_a_failed_result_not_a_crash() -> None:
    llm = _llm_with(
        [
            structured_response(
                {"tasks": [{"agent": "action", "objective": "draft an email", "constraints": {}}]}
            ),
            structured_response(
                {
                    "answer": "I could not draft that email -- the drafting tool is unavailable.",
                    "cited_tasks": [],
                    "conflicts_noted": [],
                }
            ),
            _PASSING_VERDICT,
        ]
    )
    orch = Orchestrator(llm, executors={})  # no "action" executor registered

    result = orch.answer("Draft a renegotiation email to DIAGEO.", role="analyst")

    assert len(result.results) == 1
    assert result.results[0].status == "failed"
    assert "no executor registered" in result.results[0].gaps[0]


def test_a_raising_executor_becomes_a_failed_result_not_a_crash() -> None:
    def _raises(spec: TaskSpec) -> AgentResult:
        raise ValueError("snapshot not built")

    llm = _llm_with(
        [
            structured_response(
                {
                    "tasks": [
                        {
                            "agent": "forecasting_risk",
                            "objective": "forecast",
                            "constraints": {},
                        }
                    ]
                }
            ),
            structured_response(
                {
                    "answer": "I could not produce a forecast -- the data isn't available.",
                    "cited_tasks": [],
                    "conflicts_noted": [],
                }
            ),
            _PASSING_VERDICT,
        ]
    )
    orch = Orchestrator(llm, executors={"forecasting_risk": _raises})

    result = orch.answer("Forecast next quarter's demand.", role="analyst")

    assert result.results[0].status == "failed"
    assert "snapshot not built" in result.results[0].gaps[0]


def test_conflicts_noted_by_the_draft_step_are_logged_not_resolved() -> None:
    llm = _llm_with(
        [
            structured_response(
                {
                    "tasks": [
                        {"agent": "data_analyst", "objective": "margin", "constraints": {}},
                        {"agent": "knowledge", "objective": "margin definition", "constraints": {}},
                    ]
                }
            ),
            structured_response(
                {
                    "answer": (
                        "The specialists disagree on blended margin (5.31% vs 28.72%); see note."
                    ),
                    "cited_tasks": ["t0", "t1"],
                    "conflicts_noted": [
                        "data_analyst reports 5.31% (AVG of a ratio column) vs 28.72% "
                        "(ratio of sums) -- see docs/specs/text_to_sql_safety.md"
                    ],
                }
            ),
            _PASSING_VERDICT,
        ]
    )
    orch = Orchestrator(
        llm,
        executors={
            "data_analyst": _ok("data_analyst", "blended margin is 5.31%"),
            "knowledge": _ok("knowledge", "blended margin should be a ratio of sums, 28.72%"),
        },
    )

    result = orch.answer("What is blended margin?", role="analyst")

    assert len(result.conflicts_noted) == 1
    # logged, not re-queried: exactly one plan call, one draft call and one verify call, no extra
    # loop over the conflict -- plus the two fake specialists' own llm_calls=1 each
    assert result.llm_calls == 5


def test_cost_latency_and_calls_sum_across_plan_specialists_and_draft() -> None:
    llm = _llm_with(
        [
            structured_response(
                {"tasks": [{"agent": "data_analyst", "objective": "x", "constraints": {}}]}
            ),
            structured_response({"answer": "ok", "cited_tasks": ["t0"], "conflicts_noted": []}),
            _PASSING_VERDICT,
        ]
    )
    orch = Orchestrator(llm, executors={"data_analyst": _ok("data_analyst", "x", ["internal"])})

    result = orch.answer("x?", role="analyst")

    # 3 LLM calls (plan, draft, verify) at FakeMessagesResource's fixed cost, plus the fake
    # specialist's own 0.001/0.1/1 accounting folded in by the finalize node.
    assert result.llm_calls == 4  # plan(1) + draft(1) + verify(1) + specialist(1)
    assert result.total_cost_usd > 0.001
    assert result.total_latency_s > 0.1


def test_a_failed_verification_triggers_one_redraft_that_then_passes() -> None:
    llm = _llm_with(
        [
            structured_response(
                {"tasks": [{"agent": "data_analyst", "objective": "x", "constraints": {}}]}
            ),
            structured_response(
                {"answer": "freight is about $2M", "cited_tasks": [], "conflicts_noted": []}
            ),
            structured_response(
                _verdict(
                    grounded=False,
                    citations_ok=False,
                    feedback="You said $2M but the finding says $1.64M -- use that figure "
                    "and cite t0.",
                )
            ),
            structured_response(
                {"answer": "freight is $1.64M", "cited_tasks": ["t0"], "conflicts_noted": []}
            ),
            _PASSING_VERDICT,
        ]
    )
    orch = Orchestrator(
        llm, executors={"data_analyst": _ok("data_analyst", "freight is $1.64M", ["internal"])}
    )

    result = orch.answer("What is freight cost?", role="analyst")

    assert result.answer == "freight is $1.64M"
    assert result.verified is True
    assert result.verify_attempts == 1
    # plan(1) + draft(1) + verify(1) + revise + draft(1) + verify(1) + specialist(1)
    assert result.llm_calls == 6


def test_verification_that_never_passes_finalizes_unverified_after_max_loops() -> None:
    llm = _llm_with(
        [
            structured_response(
                {"tasks": [{"agent": "data_analyst", "objective": "x", "constraints": {}}]}
            ),
            structured_response({"answer": "attempt 1", "cited_tasks": [], "conflicts_noted": []}),
            structured_response(_verdict(grounded=False, feedback="still wrong, attempt 1")),
            structured_response({"answer": "attempt 2", "cited_tasks": [], "conflicts_noted": []}),
            structured_response(_verdict(grounded=False, feedback="still wrong, attempt 2")),
            structured_response({"answer": "attempt 3", "cited_tasks": [], "conflicts_noted": []}),
            structured_response(_verdict(grounded=False, feedback="still wrong, attempt 3")),
        ]
    )
    orch = Orchestrator(llm, executors={"data_analyst": _ok("data_analyst", "x", ["internal"])})

    result = orch.answer("x?", role="analyst")

    assert result.verified is False
    assert result.verify_attempts == MAX_VERIFICATION_LOOPS
    # Day 7: an unverified draft is finalized (not looped forever) but then the Guardian
    # ESCALATEs it -- the raw "attempt 3" text never reaches the caller; the safe,
    # human-review-queued message does. The original draft is still visible through
    # `results`/the eval harness if needed; what a real end user sees is the safe copy.
    assert result.guardian_verdict is not None
    assert result.guardian_verdict.outcome == "escalate"
    assert "unverified_grounding" in result.guardian_verdict.reason_codes
    assert result.answer != "attempt 3"
    # Day 8, ADR-006 q2: ESCALATE is now visibly flagged, not just embedded in `answer`'s text --
    # a caller (the /ask API, the UI) can branch on `pending_review` without parsing the message.
    assert result.pending_review is not None
    assert result.pending_review.review_id  # a real, non-empty join key for the audit log
    assert result.pending_review.reason_codes == result.guardian_verdict.reason_codes
    # plan(1) + 3x(draft+verify) + specialist(1) = 1 + 6 + 1
    assert result.llm_calls == 8


def test_an_allowed_result_has_no_pending_review() -> None:
    # The flip side of the escalate test above: a clean ALLOW must not leave pending_review set.
    llm = _llm_with(
        [
            structured_response(
                {"tasks": [{"agent": "data_analyst", "objective": "x", "constraints": {}}]}
            ),
            structured_response(
                {"answer": "freight is $1.64M", "cited_tasks": [], "conflicts_noted": []}
            ),
            structured_response(_verdict(grounded=True)),
        ]
    )
    orch = Orchestrator(llm, executors={"data_analyst": _ok("data_analyst", "x", ["internal"])})

    result = orch.answer("What is freight cost?", role="analyst")

    assert result.guardian_verdict is not None
    assert result.guardian_verdict.outcome == "allow"
    assert result.pending_review is None


def test_a_specialist_that_outlives_its_latency_budget_becomes_a_failed_result() -> None:
    def _slow(spec: TaskSpec) -> AgentResult:
        time.sleep(0.2)
        return AgentResult(task_id=spec.task_id, agent="data_analyst", status="ok", findings="x")

    llm = _llm_with(
        [
            structured_response(
                {"tasks": [{"agent": "data_analyst", "objective": "x", "constraints": {}}]}
            ),
            structured_response(
                {
                    "answer": "I could not get an answer in time.",
                    "cited_tasks": [],
                    "conflicts_noted": [],
                }
            ),
            _PASSING_VERDICT,
        ]
    )
    orch = Orchestrator(
        llm,
        executors={"data_analyst": _slow},
        default_budget=AgentBudget(max_latency_s=0.01),
    )

    result = orch.answer("x?", role="analyst")

    assert result.results[0].status == "failed"
    assert "timed out" in result.results[0].gaps[0]


def test_a_specialist_that_overruns_its_cost_budget_is_downgraded_to_partial() -> None:
    def _expensive(spec: TaskSpec) -> AgentResult:
        return AgentResult(
            task_id=spec.task_id,
            agent="data_analyst",
            status="ok",
            findings="x",
            cost_usd=10.0,  # way over the default $0.05 budget
        )

    llm = _llm_with(
        [
            structured_response(
                {"tasks": [{"agent": "data_analyst", "objective": "x", "constraints": {}}]}
            ),
            structured_response(
                {"answer": "x, but at unusual cost", "cited_tasks": ["t0"], "conflicts_noted": []}
            ),
            _PASSING_VERDICT,
        ]
    )
    orch = Orchestrator(llm, executors={"data_analyst": _expensive})

    result = orch.answer("x?", role="analyst")

    assert result.results[0].status == "partial"
    assert "exceeded budget" in result.results[0].gaps[0]
    assert "cost" in result.results[0].gaps[0]


def test_sqlite_checkpointer_persists_the_run_under_its_thread_id(tmp_path: Path) -> None:
    db_path = str(tmp_path / "checkpoints.sqlite")
    llm = _llm_with(
        [
            structured_response(
                {"tasks": [{"agent": "data_analyst", "objective": "x", "constraints": {}}]}
            ),
            structured_response({"answer": "ok", "cited_tasks": ["t0"], "conflicts_noted": []}),
            _PASSING_VERDICT,
        ]
    )
    orch = Orchestrator(
        llm, executors={"data_analyst": _ok("data_analyst", "x")}, checkpoint_path=db_path
    )

    result = orch.answer("x?", role="analyst", thread_id="run-42")

    assert result.answer == "ok"
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "select count(*) from checkpoints where thread_id = ?", ("run-42",)
        ).fetchone()
    finally:
        con.close()
    assert rows[0] > 0


def test_every_path_to_end_passes_through_guardian() -> None:
    """Day 7 step 4's topology test: master prompt C4 requires "a graph-topology unit test
    asserts that every path to the end node passes through the Guardian." LangGraph's own
    `get_graph()` exposes the compiled graph's real edges (not just the `add_edge` calls in
    `_build_graph`'s source, which could drift from what's actually compiled) -- this asserts
    directly against that.

    Day 7 step 5 added "approval_gate" as a second possible hop before END (an allowed/redacted
    Action draft stops there first), so "exactly one edge into END, from guardian" is no longer
    the right shape -- the guarantee that still has to hold is that every edge into END comes
    from "guardian" or "approval_gate", and "approval_gate" itself is only ever reached from
    "guardian". That composition is what actually proves "every path passes through guardian".
    """
    llm = _llm_with([])
    orch = Orchestrator(llm, executors={})
    compiled = orch._graph.get_graph()

    end_node_id = next(n for n in compiled.nodes if n in ("__end__", "END"))
    edges_into_end = [e for e in compiled.edges if e.target == end_node_id]
    sources_into_end = {e.source for e in edges_into_end}

    assert sources_into_end <= {"guardian", "approval_gate"}
    edges_into_approval_gate = [e for e in compiled.edges if e.target == "approval_gate"]
    assert {e.source for e in edges_into_approval_gate} == {"guardian"}


def test_guardian_blocks_a_restricted_name_leak_end_to_end() -> None:
    """Proves the wiring, not just `Guardian.review()` in isolation (that's
    `tests/test_guardian.py`'s job): a draft answer that happens to name a Restricted table
    comes back blocked through the real graph, with the raw text never reaching the caller.
    """
    llm = _llm_with(
        [
            structured_response(
                {"tasks": [{"agent": "data_analyst", "objective": "x", "constraints": {}}]}
            ),
            structured_response(
                {
                    "answer": "Computed straight from vw_PortfolioHealth.",
                    "cited_tasks": ["t0"],
                    "conflicts_noted": [],
                }
            ),
            _PASSING_VERDICT,
        ]
    )
    orch = Orchestrator(llm, executors={"data_analyst": _ok("data_analyst", "x", ["internal"])})

    result = orch.answer("x?", role="analyst")

    assert result.guardian_verdict is not None
    assert result.guardian_verdict.outcome == "block"
    assert "vw_PortfolioHealth" not in (result.answer or "")


def _action_plan_llm() -> list[object]:
    return [
        structured_response(
            {
                "tasks": [
                    {"agent": "action", "objective": "draft a reorder email", "constraints": {}}
                ]
            }
        ),
        structured_response(
            {
                "answer": "Draft: confirm the reorder, thanks.",
                "cited_tasks": ["t0"],
                "conflicts_noted": [],
            }
        ),
        _PASSING_VERDICT,
    ]


def test_no_checkpointer_skips_the_approval_gate_entirely() -> None:
    """Day 7 step 5: `interrupt()`/`Command(resume=...)` need a checkpointer to actually pause
    and resume (confirmed against a real SqliteSaver -- resuming without one raises a LangGraph
    RuntimeError). An Orchestrator built without `checkpoint_path` (every test above this one,
    and any one-shot caller) must never pause on an Action draft it has no way to ever resume --
    it should route straight through to a normal, non-pending result.
    """
    llm = _llm_with(_action_plan_llm())
    orch = Orchestrator(llm, executors={"action": _ok("action", "x", ["public"])})

    result = orch.answer("x?", role="analyst")

    assert result.pending_approval is False
    assert result.approval_decision is None
    assert result.guardian_verdict is not None
    assert result.guardian_verdict.outcome == "allow"
    assert result.answer == "Draft: confirm the reorder, thanks."


def test_action_draft_pauses_for_approval_when_checkpointed(tmp_path: Path) -> None:
    db_path = str(tmp_path / "checkpoints.sqlite")
    llm = _llm_with(_action_plan_llm())
    orch = Orchestrator(
        llm,
        executors={"action": _ok("action", "x", ["public"])},
        checkpoint_path=db_path,
    )

    result = orch.answer("x?", role="analyst", thread_id="run-approve")

    assert result.pending_approval is True
    assert result.approval_decision is None
    # The draft itself is still the Guardian's already-reviewed safe_answer -- pending_approval
    # flags that it's awaiting a human, it doesn't hide the text a reviewer needs to see.
    assert result.answer == "Draft: confirm the reorder, thanks."


def test_approver_can_approve_a_paused_action_draft(tmp_path: Path) -> None:
    db_path = str(tmp_path / "checkpoints.sqlite")
    llm = _llm_with(_action_plan_llm())
    orch = Orchestrator(
        llm,
        executors={"action": _ok("action", "x", ["public"])},
        checkpoint_path=db_path,
    )
    orch.answer("x?", role="analyst", thread_id="run-approve")

    result = orch.resume_approval("run-approve", "approve", approver_role="approver")

    assert result.approval_decision == "approved"
    # pending_approval is set True only by answer()'s own wrapper around the paused invoke()
    # call (it's never written into graph state) -- a resumed, decided run has nothing pending.
    assert result.pending_approval is False
    assert result.answer == "Draft: confirm the reorder, thanks."


def test_approver_can_reject_a_paused_action_draft(tmp_path: Path) -> None:
    db_path = str(tmp_path / "checkpoints.sqlite")
    llm = _llm_with(_action_plan_llm())
    orch = Orchestrator(
        llm,
        executors={"action": _ok("action", "x", ["public"])},
        checkpoint_path=db_path,
    )
    orch.answer("x?", role="analyst", thread_id="run-reject")

    result = orch.resume_approval("run-reject", "reject", approver_role="approver")

    assert result.approval_decision == "rejected"
    assert "rejected" in (result.answer or "")
    assert "Draft: confirm the reorder" not in (result.answer or "")


def test_approver_edit_is_re_reviewed_by_the_guardian_not_trusted(tmp_path: Path) -> None:
    """An approver's edit is new, unreviewed text -- re-running it through the Guardian should
    catch a violation the original draft never had (here, a restricted-name leak the approver
    typed in by hand), proving the edit path doesn't bypass step 4's non-bypassable guarantee.
    """
    db_path = str(tmp_path / "checkpoints.sqlite")
    llm = _llm_with(_action_plan_llm())
    orch = Orchestrator(
        llm,
        executors={"action": _ok("action", "x", ["public"])},
        checkpoint_path=db_path,
    )
    orch.answer("x?", role="analyst", thread_id="run-edit")

    result = orch.resume_approval(
        "run-edit",
        "edit",
        approver_role="approver",
        edited_answer="Pulled straight from vw_PortfolioHealth for you.",
    )

    assert result.approval_decision == "edited"
    assert result.guardian_verdict is not None
    assert result.guardian_verdict.outcome == "block"
    assert "vw_PortfolioHealth" not in (result.answer or "")


def test_approver_edit_that_stays_clean_is_accepted(tmp_path: Path) -> None:
    db_path = str(tmp_path / "checkpoints.sqlite")
    llm = _llm_with(_action_plan_llm())
    orch = Orchestrator(
        llm,
        executors={"action": _ok("action", "x", ["public"])},
        checkpoint_path=db_path,
    )
    orch.answer("x?", role="analyst", thread_id="run-edit-clean")

    result = orch.resume_approval(
        "run-edit-clean",
        "edit",
        approver_role="approver",
        edited_answer="Please confirm the reorder at your convenience.",
    )

    assert result.approval_decision == "edited"
    assert result.guardian_verdict is not None
    assert result.guardian_verdict.outcome == "allow"
    assert result.answer == "Please confirm the reorder at your convenience."


def test_resume_approval_rejects_a_non_approver_role(tmp_path: Path) -> None:
    db_path = str(tmp_path / "checkpoints.sqlite")
    llm = _llm_with(_action_plan_llm())
    orch = Orchestrator(
        llm,
        executors={"action": _ok("action", "x", ["public"])},
        checkpoint_path=db_path,
    )
    orch.answer("x?", role="analyst", thread_id="run-guard")

    try:
        orch.resume_approval("run-guard", "approve", approver_role="viewer")
        raised = False
    except PermissionError:
        raised = True
    assert raised


def test_resume_approval_without_a_checkpointer_raises() -> None:
    llm = _llm_with([])
    orch = Orchestrator(llm, executors={})

    try:
        orch.resume_approval("no-thread", "approve", approver_role="approver")
        raised = False
    except RuntimeError:
        raised = True
    assert raised


def test_input_gate_blocks_before_the_graph_ever_runs() -> None:
    """Day 7 step 6: a blocked question never reaches "plan" -- no LLM call, no specialist, no
    cost. `_llm_with([])` (an empty queue) proves this: if `_plan` ran, `FakeMessagesResource`
    would raise on the unexpected call.
    """
    llm = _llm_with([])
    gate = InputGate(kill_switch_enabled=True)
    orch = Orchestrator(llm, executors={}, input_gate=gate)

    result = orch.answer("anything at all", role="analyst")

    assert result.input_gate_verdict is not None
    assert result.input_gate_verdict.outcome == "block"
    assert "kill_switch_engaged" in result.input_gate_verdict.reason_codes
    assert result.plan == []
    assert result.results == []
    assert result.total_cost_usd == 0.0
    assert "stopped before it reached the system" in (result.answer or "")


def test_input_gate_allows_a_clean_question_through_with_no_verdict_recorded() -> None:
    llm = _llm_with(
        [
            structured_response(
                {"tasks": [{"agent": "data_analyst", "objective": "x", "constraints": {}}]}
            ),
            structured_response({"answer": "ok", "cited_tasks": ["t0"], "conflicts_noted": []}),
            _PASSING_VERDICT,
        ]
    )
    orch = Orchestrator(llm, executors={"data_analyst": _ok("data_analyst", "x")})

    result = orch.answer("What is our top vendor's fill rate?", role="analyst")

    assert result.answer == "ok"
    assert result.input_gate_verdict is None


def test_a_completed_run_records_its_spend_against_the_input_gate_cap(tmp_path: Path) -> None:
    """Proves `answer()` actually calls `InputGate.record_spend` with the real total, not a
    guess -- the second call for the same role should then see that spend reflected.
    """
    from copilot.guardrails.input_gate import SpendTracker

    tracker = SpendTracker(path=tmp_path / "spend.json")
    gate = InputGate(spend_tracker=tracker, daily_spend_cap_usd=1000.0)

    def _costly(spec: TaskSpec) -> AgentResult:
        return AgentResult(
            task_id=spec.task_id, agent="data_analyst", status="ok", findings="x", cost_usd=2.0
        )

    llm = _llm_with(
        [
            structured_response(
                {"tasks": [{"agent": "data_analyst", "objective": "x", "constraints": {}}]}
            ),
            structured_response({"answer": "ok", "cited_tasks": ["t0"], "conflicts_noted": []}),
            _PASSING_VERDICT,
        ]
    )
    orch = Orchestrator(llm, executors={"data_analyst": _costly}, input_gate=gate)

    result = orch.answer("x?", role="analyst")

    assert result.total_cost_usd > 0
    assert tracker.spent_today("analyst") == result.total_cost_usd
