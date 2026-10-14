---
doc_type: methodology
vendor: null
version: 1
data_class: public
allowed_roles: [anonymous, viewer, analyst, approver, admin]
---

# Methodology

How this system turns the underlying vendor analytics project into answers, and the limits on
what it can honestly claim.

## Source and licensing

The underlying dataset (12.8M raw rows across 6 tables) was purchased under a Topmate licence and
must never be redistributed. This copilot never queries the raw dataset directly — it queries a
derived, aggregate-only Parquet snapshot (`data/snapshot/`) rebuilt from the analytics project's
Gold-layer views. The snapshot itself is never committed to this repo; only its manifest
(`data/snapshot/MANIFEST.json`, row counts and hashes) is tracked, so a fresh clone must rebuild
it from the workbook before anything can be queried.

## Medallion architecture (source project)

Bronze (`vendor_sales_summary`, raw) -> Silver (`vw_PortfolioHealth`, 10,495 SKUs) -> Gold views
(`vw_VendorRevenueSummary`, `vw_VendorTiering`, `vw_ParetoAnalysis`, `vw_ProfitLeakage`,
`vw_VendorRankings`, `vw_LogisticsCostSummary`, `vw_FullCostAnalysis`, and others). All views read
from `vw_VendorSalesBase`, which merges duplicate vendor-name variants into one canonical vendor.
This copilot's snapshot is built only from the Gold layer, aggregated further where needed
(vendor x month, portfolio x month) before it ever reaches Parquet.

## Forecasting: what the ETS model can and cannot claim

The original Excel ETS forecast reports 9.84% MAPE — that is an **in-sample fit** on the 12
months of training data, not an out-of-sample accuracy figure, and must never be cited as
"accuracy." The honest out-of-sample number comes from `forecast_backtest.py`'s rolling
one-month-ahead backtest: the flagship SKU scores 15.7% MAPE with a 6-month moving average, the
top-50 SKU median is 15.4%, and the portfolio-level figure is 11.8%, where a naive forecast ties.

A classical model like ETS cannot "model" a sudden structural break (a black-swan demand shock).
The correct approach is to detect the break with a formal test (a Chow test at a known date, or
Bai-Perron / CUSUM when the date isn't known), then handle it with an intervention dummy in a
dynamic regression, a post-break training window, or scenario-based forecasts — not to expect the
classical model to absorb it on its own.

## Classification models

Random Forest classifier for SKU risk: 95% accuracy, F1 0.86, **after removing the ProfitMargin
feature**, which leaked the outcome (a SKU's profit margin is causally downstream of whether it is
loss-making — including it let the model "cheat"). XGBoost has not yet been built as of this
document's current state; do not cite an XGBoost result until it exists in the repo (see
`docs/PROJECT_PROGRESS.md` for current status). K-Means clustering (k=3, silhouette 0.68) found a
"Premium Niche" cluster that the original notebook code still labels "At-Risk" — a naming
mismatch between what was found and what was written down, not a modelling error.

## Honesty rule

Nothing in a CV line, an interview answer or an agent's output claims more than what the repo or
the live site can currently demonstrate. "Benchmarked a QLoRA fine-tune" is fine once the
benchmark exists; "deployed a fine-tuned model to production" is not fine until it is actually
serving traffic.
