"""Tests for the Orchestrator (Day 6 step 3): typed plan, Send fan-out, join, draft, and
logged-only conflict handling. No network, no real API key, same convention as
tests/test_model_selection_agent.py and tests/test_rag_corrective.py: the LLM side is
FakeMessagesResource, queued in the exact order the graph is expected to call it in; specialists
are fake executors (step 2's own correctness is covered in tests/test_agent_specialists.py).
"""

from __future__ import annotations

from copilot.agents.contracts import AgentResult, TaskSpec
from copilot.agents.orchestrator import Orchestrator
from copilot.llm.client import LLMClient
from tests.fakes.anthropic_fakes import FakeMessagesResource, structured_response


def _llm_with(responses: list[object]) -> LLMClient:
    llm = LLMClient(api_key="sk-test-not-real")
    llm._client.messages = FakeMessagesResource(responses)  # type: ignore[attr-defined]
    return llm


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
    assert result.llm_calls == 3  # plan(1) + draft(1) + the fake specialist's own llm_calls=1


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
    # logged, not re-queried: exactly one plan call and one draft call, no extra loop over the
    # conflict -- plus the two fake specialists' own llm_calls=1 each
    assert result.llm_calls == 4


def test_cost_latency_and_calls_sum_across_plan_specialists_and_draft() -> None:
    llm = _llm_with(
        [
            structured_response(
                {"tasks": [{"agent": "data_analyst", "objective": "x", "constraints": {}}]}
            ),
            structured_response({"answer": "ok", "cited_tasks": ["t0"], "conflicts_noted": []}),
        ]
    )
    orch = Orchestrator(
        llm, executors={"data_analyst": _ok("data_analyst", "x", ["internal"])}
    )

    result = orch.answer("x?", role="analyst")

    # 2 LLM calls (plan, draft) at FakeMessagesResource's fixed cost, plus the fake specialist's
    # own 0.001/0.1/1 accounting folded in by the draft node.
    assert result.llm_calls == 3  # plan(1) + draft(1) + specialist(1)
    assert result.total_cost_usd > 0.001
    assert result.total_latency_s > 0.1
