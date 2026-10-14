"""Day 6 step 7: wires the five already-tested Day 6 step 2 specialist functions into the
`dict[AgentName, SpecialistExecutor]` shape `Orchestrator` takes, against real services.

Purpose : `copilot.agents.orchestrator.Orchestrator` deliberately never constructs its own
          specialists (module docstring) -- tests inject fakes, and *something* has to inject
          the real `run_*` functions for an actual end-to-end run. This is that something; its
          only caller so far is `scripts/run_orchestrator_golden.py` (Day 6 step 7's 10
          multi-hop golden questions, run for real on your machine with your own
          ANTHROPIC_API_KEY -- keys never go in chat, same posture every other real-key script
          in this repo already takes).
Inputs  : the already-constructed real services every specialist needs (an `LLMClient`, a
          `TextToSqlService`, a DuckDB connection, a `CorrectiveRagService` + its
          `PermissionedRetriever`) -- each built exactly the way the existing `scripts/
          run_effort_lab.py`/`run_rag_eval.py` already build them, not reproduced here.
Outputs : `dict[AgentName, SpecialistExecutor]`, ready to pass to `Orchestrator(...)`.

`inventory_planning` needs a `ForecastResult`, not a bare `TaskSpec` (`run_inventory_planning`'s
own signature, step 2) -- `_inventory_executor` below is the one piece of real glue this module
adds: it calls `forecast_result_for_inventory` itself so the Orchestrator's executor map still
satisfies the plain `TaskSpec -> AgentResult` `SpecialistExecutor` shape every other specialist
already does. This mirrors `orchestrator_plan`'s own rule that planning `inventory_planning`
always implies planning `forecasting_risk` too, since the former needs the latter's output.
"""

from __future__ import annotations

import duckdb

from copilot.agents.contracts import AgentName, AgentResult, TaskSpec
from copilot.agents.orchestrator import SpecialistExecutor
from copilot.agents.specialists import (
    forecast_result_for_inventory,
    run_action,
    run_data_analyst,
    run_forecasting_risk,
    run_inventory_planning,
    run_knowledge,
)
from copilot.guardrails.policy import DisclosurePolicy
from copilot.llm.client import LLMClient
from copilot.rag.corrective import CorrectiveRagService
from copilot.rag.permissions import PermissionedRetriever
from copilot.sql.service import TextToSqlService


def _inventory_executor(
    spec: TaskSpec, con: duckdb.DuckDBPyConnection | None
) -> AgentResult:
    forecast = forecast_result_for_inventory(spec, con=con)
    return run_inventory_planning(spec, forecast)


def build_executors(
    llm: LLMClient,
    sql_service: TextToSqlService,
    rag_service: CorrectiveRagService,
    retriever: PermissionedRetriever,
    con: duckdb.DuckDBPyConnection | None = None,
    policy: DisclosurePolicy | None = None,
) -> dict[AgentName, SpecialistExecutor]:
    """Build the real executor map for all five specialists (C3 roster). `con=None` lets
    `run_forecasting_risk`/`forecast_result_for_inventory` fall back to their own default
    connection (`copilot.data.store.connect()`), same as calling them directly would.
    """
    return {
        "data_analyst": lambda spec: run_data_analyst(spec, sql_service, policy=policy),
        "forecasting_risk": lambda spec: run_forecasting_risk(spec, con=con),
        "inventory_planning": lambda spec: _inventory_executor(spec, con),
        "knowledge": lambda spec: run_knowledge(spec, rag_service, retriever),
        "action": lambda spec: run_action(spec, llm),
    }


__all__ = ["build_executors"]
