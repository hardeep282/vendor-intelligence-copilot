"""Tests for the CSV run-log (Day 5 step 5)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from copilot.ml.forecast import BacktestMetrics, ForecastRequest, ForecastResult, MonthlyPoint
from copilot.ml.inventory import InventoryPlan, InventoryRequest
from copilot.ml.risk_classifier import CalibrationPoint, ClassifierResult
from copilot.ml.run_log import (
    RUN_LOG_COLUMNS,
    append_run_log,
    log_classifier_run,
    log_forecast_run,
    log_inventory_run,
)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_append_run_log_writes_header_on_first_call(tmp_path: Path) -> None:
    path = tmp_path / "runs.csv"
    entry = log_forecast_run(_fake_forecast_result(), path)
    rows = _read_rows(path)
    assert len(rows) == 1
    assert list(rows[0].keys()) == list(RUN_LOG_COLUMNS)
    assert rows[0]["tool"] == "forecast_demand"
    assert rows[0]["timestamp"] == entry.timestamp


def test_append_run_log_appends_without_duplicating_header(tmp_path: Path) -> None:
    path = tmp_path / "runs.csv"
    log_forecast_run(_fake_forecast_result(), path)
    log_forecast_run(_fake_forecast_result(), path)
    with path.open(encoding="utf-8") as f:
        lines = f.readlines()
    assert lines.count(",".join(RUN_LOG_COLUMNS) + "\n") == 1
    assert len(lines) == 3  # header + 2 rows


def test_log_forecast_run_records_the_chosen_models_backtest_metrics(tmp_path: Path) -> None:
    path = tmp_path / "runs.csv"
    result = _fake_forecast_result()
    log_forecast_run(result, path)
    row = _read_rows(path)[0]
    metrics = json.loads(row["metrics"])
    assert metrics["wape"] == 0.1
    assert row["model"] == "naive"


def test_log_inventory_run_records_the_three_formula_outputs(tmp_path: Path) -> None:
    path = tmp_path / "runs.csv"
    plan = InventoryPlan(
        request=InventoryRequest(
            mean_demand_per_period=100,
            demand_std_per_period=10,
            lead_time_periods=1,
            ordering_cost_per_order=50,
            holding_cost_per_unit_per_year=2,
        ),
        z_score=1.64,
        safety_stock=16.4,
        reorder_point=116.4,
        economic_order_quantity=500.0,
    )
    log_inventory_run(plan, path)
    row = _read_rows(path)[0]
    metrics = json.loads(row["metrics"])
    assert metrics["safety_stock"] == 16.4
    assert metrics["economic_order_quantity"] == 500.0


def test_log_classifier_run_records_accuracy_and_f1(tmp_path: Path) -> None:
    path = tmp_path / "runs.csv"
    result = ClassifierResult(
        model="random_forest",
        features_used=["StockTurnover"],
        leakage_safe=True,
        n_train=100,
        n_test=25,
        accuracy=0.9,
        f1=0.5,
        calibration=[
            CalibrationPoint(mean_predicted_prob=0.1, fraction_of_positives=0.1, bin_count=5)
        ],
    )
    log_classifier_run(result, path)
    row = _read_rows(path)[0]
    assert row["model"] == "random_forest"
    params = json.loads(row["params"])
    assert params["leakage_safe"] is True
    metrics = json.loads(row["metrics"])
    assert metrics["accuracy"] == 0.9
    assert metrics["f1"] == 0.5


def test_append_run_log_json_encodes_params_and_metrics_into_single_cells(tmp_path: Path) -> None:
    from copilot.ml.run_log import RunLogEntry

    path = tmp_path / "runs.csv"
    entry = RunLogEntry(
        timestamp="2026-10-14T00:00:00+00:00",
        tool="example",
        model="example_model",
        params={"a": 1},
        metrics={"b": 2.0},
    )
    append_run_log(path, entry)
    row = _read_rows(path)[0]
    assert json.loads(row["params"]) == {"a": 1}
    assert json.loads(row["metrics"]) == {"b": 2.0}


def _fake_forecast_result() -> ForecastResult:
    req = ForecastRequest(level="portfolio", horizon_months=2)
    return ForecastResult(
        request=req,
        history=[MonthlyPoint(year=2024, month=i + 1, value=100.0) for i in range(8)],
        forecast=[MonthlyPoint(year=2025, month=i + 1, value=100.0) for i in range(2)],
        chosen_model="naive",
        backtest=[
            BacktestMetrics(model="ets", n_origins=2, wape=0.2, mase=1.1, bias=1.0),
            BacktestMetrics(model="naive", n_origins=2, wape=0.1, mase=1.0, bias=0.5),
        ],
    )
