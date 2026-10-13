# ADR-000: Corrections to the master prompt

Date: 2026-10-10 · Status: Accepted

## Context
Section 2 of the master build prompt (v2.3) disagreed with the live analytics repository.

## Decision
Treat the repository as the source of truth. Corrections carried into this build:

1. **XGBoost was never implemented.** Only the Random Forest exists (accuracy 95%, F1 0.86 after removing the leaking `ProfitMargin` feature). XGBoost is built on Day 5.
2. **Excel ETS MAPE of 9.84% is an in-sample fit,** not forecast accuracy. Out-of-sample baselines from `forecast_backtest.py`: flagship SKU 15.7%, top-50 median 15.4%, portfolio naive 11.8%.
3. **View names** in the repo are `vw_*` (for example `vw_ProfitLeakage`), not `gold_*`.
4. **Power BI** has 4 pages (Executive Summary, Commercial Deep Dive, Risk Dashboard, Vendor Detail).
5. **`vendor_insights.py`** calls `claude-opus-4-5`; the model becomes a config value on Day 3.
6. The K-Means notebook code labels the 65%-margin cluster "At-Risk" while the write-up says "Premium Niche"; fix when K-Means is revisited.

## Consequences
Every number in this repo's README must come from code here. Claims about XGBoost appear only after Day 5.
