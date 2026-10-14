"""Inventory tools (Day 5 step 4): safety stock, reorder point, EOQ from forecast outputs.

Purpose : the Inventory Planning agent's tools (A2). Pure, well-known OR formulas -- no LLM, no
          fitting, no fakes needed, same category as `copilot.ml.metrics`: run for real in any
          environment. Deliberately takes demand *statistics* (mean, std dev) rather than a
          `ForecastResult` directly, so these functions stay testable in isolation and so a
          caller can feed them real backtest-residual variability instead of a guessed std dev
          -- see `demand_stats_from_backtest()` below, which is the bridge from
          `copilot.ml.forecast`'s output to these formulas' inputs.
Inputs  : `InventoryRequest` -- mean demand per period, demand std dev per period, lead time (in
          the same period unit), a target service level, and the two EOQ cost inputs.
Outputs : `InventoryPlan` -- safety stock, reorder point, EOQ, and the z-score the service level
          implied.

Formulas (standard OR textbook form, e.g. Silver/Pyke/Peterson *Inventory Management and
Production Planning and Scheduling*; Hyndman & Athanasopoulos FPP3 ch. on inventory):
  - Safety stock:  SS = z * sigma_d * sqrt(L)
      z from the target service level via the inverse standard normal CDF (scipy.stats.norm.ppf)
      -- a 95% service level means a 5% chance of stocking out during the lead time, assuming
      demand during lead time is approximately normal. sigma_d is demand std dev *per period*
      (e.g. per month); the sqrt(L) scaling is because variance adds across L independent
      periods of lead time, so std dev scales with sqrt(L), not L.
  - Reorder point:  ROP = d_bar * L + SS
      Expected demand consumed during the lead time, plus the safety buffer above it.
  - EOQ (Wilson, 1913):  EOQ = sqrt(2 * D * S / H)
      D = demand over the same period H and S are costed in (annualised here, since holding
      cost is conventionally an annual rate); S = fixed cost per order; H = holding cost per
      unit per that period. Minimises ordering cost + holding cost at the point where they're
      equal -- the classic EOQ derivation, included in the module docstring rather than
      re-derived in the function, per the project's existing docstring convention.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from scipy.stats import norm

from copilot.ml.forecast import ForecastResult


class InventoryRequest(BaseModel):
    mean_demand_per_period: float = Field(ge=0)
    demand_std_per_period: float = Field(ge=0)
    lead_time_periods: float = Field(gt=0)
    service_level: float = Field(gt=0, lt=1, default=0.95)
    periods_per_year: int = Field(
        gt=0, default=12, description="How many `mean_demand_per_period` periods make a year."
    )
    ordering_cost_per_order: float = Field(gt=0)
    holding_cost_per_unit_per_year: float = Field(gt=0)


class InventoryPlan(BaseModel):
    request: InventoryRequest
    z_score: float
    safety_stock: float
    reorder_point: float
    economic_order_quantity: float


def safety_stock(demand_std_per_period: float, lead_time_periods: float, z_score: float) -> float:
    """SS = z * sigma_d * sqrt(L). See module docstring for why sqrt(L), not L."""
    return float(z_score * demand_std_per_period * (lead_time_periods**0.5))


def reorder_point(mean_demand_per_period: float, lead_time_periods: float, ss: float) -> float:
    """ROP = expected demand during the lead time + the safety-stock buffer."""
    return mean_demand_per_period * lead_time_periods + ss


def economic_order_quantity(
    annual_demand: float, ordering_cost_per_order: float, holding_cost_per_unit_per_year: float
) -> float:
    """EOQ = sqrt(2 * D * S / H) (Wilson, 1913). See module docstring for the cost balance."""
    return float(
        (2 * annual_demand * ordering_cost_per_order / holding_cost_per_unit_per_year) ** 0.5
    )


def compute_inventory_plan(request: InventoryRequest) -> InventoryPlan:
    """Tool entry point: run all three formulas from one request."""
    z = float(norm.ppf(request.service_level))
    ss = safety_stock(request.demand_std_per_period, request.lead_time_periods, z)
    rop = reorder_point(request.mean_demand_per_period, request.lead_time_periods, ss)
    annual_demand = request.mean_demand_per_period * request.periods_per_year
    eoq = economic_order_quantity(
        annual_demand, request.ordering_cost_per_order, request.holding_cost_per_unit_per_year
    )
    return InventoryPlan(
        request=request,
        z_score=z,
        safety_stock=ss,
        reorder_point=rop,
        economic_order_quantity=eoq,
    )


def demand_stats_from_backtest(forecast: ForecastResult) -> tuple[float, float]:
    """Mean of the forecast horizon, paired with demand variability from *history*, as the
    (mean, std) pair `InventoryRequest` needs.

    Mean comes from the forecast (forward-looking, where demand is heading). Std dev
    deliberately does NOT come from variance across the forecast points: both models here can
    produce a flat-line forecast (naive always does; this project's ETS frequently reduces to
    one too, see `forecast.py`'s module docstring on why) and a flat forecast has zero variance
    by construction -- using it would silently report zero demand uncertainty and hand back a
    zero safety stock, which is wrong, not conservative. Instead this uses the historical
    month-over-month change in `forecast.history`, which is always non-zero for real demand
    data and is the standard practice when the forecast itself is naive or near-flat (Silver/
    Pyke/Peterson, ch. 7: lead-time demand variance is estimated from historical period-to-
    period variability when a model-based residual series isn't being used directly).
    """
    fc_values = [p.value for p in forecast.forecast]
    mean = sum(fc_values) / len(fc_values)

    hist_values = [p.value for p in forecast.history]
    if len(hist_values) < 2:
        raise ValueError("need at least 2 history points to estimate demand variability")
    diffs = [hist_values[i] - hist_values[i - 1] for i in range(1, len(hist_values))]
    diff_mean = sum(diffs) / len(diffs)
    if len(diffs) < 2:
        # Exactly 2 history points -> exactly 1 diff -> no sample variance of the diffs.
        # Fall back to the diff's own magnitude as a non-zero variability proxy.
        return mean, abs(diffs[0])
    variance = sum((d - diff_mean) ** 2 for d in diffs) / (len(diffs) - 1)
    return mean, variance**0.5
