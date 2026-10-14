"""CSV run-log for the ML tools (Day 5 step 5): MLflow was cut for this sprint per the sprint
doc, so every forecast/inventory/classifier run appends one flat row to a plain CSV instead --
no tracking server, no extra dependency, something `pandas.read_csv` or Excel opens directly.

Purpose : an append-only audit trail of every tool call -- what was run, with what inputs, and
          what came back -- so a run can be compared against an earlier one without re-running
          it, and so a reviewer doesn't have to trust a narrative about accuracy numbers when
          the actual historical runs are sitting in a CSV.
Inputs  : the three ML tools' own result objects (`ForecastResult`, `InventoryPlan`,
          `ClassifierResult`); one `log_*_run()` builder per tool flattens each into a
          `RunLogEntry` row.
Outputs : one appended row per call to `append_run_log()`. The file is created with a header on
          first use; every row shares the same columns (`params` and `metrics` are JSON-encoded
          into single cells) so the CSV stays tabular even though the three tools' own result
          shapes differ.

Deliberately NOT a database and NOT MLflow: this project's whole ML surface is three tools
called a handful of times a day, not a training pipeline needing experiment comparison UI,
artifact storage, or a tracking server to operate. A CSV is the honest-sized tool for this job;
see docs/PROJECT_PROGRESS.md's Day 5 checklist for the "MLflow cut" decision this implements.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from copilot.ml.forecast import ForecastResult
from copilot.ml.inventory import InventoryPlan
from copilot.ml.risk_classifier import ClassifierResult

RUN_LOG_COLUMNS: tuple[str, ...] = ("timestamp", "tool", "model", "params", "metrics")


class RunLogEntry(BaseModel):
    timestamp: str
    tool: str
    model: str
    params: dict[str, Any]
    metrics: dict[str, Any]


def append_run_log(path: Path, entry: RunLogEntry) -> None:
    """Append one row, writing the header first if `path` doesn't exist yet."""
    is_new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(RUN_LOG_COLUMNS)
        writer.writerow(
            [
                entry.timestamp,
                entry.tool,
                entry.model,
                json.dumps(entry.params),
                json.dumps(entry.metrics),
            ]
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def log_forecast_run(result: ForecastResult, path: Path) -> RunLogEntry:
    chosen = next(b for b in result.backtest if b.model == result.chosen_model)
    entry = RunLogEntry(
        timestamp=_now(),
        tool="forecast_demand",
        model=result.chosen_model,
        params={
            "level": result.request.level,
            "vendor_name": result.request.vendor_name,
            "horizon_months": result.request.horizon_months,
        },
        metrics={"wape": chosen.wape, "mase": chosen.mase, "bias": chosen.bias},
    )
    append_run_log(path, entry)
    return entry


def log_inventory_run(plan: InventoryPlan, path: Path) -> RunLogEntry:
    entry = RunLogEntry(
        timestamp=_now(),
        tool="compute_inventory_plan",
        model="eoq_formula",
        params={
            "service_level": plan.request.service_level,
            "lead_time_periods": plan.request.lead_time_periods,
        },
        metrics={
            "safety_stock": plan.safety_stock,
            "reorder_point": plan.reorder_point,
            "economic_order_quantity": plan.economic_order_quantity,
        },
    )
    append_run_log(path, entry)
    return entry


def log_classifier_run(result: ClassifierResult, path: Path) -> RunLogEntry:
    entry = RunLogEntry(
        timestamp=_now(),
        tool="classify_sku_risk",
        model=result.model,
        params={"leakage_safe": result.leakage_safe, "n_features": len(result.features_used)},
        metrics={
            "accuracy": result.accuracy,
            "f1": result.f1,
            "n_train": result.n_train,
            "n_test": result.n_test,
        },
    )
    append_run_log(path, entry)
    return entry
