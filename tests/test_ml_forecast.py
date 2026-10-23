"""Tests for the demand forecast tool (Day 5 step 1).

Pure-series tests run real `statsforecast` calls against small synthetic series (deterministic,
no network, no API key -- CPU-only model fitting). `forecast_demand()` end-to-end tests run
against the real snapshot and are skipped when it has not been built, same pattern as
`tests/test_store_security.py`.
"""

from __future__ import annotations

import pytest

from copilot.data.store import DB_NAME, connect
from copilot.ml.forecast import (
    SEASONALITY_NOTE,
    ForecastRequest,
    forecast_demand,
    rolling_origin_backtest,
)
from copilot.settings import get_settings

pytestmark_snapshot = pytest.mark.skipif(
    not (get_settings().snapshot_dir / DB_NAME).exists(), reason="snapshot not built"
)


# -- ForecastRequest validation -----------------------------------------------------------


def test_vendor_level_requires_a_vendor_name() -> None:
    with pytest.raises(ValueError, match="vendor_name is required"):
        ForecastRequest(level="vendor")


def test_portfolio_level_forbids_a_vendor_name() -> None:
    with pytest.raises(ValueError, match="must be omitted"):
        ForecastRequest(level="portfolio", vendor_name="ACME")


def test_portfolio_request_is_valid_without_a_vendor_name() -> None:
    req = ForecastRequest(level="portfolio")
    assert req.vendor_name is None


def test_first_backtest_origin_floor_is_seven() -> None:
    # statsforecast's AutoETS raises NotImplementedError("tiny datasets") below 7 in-sample
    # points -- confirmed empirically against the installed version (see forecast.py docstring).
    with pytest.raises(ValueError):
        ForecastRequest(level="portfolio", first_backtest_origin=6)


# -- rolling_origin_backtest, pure series, real statsforecast calls -----------------------


def test_backtest_rejects_a_first_origin_with_nothing_left_to_forecast() -> None:
    with pytest.raises(ValueError, match="first_origin"):
        rolling_origin_backtest([1.0] * 7, first_origin=7)


def test_backtest_on_a_near_flat_series_gives_naive_small_wape() -> None:
    # Almost flat with one single-step bump at index 6, so MASE's in-sample scale isn't zero
    # (a perfectly constant series makes MASE undefined by definition -- see
    # test_ml_metrics.py) but naive still only misses on the one origin that straddles the
    # bump (origin 7, predicting month 8 from the bumped month 7): 1 error out of 5 origins.
    y = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 101.0, 100.0, 100.0, 100.0, 100.0, 100.0]
    ets_m, naive_m = rolling_origin_backtest(y, first_origin=7)
    assert naive_m.wape == pytest.approx(1 / 500)  # |101-100| / sum(5 actuals of 100)
    assert naive_m.n_origins == 5  # origins 7..11 (0-indexed), predicting months 8..12


def test_backtest_returns_metrics_for_both_models_with_matching_origin_counts() -> None:
    y = [100.0, 110.0, 95.0, 120.0, 130.0, 90.0, 140.0, 125.0, 150.0, 160.0, 145.0, 170.0]
    ets_m, naive_m = rolling_origin_backtest(y, first_origin=7)
    assert ets_m.model == "ets"
    assert naive_m.model == "naive"
    assert ets_m.n_origins == naive_m.n_origins == 5
    assert ets_m.wape >= 0
    assert naive_m.wape >= 0


# -- forecast_demand, end to end against the real snapshot ---------------------------------


@pytestmark_snapshot
def test_forecast_demand_portfolio_produces_the_requested_horizon() -> None:
    result = forecast_demand(ForecastRequest(level="portfolio", horizon_months=3))
    assert len(result.forecast) == 3
    assert len(result.history) == 12  # one calendar year in the snapshot
    assert result.chosen_model in ("ets", "naive")
    assert {b.model for b in result.backtest} == {"ets", "naive"}
    assert result.seasonality_note == SEASONALITY_NOTE


@pytestmark_snapshot
def test_forecast_demand_picks_the_lower_wape_model() -> None:
    result = forecast_demand(ForecastRequest(level="portfolio", horizon_months=1))
    by_model = {b.model: b.wape for b in result.backtest}
    assert result.chosen_model == min(by_model, key=lambda m: by_model[m])


@pytestmark_snapshot
def test_forecast_demand_vendor_level_sums_a_vendor_across_health_categories() -> None:
    # `store.connect()` locks DuckDB's configuration on the shared in-process connection to
    # this file, so a second `connect()` call in the same process raises -- reuse one
    # connection for both the vendor lookup and the tool call, same as any real caller would.
    con = connect()
    vendor = con.execute(
        "SELECT VendorName FROM vendor_tiering ORDER BY TotalRevenue DESC LIMIT 1"
    ).fetchone()[0]
    result = forecast_demand(
        ForecastRequest(level="vendor", vendor_name=vendor, horizon_months=1), con=con
    )
    assert len(result.history) >= 1
    assert all(p.value >= 0 for p in result.history)


@pytestmark_snapshot
def test_forecast_demand_unknown_vendor_raises() -> None:
    con = connect()
    with pytest.raises(ValueError, match="no demand history"):
        forecast_demand(
            ForecastRequest(level="vendor", vendor_name="NOT A REAL VENDOR XYZ"), con=con
        )
