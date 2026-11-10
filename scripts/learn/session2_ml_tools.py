"""Learning script for session 2: the ML tools (forecast, inventory maths, risk classifier).

Purpose : run the real code behind the Forecasting & Risk and Inventory Planning specialists in
          eight small, numbered steps, so you can watch it work in VS Code's debugger. All of
          this is plain Python: no Claude calls, free, no API key, the same result every time.
Inputs  : the local snapshot (build it first with `uv run python scripts/build_snapshot.py`).
          Step 7 uses the clearly-synthetic SKU fixture, because the snapshot deliberately holds
          no product-level rows (ADR-002); the real-data numbers come from your laptop run of
          `scripts/train_risk_classifier.py` and are printed alongside for comparison.
Outputs : plain-English printout of each step. Nothing is written anywhere.

How to use it in VS Code (see the Code Trail page, chapter 4): put a red dot on the first line
inside any `step_...` function, press F5, pick "Python Debugger: Current File", then F10 to go
line by line and F11 to step into a call. Or just run it:
    uv run python scripts/learn/session2_ml_tools.py

Added 10 Nov 2026 for the learning sessions. It only *uses* the copilot's code; it changes
nothing about how the copilot behaves.
"""

from __future__ import annotations

import calendar

import duckdb

from copilot.agents.model_selection import _CATALOG_NOTES, MODEL_CATALOG
from copilot.cli import use_utf8_output
from copilot.data import store
from copilot.ml.forecast import ForecastRequest, ForecastResult, forecast_demand
from copilot.ml.inventory import (
    InventoryRequest,
    compute_inventory_plan,
    demand_stats_from_backtest,
)
from copilot.ml.metrics import bias, mase, wape
from copilot.ml.risk_classifier import LEAKING_FEATURES, make_synthetic_skus, train_and_evaluate

TOP_VENDOR = "DIAGEO NORTH AMERICA INC"


def heading(n: int, title: str) -> None:
    print(f"\n{'=' * 72}\nSTEP {n}: {title}\n{'=' * 72}")


def step_1_the_history(con: duckdb.DuckDBPyConnection) -> list[float]:
    """The whole portfolio's units sold per month: all the forecast ever has to learn from."""
    heading(1, "The history: 12 months of units sold, portfolio-wide")
    rows = con.execute(
        "SELECT SalesMonth, MonthlyDemand FROM portfolio_monthly_demand ORDER BY SalesMonth"
    ).fetchall()
    peak = max(v for _, v in rows)
    for month, value in rows:
        bar = "#" * round(value / peak * 40)
        print(f"  {calendar.month_abbr[month]} 2024 {value:>10,.0f}  {bar}")
    print("\n  One calendar year only. December is the peak, and there's no earlier December")
    print("  to learn from, so no model here can know that December is seasonal.")
    return [float(v) for _, v in rows]


def step_2_backtest_by_hand(y: list[float]) -> None:
    """The rolling-origin backtest, done by hand for the naive model (ml/forecast.py)."""
    heading(2, "Backtest by hand: forecast each month from only the months before it")
    first_origin = 7  # same default as ForecastRequest.first_backtest_origin
    actual, predicted = [], []
    for origin in range(first_origin, len(y)):
        guess = y[origin - 1]  # naive: "next month = last month"
        actual.append(y[origin])
        predicted.append(guess)
        print(
            f"  using months 1-{origin:<2} predict {calendar.month_abbr[origin + 1]}: "
            f"guess {guess:>10,.0f}  actual {y[origin]:>10,.0f}  "
            f"error {guess - y[origin]:>+10,.0f}"
        )
    print(f"\n  WAPE  = {wape(actual, predicted):.4f}  (total error / total actual)")
    print(
        f"  MASE  = {mase(actual, predicted, y[:first_origin]):.3f}  "
        "(error / typical month-to-month change in months 1-7; above 1 = bigger)"
    )
    print(f"  bias  = {bias(actual, predicted):,.0f}  (negative = guesses ran below actual)")


def step_3_the_real_forecast_tool(con: duckdb.DuckDBPyConnection) -> ForecastResult:
    """The same backtest for ETS and naive, then a 3-month forecast with whichever wins."""
    heading(3, "The forecast tool: ETS vs naive, the winner on WAPE forecasts")
    result = forecast_demand(ForecastRequest(level="portfolio", horizon_months=3), con=con)
    for bt in result.backtest:
        print(f"  {bt.model:<5} WAPE={bt.wape:.4f}  MASE={bt.mase:.3f}  bias={bt.bias:,.0f}")
    print(f"\n  chosen: {result.chosen_model} (ties go to ETS; here naive is a hair better)")
    for p in result.forecast:
        print(f"    {calendar.month_abbr[p.month]} {p.year}: {p.value:>12,.0f} units")
    print("\n  Warnings passed on to the answer writer:")
    for w in result.warnings:
        print(f"    - {w}")
    return result


def step_4_one_vendor(con: duckdb.DuckDBPyConnection) -> None:
    """Vendor-level forecasts use the same code, on vendor_monthly_demand."""
    heading(4, f"Same tool, one vendor: {TOP_VENDOR}")
    result = forecast_demand(
        ForecastRequest(level="vendor", vendor_name=TOP_VENDOR, horizon_months=3), con=con
    )
    ets, naive = result.backtest
    print(f"  ETS WAPE {ets.wape:.4f} vs naive WAPE {naive.wape:.4f} -> {result.chosen_model}")
    print(f"  next 3 months: {[round(p.value) for p in result.forecast]}")
    print(f"  {len(result.warnings)} warning(s), so the specialist reports confidence 'low'.")


def step_5_inventory_plan(forecast: ForecastResult) -> None:
    """Safety stock, reorder point and EOQ from the forecast (ml/inventory.py)."""
    heading(5, "Inventory maths from the forecast")
    mean, std = demand_stats_from_backtest(forecast)
    print(f"  mean demand per month (from the forecast)        {mean:>12,.0f}")
    print(f"  variability per month (from history's changes)  {std:>12,.0f}")
    base = {
        "mean_demand_per_period": mean,
        "demand_std_per_period": std,
        "lead_time_periods": 1.0,
        "ordering_cost_per_order": 500.0,  # assumption, not from your data
        "holding_cost_per_unit_per_year": 0.5,  # assumption, not from your data
    }
    print("\n  service level   z     safety stock   reorder point")
    for level in (0.90, 0.95, 0.99):
        plan = compute_inventory_plan(InventoryRequest(service_level=level, **base))
        print(
            f"      {level:.0%}       {plan.z_score:.2f}  {plan.safety_stock:>13,.0f}"
            f"  {plan.reorder_point:>14,.0f}"
        )
    plan = compute_inventory_plan(InventoryRequest(**base))
    print(f"\n  EOQ at the default 95%: {plan.economic_order_quantity:,.0f} units per order")
    print("  Going from 95% to 99% service needs about 41% more safety stock.")


def step_6_the_flat_forecast_trap(forecast: ForecastResult) -> None:
    """The bug caught before shipping: variability taken from a flat forecast is zero."""
    heading(6, "The trap: measuring variability from a flat forecast")
    values = [p.value for p in forecast.forecast]
    spread = max(values) - min(values)
    print(f"  the naive forecast repeats one number: {values}  (spread {spread:,.0f})")
    wrong = compute_inventory_plan(
        InventoryRequest(
            mean_demand_per_period=values[0],
            demand_std_per_period=0.0,  # what "std dev across the forecast" would give
            lead_time_periods=1.0,
            ordering_cost_per_order=500.0,
            holding_cost_per_unit_per_year=0.5,
        )
    )
    print(f"  safety stock if variability came from it: {wrong.safety_stock:,.0f}  <- wrong")
    print("  So demand_stats_from_backtest takes variability from history instead.")


def step_7_the_leaking_feature() -> None:
    """Risk classifier with and without the margin columns that rebuild the label."""
    heading(7, "The leaking feature: risk model with and without margin columns")
    df = make_synthetic_skus()  # clearly synthetic: real column names, invented values
    print(f"  {len(df):,} synthetic SKUs; label = HealthStatus 'Loss Making' or 'At Risk'")
    print(f"  columns treated as leaks: {', '.join(LEAKING_FEATURES)}")
    leaky = train_and_evaluate(df, "random_forest", leakage_safe=False)
    safe = train_and_evaluate(df, "random_forest", leakage_safe=True, compute_shap=True)
    print(f"\n  synthetic, leaky : accuracy {leaky.accuracy:.3f}  F1 {leaky.f1:.3f}")
    print(f"  synthetic, safe  : accuracy {safe.accuracy:.3f}  F1 {safe.f1:.3f}")
    print(f"  top driver once the leak is gone: {safe.top_shap_drivers[0].feature}")
    print("\n  Real run on your laptop (10,495 SKUs, 17 Oct), recorded in README:")
    print("    leaky : accuracy 0.997  F1 0.994   <- too good: it read the label back")
    print("    safe  : accuracy 0.952  F1 0.919   <- the honest number")


def step_8_model_selection_catalog() -> None:
    """The Model Selection Agent picks from a fixed list. Printed here without calling it."""
    heading(8, "The Model Selection Agent's closed catalogue (no AI call made here)")
    for task, families in MODEL_CATALOG.items():
        print(f"  {task}:")
        for family in families:
            print(f"    {family:<20} {_CATALOG_NOTES[family]}")
    print("\n  The agent itself is an LLM loop (propose -> critique -> revise, or abstain).")
    print("  It's a separate tool, not part of the copilot's answer flow.")


def main() -> None:
    use_utf8_output()
    con = store.connect()
    y = step_1_the_history(con)
    step_2_backtest_by_hand(y)
    forecast = step_3_the_real_forecast_tool(con)
    step_4_one_vendor(con)
    step_5_inventory_plan(forecast)
    step_6_the_flat_forecast_trap(forecast)
    step_7_the_leaking_feature()
    step_8_model_selection_catalog()
    print("\nDone. Every step above used the copilot's real code, and no AI call was made.")


if __name__ == "__main__":
    main()
