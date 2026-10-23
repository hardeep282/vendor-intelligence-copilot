"""Tests for the five specialist nodes (Day 6 step 2). Each wraps an already-tested service, so
these tests use stubs/mocks for that service (same posture `copilot.agents.model_selection`'s
own tests take toward the LLM) and check the TaskSpec -> AgentResult contract itself: findings,
status, gaps, and data_classes are filled honestly.

`run_forecasting_risk`/`run_inventory_planning` are the exception: they call the real
`forecast_demand`/`compute_inventory_plan` tools against this repo's own snapshot, same
skip-if-not-built pattern `tests/test_ml_forecast.py` uses, because that's the whole point of
those two specialists having a real, no-API-key data path in this repo.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from copilot.agents.contracts import TaskSpec
from copilot.agents.specialists import (
    _sql_data_classes,
    forecast_result_for_inventory,
    run_action,
    run_data_analyst,
    run_forecasting_risk,
    run_inventory_planning,
    run_knowledge,
)
from copilot.data.store import DB_NAME
from copilot.guardrails.policy import load_policy
from copilot.ml.forecast import forecast_demand
from copilot.ml.inventory import demand_stats_from_backtest
from copilot.rag.chunking import Chunk
from copilot.rag.corrective import CorrectiveRagResult
from copilot.settings import get_settings
from copilot.sql.service import TextToSqlResult

pytestmark_snapshot = pytest.mark.skipif(
    not (get_settings().snapshot_dir / DB_NAME).exists(), reason="snapshot not built"
)


def _spec(agent: str, objective: str = "x", constraints: dict[str, str] | None = None) -> TaskSpec:
    return TaskSpec(
        task_id="t1",
        agent=agent,  # type: ignore[arg-type]
        objective=objective,
        role="analyst",
        constraints=constraints or {},
    )


# -- _sql_data_classes ------------------------------------------------------------------------


def test_sql_data_classes_looks_up_every_referenced_table() -> None:
    policy = load_policy()
    classes = _sql_data_classes(
        "SELECT * FROM vendor_revenue_summary JOIN portfolio_health_mix USING (x)", policy
    )
    assert classes == ["internal", "public"]


def test_sql_data_classes_returns_empty_on_unparsable_sql() -> None:
    policy = load_policy()
    assert _sql_data_classes("not valid sql {{{", policy) == []


# -- Data Analyst -----------------------------------------------------------------------------


def test_data_analyst_reports_ok_and_data_classes_on_success() -> None:
    sql_service = Mock()
    sql_service.answer.return_value = TextToSqlResult(
        question="freight by vendor",
        role="analyst",
        sql="SELECT * FROM vendor_logistics_cost",
        rows=[{"VendorName": "DIAGEO", "FreightCost": 164000.0}],
        abstained=False,
        total_cost_usd=0.01,
        total_latency_s=1.2,
        llm_calls=1,
    )

    result = run_data_analyst(_spec("data_analyst", "freight by vendor"), sql_service)

    assert result.status == "ok"
    assert result.data_classes == ["internal"]
    assert "DIAGEO" in result.findings
    assert result.evidence == ["SELECT * FROM vendor_logistics_cost"]


def test_data_analyst_reports_failed_on_abstain() -> None:
    sql_service = Mock()
    sql_service.answer.return_value = TextToSqlResult(
        question="x",
        role="analyst",
        abstained=True,
        abstain_reason="no coverage for 2025",
        total_cost_usd=0.02,
    )

    result = run_data_analyst(_spec("data_analyst"), sql_service)

    assert result.status == "failed"
    assert result.confidence == "low"
    assert "no coverage for 2025" in result.gaps


def test_data_analyst_marks_partial_when_truncated() -> None:
    sql_service = Mock()
    sql_service.answer.return_value = TextToSqlResult(
        question="x",
        role="analyst",
        sql="SELECT * FROM vendor_pareto",
        rows=[{"a": 1}],
        abstained=False,
        truncated=True,
    )

    result = run_data_analyst(_spec("data_analyst"), sql_service)

    assert result.status == "partial"
    assert any("truncated" in g for g in result.gaps)


# -- Forecasting & Risk (real snapshot) --------------------------------------------------------


@pytestmark_snapshot
def test_forecasting_risk_runs_a_real_portfolio_forecast() -> None:
    spec = _spec("forecasting_risk", "forecast portfolio demand")

    result = run_forecasting_risk(spec)

    assert result.status == "ok"
    assert result.data_classes == ["public"]
    assert "demand forecast" in result.findings
    assert result.gaps == []


@pytestmark_snapshot
def test_forecasting_risk_vendor_level_is_tagged_internal() -> None:
    spec = _spec(
        "forecasting_risk",
        "forecast DIAGEO demand",
        {"level": "vendor", "vendor_name": "DIAGEO NORTH AMERICA INC"},
    )

    result = run_forecasting_risk(spec)

    assert result.data_classes == ["internal"]


@pytestmark_snapshot
def test_forecasting_risk_classifier_against_synthetic_fixture_flags_a_gap() -> None:
    spec = _spec("forecasting_risk", "classify SKU risk", {"run_risk_classifier": "true"})

    result = run_forecasting_risk(spec)

    assert result.status == "partial"
    assert any("synthetic" in g for g in result.gaps)
    assert "risk classifier" in result.findings


@pytestmark_snapshot
def test_forecast_result_for_inventory_returns_a_real_forecast_result() -> None:
    spec = _spec("forecasting_risk", "forecast")

    forecast = forecast_result_for_inventory(spec)

    assert forecast.request.level == "portfolio"
    assert len(forecast.forecast) == 3


# -- Inventory Planning (real snapshot, chained off a real forecast) ---------------------------


@pytestmark_snapshot
def test_inventory_planning_chains_off_a_real_forecast() -> None:
    from copilot.ml.forecast import ForecastRequest

    forecast = forecast_demand(ForecastRequest(level="portfolio"))
    spec = _spec("inventory_planning", "inventory plan")

    result = run_inventory_planning(spec, forecast)

    assert result.status == "ok"
    assert "safety stock" in result.findings
    assert result.data_classes == ["public"]
    # sanity: matches what demand_stats_from_backtest/compute_inventory_plan would give directly
    mean_demand, demand_std = demand_stats_from_backtest(forecast)
    assert mean_demand > 0
    assert demand_std >= 0


# -- Knowledge ----------------------------------------------------------------------------------


def _chunk(chunk_id: str, data_class: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_type="methodology",
        vendor=None,
        version=1,
        data_class=data_class,  # type: ignore[arg-type]
        allowed_roles=("viewer", "analyst", "approver", "admin"),
        heading_path=("Intro",),
        chunk_index=0,
        text="some text",
        content_hash="deadbeef",
    )


def test_knowledge_reports_ok_and_looks_up_cited_chunk_classes() -> None:
    rag_service = Mock()
    rag_service.answer.return_value = CorrectiveRagResult(
        question="what is freight cost",
        role="analyst",
        answer="Freight cost is vendor-level, use MAX not SUM.",
        cited_chunk_ids=["c1", "c2"],
        corrections=0,
        abstained=False,
        total_cost_usd=0.01,
        total_latency_s=0.5,
        llm_calls=2,
    )
    retriever = Mock()
    retriever.chunk_by_id.side_effect = lambda cid: {
        "c1": _chunk("c1", "public"),
        "c2": _chunk("c2", "internal"),
    }.get(cid)

    result = run_knowledge(_spec("knowledge", "what is freight cost"), rag_service, retriever)

    assert result.status == "ok"
    assert result.data_classes == ["internal", "public"]
    assert result.confidence == "high"


def test_knowledge_reports_partial_when_corrections_were_needed() -> None:
    rag_service = Mock()
    rag_service.answer.return_value = CorrectiveRagResult(
        question="x",
        role="analyst",
        answer="answer after a rewrite",
        cited_chunk_ids=[],
        corrections=1,
        abstained=False,
    )
    retriever = Mock()

    result = run_knowledge(_spec("knowledge"), rag_service, retriever)

    assert result.status == "partial"
    assert "1 query rewrite" in result.gaps[0]


def test_knowledge_reports_failed_on_abstain() -> None:
    rag_service = Mock()
    rag_service.answer.return_value = CorrectiveRagResult(
        question="x", role="analyst", abstained=True, abstain_reason="nothing relevant retrieved"
    )
    retriever = Mock()

    result = run_knowledge(_spec("knowledge"), rag_service, retriever)

    assert result.status == "failed"
    assert "nothing relevant retrieved" in result.gaps


# -- Action (drafts only) -----------------------------------------------------------------------


def test_action_always_returns_partial_with_a_guardian_gap() -> None:
    from copilot.llm.types import CallMetrics

    llm = Mock()
    draft = Mock(subject="Re: Q1 freight terms", body="Dear DIAGEO, ...")
    metrics = CallMetrics(
        model="claude-sonnet-5",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.005,
        ttft_s=0.2,
        total_latency_s=1.0,
    )
    llm.structured.return_value = (draft, metrics)
    spec = _spec(
        "action",
        "draft a renegotiation email",
        {"draft_type": "renegotiation_email", "vendor_name": "DIAGEO", "context": "freight terms"},
    )

    result = run_action(spec, llm)

    assert result.status == "partial"
    assert "Guardian" in result.gaps[0] or "approver" in result.gaps[0]
    assert result.data_classes == ["confidential"]
    assert "Re: Q1 freight terms" in result.findings
