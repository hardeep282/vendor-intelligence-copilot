"""Tests for safety stock / reorder point / EOQ (Day 5 step 4).

Pure arithmetic -- no fakes, no network, no LLM. Expected values hand-computed from the
formulas in `copilot.ml.inventory`'s module docstring.
"""

from __future__ import annotations

import pytest

from copilot.ml.forecast import BacktestMetrics, ForecastRequest, ForecastResult, MonthlyPoint
from copilot.ml.inventory import (
    InventoryRequest,
    compute_inventory_plan,
    demand_stats_from_backtest,
    economic_order_quantity,
    reorder_point,
    safety_stock,
)


def test_safety_stock_scales_with_sqrt_lead_time() -> None:
    # z=2, sigma=10, L=4 -> SS = 2 * 10 * sqrt(4) = 40
    assert safety_stock(demand_std_per_period=10, lead_time_periods=4, z_score=2) == pytest.approx(
        40.0
    )


def test_safety_stock_is_zero_with_zero_demand_variability() -> None:
    assert safety_stock(demand_std_per_period=0, lead_time_periods=4, z_score=2) == 0.0


def test_reorder_point_adds_lead_time_demand_and_safety_stock() -> None:
    # mean=100/period, L=2 periods -> expected demand during lead time = 200, + SS of 15 = 215
    assert reorder_point(mean_demand_per_period=100, lead_time_periods=2, ss=15) == pytest.approx(
        215.0
    )


def test_eoq_matches_the_wilson_formula() -> None:
    # EOQ = sqrt(2 * 10000 * 50 / 2) = sqrt(500000) ~= 707.1068
    eoq = economic_order_quantity(
        annual_demand=10000, ordering_cost_per_order=50, holding_cost_per_unit_per_year=2
    )
    assert eoq == pytest.approx(707.1068, abs=1e-3)


def test_eoq_doubles_order_quantity_when_ordering_cost_quadruples() -> None:
    # EOQ is proportional to sqrt(S): 4x ordering cost -> 2x EOQ.
    base = economic_order_quantity(1000, 100, 5)
    quadrupled = economic_order_quantity(1000, 400, 5)
    assert quadrupled == pytest.approx(base * 2)


def test_compute_inventory_plan_wires_all_three_formulas_together() -> None:
    req = InventoryRequest(
        mean_demand_per_period=1000,
        demand_std_per_period=150,
        lead_time_periods=1,
        service_level=0.95,
        periods_per_year=12,
        ordering_cost_per_order=200,
        holding_cost_per_unit_per_year=5,
    )
    plan = compute_inventory_plan(req)
    # z for 95% service level ~= 1.6449
    assert plan.z_score == pytest.approx(1.6449, abs=1e-3)
    assert plan.safety_stock == pytest.approx(1.6449 * 150, abs=1e-1)
    assert plan.reorder_point == pytest.approx(1000 + plan.safety_stock, abs=1e-6)
    annual_demand = 1000 * 12
    expected_eoq = (2 * annual_demand * 200 / 5) ** 0.5
    assert plan.economic_order_quantity == pytest.approx(expected_eoq)


def test_higher_service_level_increases_safety_stock() -> None:
    low = compute_inventory_plan(
        InventoryRequest(
            mean_demand_per_period=500,
            demand_std_per_period=80,
            lead_time_periods=2,
            service_level=0.80,
            ordering_cost_per_order=100,
            holding_cost_per_unit_per_year=3,
        )
    )
    high = compute_inventory_plan(
        InventoryRequest(
            mean_demand_per_period=500,
            demand_std_per_period=80,
            lead_time_periods=2,
            service_level=0.99,
            ordering_cost_per_order=100,
            holding_cost_per_unit_per_year=3,
        )
    )
    assert high.safety_stock > low.safety_stock
    assert high.reorder_point > low.reorder_point


def _fake_forecast(forecast_values: list[float], history_values: list[float]) -> ForecastResult:
    req = ForecastRequest(level="portfolio", horizon_months=len(forecast_values))
    return ForecastResult(
        request=req,
        history=[
            MonthlyPoint(year=2024, month=i + 1, value=v) for i, v in enumerate(history_values)
        ],
        forecast=[
            MonthlyPoint(year=2025, month=i + 1, value=v) for i, v in enumerate(forecast_values)
        ],
        chosen_model="naive",
        backtest=[
            BacktestMetrics(model="ets", n_origins=5, wape=0.1, mase=1.0, bias=2.0),
            BacktestMetrics(model="naive", n_origins=5, wape=0.1, mase=1.0, bias=3.0),
        ],
    )


def test_demand_stats_from_backtest_mean_comes_from_the_forecast() -> None:
    # Flat naive forecast on purpose: mean must still come from the forecast, not history.
    mean, _ = demand_stats_from_backtest(
        _fake_forecast([200.0, 200.0, 200.0], history_values=[100.0] * 12)
    )
    assert mean == pytest.approx(200.0)


def test_demand_stats_from_backtest_std_is_nonzero_for_a_flat_forecast() -> None:
    # The forecast itself is perfectly flat (variance 0); std must come from history instead,
    # or every flat-forecast call would silently hand back a zero safety stock.
    history = [100.0, 110.0, 95.0, 120.0, 130.0, 90.0, 140.0, 125.0, 150.0, 160.0, 145.0, 170.0]
    mean, std = demand_stats_from_backtest(_fake_forecast([200.0, 200.0], history))
    assert std > 0


def test_demand_stats_from_backtest_std_is_zero_for_constant_diffs() -> None:
    # history = [100, 110, 120] -> diffs = [10, 10] -> no sample variance in the diffs.
    mean, std = demand_stats_from_backtest(_fake_forecast([999.0], [100.0, 110.0, 120.0]))
    assert std == pytest.approx(0.0)


def test_demand_stats_from_backtest_falls_back_with_only_two_history_points() -> None:
    # history = [100, 115] -> exactly 1 diff -> no sample variance possible -> |diff| fallback.
    mean, std = demand_stats_from_backtest(_fake_forecast([999.0], [100.0, 115.0]))
    assert std == pytest.approx(15.0)


def test_demand_stats_from_backtest_raises_with_fewer_than_two_history_points() -> None:
    with pytest.raises(ValueError, match="at least 2 history points"):
        demand_stats_from_backtest(_fake_forecast([999.0], [100.0]))
