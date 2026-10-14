"""Forecast accuracy metrics: WAPE, MASE, bias.

Purpose : pure arithmetic, no LLM and no fakes needed -- same category as
          `copilot.evals.rag_metrics` (recall@k/MRR): run for real in any environment,
          including this one, with no API key or network access required.
Inputs  : parallel sequences of actual and forecast values (one point per period), plus, for
          MASE, the in-sample training series used to scale the error.
Outputs : a single float per metric.

Why these three, not MAPE: the analytics repo's own `forecast_backtest.py` already explains why
MAPE is unreliable here (division by a small or zero actual blows up) -- this project's sprint
doc (D5) names WAPE, MASE and bias instead, which is also the FPP3 (Hyndman & Athanasopoulos)
recommended trio for exactly this failure mode:
  - WAPE (weighted/aggregate MAPE): sum(|error|) / sum(|actual|) -- one robust ratio over the
    whole backtest window instead of averaging a per-period percentage that can blow up when
    `actual` is near zero.
  - MASE (Hyndman & Koehler, 2006): MAE(forecast) / MAE(naive one-step-ahead, in-sample) --
    scale-free, comparable across series, and exactly 1.0 means "as good as naive." >1.0 means
    the model is worse than guessing last period's value.
  - Bias: mean(forecast - actual) -- signed, so a model that is accurate on average but
    systematically over- or under-forecasts still shows up (WAPE and MASE are both
    magnitude-only and would hide this).
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def wape(actual: Sequence[float], forecast: Sequence[float]) -> float:
    """Weighted Absolute Percentage Error: sum(|actual-forecast|) / sum(|actual|)."""
    a = np.asarray(actual, dtype=float)
    f = np.asarray(forecast, dtype=float)
    if a.shape != f.shape:
        raise ValueError(f"actual and forecast must be the same length ({a.shape} vs {f.shape})")
    denom = np.sum(np.abs(a))
    if denom == 0:
        raise ValueError("WAPE is undefined when every actual value is 0")
    return float(np.sum(np.abs(a - f)) / denom)


def mase(actual: Sequence[float], forecast: Sequence[float], train: Sequence[float]) -> float:
    """Mean Absolute Scaled Error (Hyndman & Koehler, 2006).

    `train` is the in-sample history the naive one-step-ahead scale is computed from -- it must
    have at least 2 points (one lag-1 difference). Scale-free: 1.0 == as good as naive,
    < 1.0 == better than naive, > 1.0 == worse than naive.
    """
    a = np.asarray(actual, dtype=float)
    f = np.asarray(forecast, dtype=float)
    t = np.asarray(train, dtype=float)
    if a.shape != f.shape:
        raise ValueError(f"actual and forecast must be the same length ({a.shape} vs {f.shape})")
    if t.size < 2:
        raise ValueError("train must have at least 2 points to compute a naive in-sample scale")
    scale = float(np.mean(np.abs(np.diff(t))))
    if scale == 0:
        raise ValueError("MASE is undefined when the training series is constant (scale == 0)")
    mae = float(np.mean(np.abs(a - f)))
    return mae / scale


def bias(actual: Sequence[float], forecast: Sequence[float]) -> float:
    """Signed mean error: mean(forecast - actual). Positive == over-forecasting on average."""
    a = np.asarray(actual, dtype=float)
    f = np.asarray(forecast, dtype=float)
    if a.shape != f.shape:
        raise ValueError(f"actual and forecast must be the same length ({a.shape} vs {f.shape})")
    return float(np.mean(f - a))
