"""Day 6 step 2: the five specialist nodes -- Data Analyst, Forecasting & Risk, Inventory
Planning, Knowledge, Action -- each a plain `TaskSpec -> AgentResult` function wrapping a
service this repo already built, never a reimplementation.

Purpose : master prompt C3's agent roster. Every function here takes the shared `TaskSpec`
          envelope (contracts.py, Day 6 step 1) and returns the shared `AgentResult` envelope,
          so the Orchestrator (step 3, not yet built) can call all five the same way and never
          branch on which specialist it's talking to. Each specialist fills `data_classes`
          itself from the live `DisclosurePolicy` -- the one thing only the specialist that
          actually ran the query/retrieval/model knows.
Inputs  : a TaskSpec, plus whatever already-constructed service object that specialist needs
          (an LLMClient, a TextToSqlService, a CorrectiveRagService + its PermissionedRetriever,
          a DuckDB connection). These are constructor-injected the same way every other service
          in this repo is -- the specialist functions don't build their own dependencies.
Outputs : AgentResult for each.

Why thin wrappers and not new logic: every number a specialist reports already has its own
tested tool (`TextToSqlService.answer`, `forecast_demand`, `compute_inventory_plan`,
`compare_models`, `CorrectiveRagService.answer`) from Days 3-5. This file's only job is the
C3 contract -- condense each tool's own result type into `AgentResult.findings`/`evidence`,
report `status`/`gaps` honestly when a tool abstains or a licence-safe limitation applies, and
fill `data_classes` from the policy. None of the underlying tools change.

Forecasting & Risk is one specialist with two tools (C3's roster), not two specialists -- the
risk half needs real SKU-level features (`copilot.ml.risk_classifier.train_and_evaluate`), which
this repo's licence-safe snapshot never contains (`copilot.data.guard.check_table` rejects
SKU-level columns by construction, same reason Day 5's classifier only ever ran against
`make_synthetic_skus()` here). `run_forecasting_risk` runs the forecast for real against this
repo's own snapshot and runs the classifier against a synthetic fixture unless the caller
supplies a real SKU dataframe (the `scripts/train_risk_classifier.py` convention) -- it never
silently claims a real accuracy/F1 number this snapshot can't support.

Action drafts only (master prompt C3/C5: behind an approval interrupt, which is Day 7 -- not
built here). Every Action result is tagged `data_classes=["confidential"]` and carries a gap
saying it has not passed Guardian review, so nothing downstream can mistake a draft for
something safe to send.
"""

from __future__ import annotations

import time
from typing import Literal, cast

import duckdb
import pandas as pd
import sqlglot
from anthropic.types import MessageParam
from langsmith.run_helpers import LangSmithExtra
from pydantic import BaseModel
from sqlglot import exp

from copilot.agents.contracts import AgentResult, TaskSpec
from copilot.guardrails.canary import canary_line
from copilot.guardrails.policy import DataClass, DisclosurePolicy, load_policy
from copilot.llm.client import Effort, LLMClient
from copilot.llm.prompts import load_prompt
from copilot.llm.types import CallMetrics
from copilot.ml.forecast import ForecastRequest, ForecastResult, Level, forecast_demand
from copilot.ml.inventory import (
    InventoryRequest,
    compute_inventory_plan,
    demand_stats_from_backtest,
)
from copilot.ml.risk_classifier import ClassifierResult, compare_models, make_synthetic_skus
from copilot.rag.corrective import CorrectiveRagService
from copilot.rag.permissions import PermissionedRetriever
from copilot.sql.service import TextToSqlResult, TextToSqlService

DIALECT = "duckdb"  # matches copilot.sql.validator -- same engine, same dialect


# -- shared helper: SQL text -> the policy data classes it actually touched -------------------


def _sql_data_classes(sql: str, policy: DisclosurePolicy) -> list[DataClass]:
    """Parse `sql` and look up every referenced table's class in the live policy. Used instead
    of trusting `TextToSqlResult` to self-report, because the service's own job is answering
    the question, not auditing itself -- same "the policy is the one source of truth"
    posture `copilot.rag.permissions` takes toward chunk `data_class`.
    """
    try:
        statement = sqlglot.parse_one(sql, read=DIALECT)
    except Exception:  # noqa: BLE001 -- malformed SQL here just means "can't attribute classes"
        return []
    tables = {t.name for t in statement.find_all(exp.Table) if t.name}
    classes = {policy.class_of(name) for name in tables}
    return sorted(classes)


# == 1. Data Analyst ===========================================================================


def run_data_analyst(
    spec: TaskSpec,
    sql_service: TextToSqlService,
    policy: DisclosurePolicy | None = None,
    effort: Effort | None = None,
) -> AgentResult:
    """Text-to-SQL, wrapped. `spec.objective` is the question; `spec.role` decides what schema
    and examples `TextToSqlService` shows the model (unchanged from Day 3).
    """
    policy = policy or load_policy()
    result: TextToSqlResult = sql_service.answer(spec.objective, role=spec.role, effort=effort)

    if result.abstained or result.sql is None or result.rows is None:
        return AgentResult(
            task_id=spec.task_id,
            agent="data_analyst",
            status="failed",
            findings=f"Could not answer: {result.abstain_reason or 'no reason given'}",
            gaps=[result.abstain_reason or "text-to-SQL abstained"],
            confidence="low",
            cost_usd=result.total_cost_usd,
            latency_s=result.total_latency_s,
            llm_calls=result.llm_calls,
        )

    data_classes = _sql_data_classes(result.sql, policy)
    row_preview = result.rows[:5]
    findings = (
        f"Query returned {len(result.rows)} row(s)"
        f"{' (truncated)' if result.truncated else ''}: {row_preview}"
    )
    gaps = list(result.assumptions)
    if result.truncated:
        gaps.append("result set was truncated to the row cap")

    return AgentResult(
        task_id=spec.task_id,
        agent="data_analyst",
        status="ok" if not gaps else "partial",
        findings=findings,
        evidence=[result.sql],
        gaps=gaps,
        confidence="high" if result.self_corrections == 0 else "medium",
        data_classes=data_classes,
        cost_usd=result.total_cost_usd,
        latency_s=result.total_latency_s,
        llm_calls=result.llm_calls,
    )


# == 2. Forecasting & Risk =====================================================================


def run_forecasting_risk(
    spec: TaskSpec,
    con: duckdb.DuckDBPyConnection | None = None,
    risk_df: pd.DataFrame | None = None,
    compute_shap: bool = False,
) -> AgentResult:
    """Demand forecast (always real, against this repo's own snapshot) plus an optional SKU
    risk classification pass. `spec.constraints["level"]` is "portfolio" (default) or "vendor"
    (with `spec.constraints["vendor_name"]` required); `spec.constraints["run_risk_classifier"]`
    ("true"/"false", default "false") turns on the classifier half -- off by default because,
    unlike the forecast, it has no real-data path in this repo (see module docstring).
    """
    level = cast("Level", spec.constraints.get("level", "portfolio"))
    vendor_name = spec.constraints.get("vendor_name")
    horizon = int(spec.constraints.get("horizon_months", "3"))

    t0 = time.perf_counter()
    forecast = forecast_demand(
        ForecastRequest(level=level, vendor_name=vendor_name, horizon_months=horizon), con=con
    )
    latency = time.perf_counter() - t0

    lines = [
        f"{level} demand forecast ({forecast.chosen_model} chosen by WAPE): "
        f"next {horizon} month(s) = {[p.value for p in forecast.forecast]}."
    ]
    for bt in forecast.backtest:
        lines.append(
            f"  backtest {bt.model}: WAPE={bt.wape:.4f} MASE={bt.mase:.3f} bias={bt.bias:.0f}"
        )
    gaps: list[str] = []
    evidence = [f"chosen_model={forecast.chosen_model}"]
    classifier_results: dict[str, ClassifierResult] = {}

    run_risk = spec.constraints.get("run_risk_classifier", "false").lower() == "true"
    if run_risk:
        df = risk_df if risk_df is not None else make_synthetic_skus()
        if risk_df is None:
            gaps.append(
                "risk classification ran against a synthetic SKU fixture, not real "
                "vw_PortfolioHealth data -- this repo's licence-safe snapshot has no SKU-level "
                "features (see scripts/train_risk_classifier.py for a real run)"
            )
        classifier_results = compare_models(df)
        safe_rf = classifier_results["random_forest_safe"]
        lines.append(
            f"risk classifier (leakage-safe random_forest): accuracy={safe_rf.accuracy:.3f} "
            f"f1={safe_rf.f1:.3f} on {safe_rf.n_test} held-out rows"
        )
        evidence.append(f"random_forest_safe accuracy={safe_rf.accuracy:.3f} f1={safe_rf.f1:.3f}")

    return AgentResult(
        task_id=spec.task_id,
        agent="forecasting_risk",
        status="ok" if not gaps else "partial",
        findings="\n".join(lines),
        evidence=evidence,
        gaps=gaps,
        confidence="medium" if not run_risk or risk_df is not None else "low",
        data_classes=["internal"] if level == "vendor" else ["public"],
        latency_s=latency,
    )


def forecast_result_for_inventory(
    spec: TaskSpec, con: duckdb.DuckDBPyConnection | None = None
) -> ForecastResult:
    """Convenience for the Orchestrator (step 3): run the same forecast
    `run_forecasting_risk` would, returning the raw `ForecastResult` Inventory Planning needs
    as its own input -- the "Inventory waits for Forecasting" dependency from master prompt C3.
    """
    level = cast("Level", spec.constraints.get("level", "portfolio"))
    vendor_name = spec.constraints.get("vendor_name")
    horizon = int(spec.constraints.get("horizon_months", "3"))
    return forecast_demand(
        ForecastRequest(level=level, vendor_name=vendor_name, horizon_months=horizon), con=con
    )


# == 3. Inventory Planning =====================================================================


def run_inventory_planning(spec: TaskSpec, forecast: ForecastResult) -> AgentResult:
    """Safety stock / reorder point / EOQ from a forecast's own history (for demand
    variability) and horizon (for mean demand) -- `demand_stats_from_backtest` is the Day 5
    bridge that already does this correctly (std dev from *history*, not across a flat
    forecast; see `docs/BUILD_LOG.md`). Cost/service-level constraints come from
    `spec.constraints`, with the same defaults Day 5's real run used.
    """
    mean_demand, demand_std = demand_stats_from_backtest(forecast)
    request = InventoryRequest(
        mean_demand_per_period=mean_demand,
        demand_std_per_period=demand_std,
        lead_time_periods=float(spec.constraints.get("lead_time_periods", "1")),
        service_level=float(spec.constraints.get("service_level", "0.95")),
        ordering_cost_per_order=float(spec.constraints.get("ordering_cost_per_order", "500")),
        holding_cost_per_unit_per_year=float(
            spec.constraints.get("holding_cost_per_unit_per_year", "0.5")
        ),
    )
    plan = compute_inventory_plan(request)

    findings = (
        f"safety stock={plan.safety_stock:,.0f}, reorder point={plan.reorder_point:,.0f}, "
        f"EOQ={plan.economic_order_quantity:,.0f} "
        f"(service level {request.service_level:.0%}, z={plan.z_score:.2f})"
    )
    return AgentResult(
        task_id=spec.task_id,
        agent="inventory_planning",
        status="ok",
        findings=findings,
        evidence=[f"forecast chosen_model={forecast.chosen_model}"],
        confidence="medium",
        data_classes=["internal"] if forecast.request.level == "vendor" else ["public"],
    )


# == 4. Knowledge ==============================================================================


def run_knowledge(
    spec: TaskSpec, rag_service: CorrectiveRagService, retriever: PermissionedRetriever
) -> AgentResult:
    """Corrective RAG, wrapped. `retriever` must be the same `PermissionedRetriever` instance
    `rag_service` was built with -- it's passed separately only so this function can look up
    each cited chunk's own `data_class` after the fact (`CorrectiveRagResult` reports chunk
    ids, not the chunks themselves).
    """
    result = rag_service.answer(spec.objective, role=spec.role)

    if result.abstained or result.answer is None:
        return AgentResult(
            task_id=spec.task_id,
            agent="knowledge",
            status="failed",
            findings=f"Could not answer: {result.abstain_reason or 'no reason given'}",
            gaps=[result.abstain_reason or "retrieval abstained"],
            confidence="low",
            cost_usd=result.total_cost_usd,
            latency_s=result.total_latency_s,
            llm_calls=result.llm_calls,
        )

    data_classes = sorted(
        {
            chunk.data_class
            for cid in result.cited_chunk_ids
            if (chunk := retriever.chunk_by_id(cid)) is not None
        }
    )
    return AgentResult(
        task_id=spec.task_id,
        agent="knowledge",
        status="ok" if result.corrections == 0 else "partial",
        findings=result.answer,
        evidence=result.cited_chunk_ids,
        gaps=(
            [f"needed {result.corrections} query rewrite(s) to find grounded chunks"]
            if result.corrections
            else []
        ),
        confidence="high" if result.corrections == 0 else "medium",
        data_classes=data_classes,
        cost_usd=result.total_cost_usd,
        latency_s=result.total_latency_s,
        llm_calls=result.llm_calls,
    )


# == 5. Action (drafts only) ===================================================================

DraftType = Literal["renegotiation_email", "reorder_recommendation"]


class ActionDraft(BaseModel):
    """Forced structured output for the action_draft prompt."""

    subject: str
    body: str


def run_action(spec: TaskSpec, llm: LLMClient, effort: Effort | None = None) -> AgentResult:
    """Draft a renegotiation email or reorder recommendation. Never sent, never approved here --
    master prompt C5's interrupt -> Guardian -> approver flow is Day 7. `spec.constraints`
    carries `draft_type` (default "renegotiation_email"), `vendor_name`, and `context` (the
    plain-English figures/terms to ground the draft in, e.g. "controllable leakage $X, driven by
    freight"). The system prompt tells the model to use only public facts and the named
    vendor's own terms -- enforced for real by the Guardian, not by this function; `gaps`
    says so explicitly rather than implying this draft is already safe to send.
    """
    draft_type = cast("DraftType", spec.constraints.get("draft_type", "renegotiation_email"))
    vendor_name = spec.constraints.get("vendor_name", "the vendor")
    context = spec.constraints.get("context", spec.objective)

    prompt = load_prompt("action_draft")
    system = prompt.render_system(draft_type=draft_type) + canary_line("action")
    messages: list[MessageParam] = [
        {
            "role": "user",
            "content": prompt.render_user(
                vendor_name=vendor_name, context=context, draft_type=draft_type
            ),
        }
    ]
    draft, metrics = cast(
        "tuple[ActionDraft, CallMetrics]",
        llm.structured(
            model=prompt.model,
            system=system,
            messages=messages,
            output_model=ActionDraft,
            max_tokens=prompt.max_tokens,
            effort=effort or prompt.effort,
            cache_system=prompt.cache_system,
            langsmith_extra=cast(
                "LangSmithExtra",
                {
                    "name": "specialist.action",
                    "tags": ["specialist", "action", f"draft_type:{draft_type}"],
                },
            ),
        ),
    )

    return AgentResult(
        task_id=spec.task_id,
        agent="action",
        status="partial",  # never "ok": a draft is never done until the Guardian/approver sees it
        findings=f"Subject: {draft.subject}\n\n{draft.body}",
        evidence=[f"draft_type={draft_type}", f"vendor_name={vendor_name}"],
        gaps=[
            "not yet passed through the Guardian or an approver (Day 7) -- do not send",
        ],
        confidence="medium",
        data_classes=["confidential"],
        cost_usd=metrics.cost_usd,
        latency_s=metrics.total_latency_s,
        llm_calls=1,
    )


__all__ = [
    "ActionDraft",
    "DraftType",
    "forecast_result_for_inventory",
    "run_action",
    "run_data_analyst",
    "run_forecasting_risk",
    "run_inventory_planning",
    "run_knowledge",
]
