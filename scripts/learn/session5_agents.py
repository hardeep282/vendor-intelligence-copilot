"""Learning script for session 5: the agents, and the orchestrator that runs them.

Purpose : run the real `Orchestrator` (the LangGraph workflow) end to end on one question, in
          eight small, numbered steps, so you can watch the graph work in VS Code's debugger.
          **No real Claude call is made.** The three agent calls the orchestrator makes itself
          (planner, answer writer, verifier) are answered by the same scripted stand-in the
          tests use (`tests/fakes/anthropic_fakes.py`). The two specialists it runs are the
          real plain-code ones (forecast and inventory), on your real snapshot. So the numbers
          are real; the planner's choices and the wording of the answer are scripted.
Inputs  : the local snapshot (build it first with `uv run python scripts/build_snapshot.py`).
Outputs : plain-English printout of each step. The Guardian's audit line and the spend record
          go to a temporary folder, never to your real data/audit or data/spend files.

How to use it in VS Code (see the Code Trail page, chapter 4): put a red dot on the first line
inside any `step_...` function, press F5, pick "Python Debugger: Current File", then F10 / F11.
Or just run it:
    uv run python scripts/learn/session5_agents.py

Added 10 Nov 2026 for the learning sessions. It only *uses* the copilot's code; it changes
nothing about how the copilot behaves.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import get_args

from copilot.agents.contracts import AgentBudget, AgentName
from copilot.agents.orchestrator import (
    MAX_VERIFICATION_LOOPS,
    Orchestrator,
    OrchestratorResult,
    PlannedTask,
    ensure_inventory_tasks,
)
from copilot.agents.specialists import (
    forecast_result_for_inventory,
    run_forecasting_risk,
    run_inventory_planning,
)
from copilot.cli import use_utf8_output
from copilot.data import store
from copilot.guardrails import audit_log
from copilot.guardrails.input_gate import InputGate, SpendTracker
from copilot.llm.client import LLMClient
from copilot.settings import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT))  # so the tests' Claude stand-in can be imported
from tests.fakes.anthropic_fakes import FakeMessagesResource, structured_response  # noqa: E402

QUESTION = "What is next quarter's portfolio demand, and what safety stock should we hold?"
CALLS_CLAUDE = {"data_analyst", "knowledge", "action"}


def heading(n: int, title: str) -> None:
    print(f"\n{'=' * 72}\nSTEP {n}: {title}\n{'=' * 72}")


def step_1_the_roster() -> None:
    """Who the orchestrator can hand work to, and which of them are agents."""
    heading(1, "The roster: five specialists, three of them agents")
    for name in get_args(AgentName):
        kind = "agent (calls Claude)" if name in CALLS_CLAUDE else "plain code (no AI)"
        print(f"  {name:<20} {kind}")
    print("\n  Plus three agents inside the orchestrator itself: the planner, the answer")
    print("  writer and the verifier. The workflow around them is plain code.")


def step_2_the_graph(orch: Orchestrator) -> None:
    """The compiled LangGraph: every node and every edge, read from the graph itself."""
    heading(2, "The graph: nodes and edges, as LangGraph compiled them")
    graph = orch._graph.get_graph()
    for edge in graph.edges:
        style = " (decided at run time)" if edge.conditional else ""
        print(f"  {edge.source:<16} -> {edge.target}{style}")
    print("\n  Every path to __end__ passes through 'guardian' (tested in test_orchestrator.py).")


def step_3_the_inventory_rule() -> None:
    """A plain-code rule that fixes the plan if the planner forgets a specialist."""
    heading(3, "A rule over the planner: inventory questions always get the calculator")
    plan = [PlannedTask(agent="forecasting_risk", objective="forecast next quarter")]
    fixed = ensure_inventory_tasks(QUESTION, plan)
    print(f"  planner asked for: {[t.agent for t in plan]}")
    print(f"  after the rule:    {[t.agent for t in fixed]}")
    print("  The question says 'safety stock', so inventory_planning is added (2 Nov fix).")


def build_orchestrator(tmp: Path) -> tuple[Orchestrator, FakeMessagesResource]:
    """The real Orchestrator, with scripted Claude and the two real plain-code specialists."""
    con = store.connect()
    plan = {
        "tasks": [
            {"agent": "forecasting_risk", "objective": "Forecast next quarter", "constraints": {}},
            {"agent": "inventory_planning", "objective": "Safety stock", "constraints": {}},
        ]
    }
    first_draft = {"answer": "Demand will rise next quarter.", "cited_tasks": []}
    failing = {
        "grounded": False,
        "citations_ok": False,
        "sufficient": False,
        "feedback": "Give the forecast figures and the safety stock, and cite both tasks.",
    }
    second_draft = {
        "answer": (
            "About 3.76M units a month for January to March (naive forecast, likely high "
            "because December was a peak). Safety stock at 95% service: about 597,537 units."
        ),
        "cited_tasks": ["t0", "t1"],
    }
    passing = {"grounded": True, "citations_ok": True, "sufficient": True}
    fake = FakeMessagesResource(
        [
            structured_response(plan),
            structured_response(first_draft),
            structured_response(failing),
            structured_response(second_draft),
            structured_response(passing),
        ]
    )
    llm = LLMClient(api_key="sk-test-not-real")  # a made-up key; nothing is ever sent
    llm._client.messages = fake  # type: ignore[misc,assignment]
    executors = {
        "forecasting_risk": lambda spec: run_forecasting_risk(spec, con=con),
        "inventory_planning": lambda spec: run_inventory_planning(
            spec, forecast_result_for_inventory(spec, con=con)
        ),
    }
    gate = InputGate(spend_tracker=SpendTracker(tmp / "spend.json"), kill_switch_enabled=False)
    return Orchestrator(llm, executors=executors, input_gate=gate), fake  # type: ignore[arg-type]


def step_4_run_one_question(orch: Orchestrator) -> OrchestratorResult:
    """Stream the run: one event per graph node, in the order they ran."""
    heading(4, "Run one question and watch the nodes fire")
    print(f"  question: {QUESTION}\n")
    result: OrchestratorResult | None = None
    for event in orch.stream_answer(QUESTION, role="analyst"):
        if event.type == "node":
            print(f"  -> {event.node}")
        else:
            result = event.result
    if result is None:
        raise RuntimeError("the run ended without a result event")
    return result


def step_5_what_the_specialists_found(result: OrchestratorResult) -> None:
    """The real numbers, from the real plain-code specialists."""
    heading(5, "What the two specialists found (real numbers from your snapshot)")
    for r in result.results:
        print(f"  [{r.agent}] status {r.status}, confidence {r.confidence}")
        for line in r.findings.splitlines()[:4]:
            print(f"      {line[:96]}")


def step_6_the_verifier_loop(result: OrchestratorResult, fake: FakeMessagesResource) -> None:
    """The first draft failed the check, was sent back once, and the redraft passed."""
    heading(6, "The verifier loop: draft, check, redraft")
    print(f"  redrafts: {result.verify_attempts} (limit {MAX_VERIFICATION_LOOPS})")
    print(f"  verified: {result.verified}")
    print(f"  Claude calls in this run: {len(fake.calls)} (plan, draft, verify, draft, verify)")
    print(f"\n  final answer: {result.answer}")


def step_7_the_guardian(result: OrchestratorResult) -> None:
    """The last stop before the user: a rule-based check, not an agent."""
    heading(7, "The Guardian's verdict on the final answer")
    verdict = result.guardian_verdict
    if verdict is None:
        raise RuntimeError("no Guardian verdict: the graph must always end at the Guardian")
    print(f"  outcome: {verdict.outcome}")
    print(f"  findings: {[f.code for f in verdict.findings] or 'none'}")
    print("  (Session 6 covers the Guardian's eight checks.)")


def step_8_budgets() -> None:
    """Each specialist runs inside a budget; going over is reported, not hidden."""
    heading(8, "Per-specialist budgets")
    b = AgentBudget()
    print(f"  max Claude calls {b.max_llm_calls}, max cost ${b.max_cost_usd}, ", end="")
    print(f"max wait {b.max_latency_s:.0f} s")
    print("  Over budget -> status 'partial' with the overage named. Too slow -> 'failed',")
    print("  and the other specialists' results still go into the answer.")


def main() -> None:
    use_utf8_output()
    tmp = Path(tempfile.mkdtemp(prefix="copilot-learn-"))
    audit_log.DEFAULT_AUDIT_LOG_PATH = tmp / "guardian_log.jsonl"  # keep your real log clean
    step_1_the_roster()
    orch, fake = build_orchestrator(tmp)
    step_2_the_graph(orch)
    step_3_the_inventory_rule()
    result = step_4_run_one_question(orch)
    step_5_what_the_specialists_found(result)
    step_6_the_verifier_loop(result, fake)
    step_7_the_guardian(result)
    step_8_budgets()
    print("\nDone. The workflow and specialists were real; Claude's replies were scripted.")


if __name__ == "__main__":
    main()
