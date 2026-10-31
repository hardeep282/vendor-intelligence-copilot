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
    ACTION_DRAFT_NOTE,
    _sql_data_classes,
    forecast_result_for_inventory,
    identify_vendor,
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
    # 30 Oct 2026: the unit and the forecast's own cautions reach the drafter, and a forecast
    # with warnings is never reported at medium confidence.
    assert "units sold per month" in result.findings
    assert "not dollars" in result.findings
    assert "WARNING: Only 12 months of history" in result.findings
    assert result.confidence == "low"


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
    # 31 Oct 2026: plain, true wording; no "Day 7" sprint jargon reaching users
    assert result.gaps == [ACTION_DRAFT_NOTE]
    assert "Day 7" not in result.gaps[0]
    assert result.data_classes == ["confidential"]
    assert "Re: Q1 freight terms" in result.findings
    assert "vendor_name=DIAGEO" in result.evidence


def test_data_analyst_findings_carry_the_units_of_the_selected_columns() -> None:
    """30 Oct 2026: a real run's drafter called a percent of vendor revenue "% of controllable
    margin"; the findings now say what each selected column measures."""
    sql_service = Mock()
    sql = (
        "SELECT VendorName, ROUND(ControllableLeakage, 2) AS controllable_leakage, "
        "ROUND(ControllableLeakagePct, 2) AS controllable_leakage_pct FROM vendor_profit_leakage"
    )
    sql_service.answer.return_value = TextToSqlResult(
        question="x",
        role="analyst",
        sql=sql,
        rows=[
            {
                "VendorName": "MARTIGNETTI COMPANIES",
                "controllable_leakage": 874764.97,
                "controllable_leakage_pct": 2.14,
            }
        ],
        abstained=False,
        total_cost_usd=0.01,
        total_latency_s=1.0,
        llm_calls=1,
    )

    result = run_data_analyst(_spec("data_analyst", "controllable leakage"), sql_service)

    assert "Units: controllable_leakage (ControllableLeakage): US dollars" in result.findings
    assert "percent of that vendor's total revenue" in result.findings


def test_data_analyst_findings_say_how_the_rows_are_sorted() -> None:
    """30 Oct 2026: a 'most controllable leakage' question got a query sorted by total leakage.
    The findings now name the sort, so the Verifier can compare it with the question."""
    sql_service = Mock()
    sql = (
        "SELECT VendorName, ROUND(TotalLeakageAmount, 2) AS total_leakage_amount "
        "FROM vendor_profit_leakage ORDER BY TotalLeakageAmount DESC LIMIT 200"
    )
    rows = [{"VendorName": f"V{i}", "total_leakage_amount": 100.0 - i} for i in range(8)]
    sql_service.answer.return_value = TextToSqlResult(
        question="x",
        role="analyst",
        sql=sql,
        rows=rows,
        abstained=False,
        total_cost_usd=0.01,
        total_latency_s=1.0,
        llm_calls=1,
    )

    result = run_data_analyst(_spec("data_analyst", "most controllable leakage"), sql_service)

    assert "Sorted by: TotalLeakageAmount (highest first)." in result.findings
    assert "The first 5 of 8 rows are shown above." in result.findings


# -- vendor identification for Action drafts (31 Oct 2026) ----------------------------------
# A real run planned an Action draft without vendor_name, so it was recorded as "the vendor".

_VENDORS = [
    "DIAGEO NORTH AMERICA INC",
    "DIAGEO CHATEAU ESTATE WINES",
    "JIM BEAM BRANDS COMPANY",
    "BACARDI USA INC",
    "MOET HENNESSY USA INC",
]


def test_identify_vendor_full_name_short_name_and_ambiguity() -> None:
    assert identify_vendor("email DIAGEO NORTH AMERICA INC", _VENDORS) == "DIAGEO NORTH AMERICA INC"
    assert identify_vendor("reorder note for Jim Beam", _VENDORS) == "JIM BEAM BRANDS COMPANY"
    assert identify_vendor("email to Bacardi", _VENDORS) == "BACARDI USA INC"
    # two Diageo vendors exist in the real data: never guess between them
    assert identify_vendor("email to Diageo", _VENDORS) is None
    assert identify_vendor("email to Bacardi and Jim Beam", _VENDORS) is None
    assert identify_vendor("an email about freight", _VENDORS) is None


def _action_llm() -> Mock:
    from copilot.llm.types import CallMetrics

    llm = Mock()
    llm.structured.return_value = (
        Mock(subject="Freight terms", body="Dear team, ..."),
        CallMetrics(
            model="claude-sonnet-5",
            input_tokens=10,
            output_tokens=10,
            cost_usd=0.001,
            ttft_s=0.1,
            total_latency_s=0.5,
        ),
    )
    return llm


def test_action_finds_the_vendor_when_the_planner_left_it_out() -> None:
    spec = _spec(
        "action",
        "Draft a short renegotiation email to DIAGEO NORTH AMERICA INC about freight terms",
        {"draft_type": "renegotiation_email"},
    )
    result = run_action(spec, _action_llm(), known_vendors=_VENDORS)
    assert "vendor_name=DIAGEO NORTH AMERICA INC" in result.evidence
    assert result.gaps == [ACTION_DRAFT_NOTE]


def test_action_flags_an_unidentified_vendor_instead_of_guessing() -> None:
    spec = _spec("action", "Draft an email to Diageo about freight", {})
    result = run_action(spec, _action_llm(), known_vendors=_VENDORS)
    assert "vendor_name=unidentified vendor" in result.evidence
    assert any("couldn't be identified" in g for g in result.gaps)
