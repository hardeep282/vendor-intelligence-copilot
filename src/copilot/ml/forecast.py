"""Demand forecast tool (Day 5 step 1): ETS vs naive, honest out-of-sample accuracy.

Purpose : the Forecasting & Risk agent's main tool (A2). Forecasts portfolio- or vendor-level
          monthly demand from the licence-safe `portfolio_monthly_demand` /
          `vendor_monthly_demand` snapshot tables, and reports WAPE/MASE/bias from a
          rolling-origin backtest -- never from an in-sample fit (ADR-000 item 2 already
          flagged the Excel ETS's 9.84% MAPE as exactly this mistake).
Inputs  : a `ForecastRequest` (level, optional vendor name, horizon in months).
Outputs : a `ForecastResult` -- point forecasts for the next `horizon` months plus the backtest
          metrics that justify trusting (or not trusting) them.

Methodology, matched to the analytics repo's own `forecast_backtest.py` on purpose (same
rolling-origin, one-month-ahead design, so the numbers are comparable): forecast each of the
last `n_backtest_origins` months using only the months before it, "naive" means "repeat last
observed month."

**Seasonal-naive is not estimable here, and we say so rather than fake it.** The project has
only 12 months of history (R3 in docs/RAID.md). A true seasonal-naive forecast needs the same
calendar month from the *previous* year; with one year of data there is no previous year, and
`statsforecast.models.SeasonalNaive(season_length=12)` on this data returns `NaN` for every
point (confirmed empirically before writing this module). So the "naive" baseline here is the
plain one-step naive (repeat last value) -- the correct baseline given the data, not a
relabelled seasonal-naive. `AutoETS` is fit with `season_length=1` for the same reason: with
under two full years of history, statsforecast's own seasonality test cannot estimate a
12-month seasonal component, so forcing `season_length=12` would silently degrade to a trend-only
fit anyway (exactly the Excel tool's failure mode this module exists to avoid) -- better to be
honest about running ETS non-seasonally than to claim a seasonal fit that isn't really one. This
limitation is logged, not hidden: `ForecastResult.seasonality_note` carries it through to every
caller, including the Model Selection Agent (Day 5 step 6) and any future agent prompt.
"""

from __future__ import annotations

import calendar
import statistics
import warnings
from typing import Literal

import duckdb
import pandas as pd
from pydantic import BaseModel, Field
from statsforecast import StatsForecast
from statsforecast.models import AutoETS

from copilot.data import store
from copilot.ml.metrics import bias, mase, wape

SEASONALITY_NOTE = (
    "Only 12 months of history exist, so seasonality cannot be estimated (no prior year to "
    "compare against) and a true seasonal-naive baseline is undefined. 'naive' below means "
    "repeat-last-month; ETS is fit non-seasonally for the same reason. See docs/RAID.md R3."
)

#: Below two full years, the same calendar month can't be compared year on year, so a seasonal
#: peak (December, in this data) is invisible to both models.
MIN_MONTHS_FOR_SEASONALITY = 24

#: How far the last month may sit from the typical (median) earlier month before the forecast
#: is flagged: both models start from the last observed level, so an unusual last month is
#: carried straight into the next quarter. 20% is a deliberately simple, explainable rule.
LAST_MONTH_OUTLIER_RATIO = 0.20

Level = Literal["portfolio", "vendor"]


class MonthlyPoint(BaseModel):
    year: int
    month: int = Field(ge=1, le=12)
    value: float


class BacktestMetrics(BaseModel):
    model: Literal["ets", "naive"]
    n_origins: int = Field(ge=1)
    wape: float = Field(ge=0)
    mase: float = Field(ge=0)
    bias: float


class ForecastRequest(BaseModel):
    level: Level
    vendor_name: str | None = None
    horizon_months: int = Field(default=3, ge=1, le=12)
    first_backtest_origin: int = Field(
        default=7,
        ge=7,
        description=(
            "First month index (1-based) to start rolling-origin backtesting from. 7, not "
            "the analytics repo's 6, because statsforecast's AutoETS raises NotImplementedError "
            "('tiny datasets') below 7 in-sample points -- confirmed empirically, see forecast.py."
        ),
    )

    def model_post_init(self, __context: object) -> None:
        if self.level == "vendor" and not self.vendor_name:
            raise ValueError("vendor_name is required when level='vendor'")
        if self.level == "portfolio" and self.vendor_name:
            raise ValueError("vendor_name must be omitted when level='portfolio'")


class ForecastResult(BaseModel):
    request: ForecastRequest
    history: list[MonthlyPoint]
    forecast: list[MonthlyPoint]
    chosen_model: Literal["ets", "naive"]
    backtest: list[BacktestMetrics]
    seasonality_note: str = SEASONALITY_NOTE
    # Added 30 Oct 2026: plain-English cautions the drafter must pass on (see
    # `forecast_warnings`). Empty when nothing looks off.
    warnings: list[str] = Field(default_factory=list)


def forecast_warnings(history: list[MonthlyPoint], chosen_model: str) -> list[str]:
    """Cautions about this forecast, in words a business reader understands.

    Added 30 Oct 2026 after a real run forecast January to March at December's level: the
    history is one calendar year, December is its highest month (38% above the median of the
    other eleven), and the naive model repeats the last month, so the next quarter was almost
    certainly over-forecast while the answer called it "a baseline". The backtest couldn't see
    this, because no backtest month was a December following another December.
    """
    out: list[str] = []
    n = len(history)
    if n < MIN_MONTHS_FOR_SEASONALITY:
        out.append(
            f"Only {n} months of history, so seasonal patterns (such as a holiday peak) can't "
            "be learned. Treat this forecast as rough."
        )
    if n >= 3:
        last = history[-1]
        typical = statistics.median(p.value for p in history[:-1])
        if typical > 0:
            change = (last.value - typical) / typical
            if abs(change) >= LAST_MONTH_OUTLIER_RATIO:
                when = f"{calendar.month_abbr[last.month]} {last.year}"
                direction = "above" if change > 0 else "below"
                outcome = "over-forecast" if change > 0 else "under-forecast"
                carried = "repeats it" if chosen_model == "naive" else "starts from it"
                out.append(
                    f"The last month ({when}: {last.value:,.0f} units) is {abs(change):.0%} "
                    f"{direction} the typical month in this history ({typical:,.0f} units). "
                    f"The {chosen_model} "
                    f"forecast {carried}, so the next months are probably {outcome}."
                )
    return out


def _load_series(
    level: Level, vendor_name: str | None, con: duckdb.DuckDBPyConnection
) -> pd.DataFrame:
    """Monthly (year, month, value) for the portfolio or one vendor, ordered chronologically."""
    # Own cursor (31 Oct 2026): forecasting and inventory planning run in parallel threads on one
    # shared connection; interleaved calls made .df() return None ("'NoneType' object has no
    # attribute 'empty'"), reproduced 7 times in 20 parallel runs before this change, 0 after.
    cur = con.cursor()
    try:
        df = _query_series(cur, level, vendor_name)
    finally:
        cur.close()
    if df is None or df.empty:
        raise ValueError(f"no demand history for level={level!r} vendor_name={vendor_name!r}")
    return df


def _query_series(
    cur: duckdb.DuckDBPyConnection, level: Level, vendor_name: str | None
) -> pd.DataFrame:
    if level == "portfolio":
        df = cur.execute(
            "SELECT SalesYear AS year, SalesMonth AS month, MonthlyDemand AS value "
            "FROM portfolio_monthly_demand ORDER BY SalesYear, SalesMonth"
        ).df()
    else:
        df = cur.execute(
            "SELECT SalesYear AS year, SalesMonth AS month, SUM(MonthlyDemand) AS value "
            "FROM vendor_monthly_demand WHERE VendorName = ? "
            "GROUP BY SalesYear, SalesMonth ORDER BY SalesYear, SalesMonth",
            [vendor_name],
        ).df()
    return df


def _naive_forecast(y: list[float], horizon: int) -> list[float]:
    return [y[-1]] * horizon


def _ets_forecast(y: list[float], horizon: int) -> list[float]:
    """Fit AutoETS non-seasonally (see module docstring) and forecast `horizon` steps ahead."""
    ds = pd.date_range("2000-01-01", periods=len(y), freq="MS")
    df = pd.DataFrame({"unique_id": ["series"] * len(y), "ds": ds, "y": y})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # statsforecast warns about short history; we know
        sf = StatsForecast(models=[AutoETS(season_length=1, model="ZZN")], freq="MS")
        sf.fit(df)
        fc = sf.predict(h=horizon)
    return [float(v) for v in fc["AutoETS"].tolist()]


def rolling_origin_backtest(
    y: list[float], first_origin: int = 6
) -> tuple[BacktestMetrics, BacktestMetrics]:
    """One-month-ahead, expanding-window backtest for ETS and naive, matching
    `forecast_backtest.py`'s `rolling_one_step` methodology.

    `first_origin` is 1-based: with the default 6, the first forecast is made from months 1-6
    to predict month 7, then 1-7 -> 8, and so on through the last available month.
    """
    if first_origin >= len(y):
        raise ValueError(
            f"first_origin ({first_origin}) must leave at least one month to forecast "
            f"(series has {len(y)} points)"
        )
    ets_actual: list[float] = []
    ets_pred: list[float] = []
    naive_actual: list[float] = []
    naive_pred: list[float] = []
    for origin in range(first_origin, len(y)):
        train = y[:origin]
        actual = y[origin]
        naive_actual.append(actual)
        naive_pred.append(_naive_forecast(train, 1)[0])
        ets_actual.append(actual)
        ets_pred.append(_ets_forecast(train, 1)[0])

    full_train_scale = y[:first_origin]
    ets_metrics = BacktestMetrics(
        model="ets",
        n_origins=len(ets_actual),
        wape=wape(ets_actual, ets_pred),
        mase=mase(ets_actual, ets_pred, full_train_scale),
        bias=bias(ets_actual, ets_pred),
    )
    naive_metrics = BacktestMetrics(
        model="naive",
        n_origins=len(naive_actual),
        wape=wape(naive_actual, naive_pred),
        mase=mase(naive_actual, naive_pred, full_train_scale),
        bias=bias(naive_actual, naive_pred),
    )
    return ets_metrics, naive_metrics


def forecast_demand(
    request: ForecastRequest, con: duckdb.DuckDBPyConnection | None = None
) -> ForecastResult:
    """Tool entry point: backtest both models, forecast with whichever wins on WAPE."""
    owns_con = con is None
    con = con or store.connect()
    try:
        df = _load_series(request.level, request.vendor_name, con)
    finally:
        if owns_con:
            con.close()

    history = [
        MonthlyPoint(year=int(row["year"]), month=int(row["month"]), value=float(row["value"]))
        for row in df.to_dict("records")
    ]
    y = [p.value for p in history]

    ets_metrics, naive_metrics = rolling_origin_backtest(y, request.first_backtest_origin)
    chosen: Literal["ets", "naive"] = "ets" if ets_metrics.wape <= naive_metrics.wape else "naive"

    full_forecast_fn = _ets_forecast if chosen == "ets" else _naive_forecast
    fc_values = full_forecast_fn(y, request.horizon_months)

    last_year, last_month = history[-1].year, history[-1].month
    forecast_points: list[MonthlyPoint] = []
    y_i, m_i = last_year, last_month
    for v in fc_values:
        m_i += 1
        if m_i > 12:
            m_i = 1
            y_i += 1
        forecast_points.append(MonthlyPoint(year=y_i, month=m_i, value=round(v, 2)))

    return ForecastResult(
        request=request,
        history=history,
        forecast=forecast_points,
        chosen_model=chosen,
        backtest=[ets_metrics, naive_metrics],
        warnings=forecast_warnings(history, chosen),
    )
