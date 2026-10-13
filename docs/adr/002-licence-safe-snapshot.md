# ADR-002: Licence-safe snapshot, vendor-level only, never committed

Date: 2026-10-10 · Status: Accepted (revisit when R1 is resolved)

## Context
The raw dataset was purchased (Topmate) and must not be redistributed. The app must answer vendor questions publicly.

## Decision
- The app queries only **aggregate tables**: the seven vendor-level views, vendor-by-month demand, portfolio-by-month demand, and SKU health **counts** per vendor and for the portfolio.
- SKU-level sheets (`vw_PortfolioHealth`, `vw_CleanAnalysis`, `output_monthly_demand`) are only ever **aggregated** by `scripts/build_snapshot.py`; no SKU name, brand, size or price is copied.
- `copilot.data.guard` rejects any table with SKU-level columns or more than 2,000 rows. A test enforces it.
- Parquet files are **git-ignored**; only `MANIFEST.json` (row counts, columns, hashes) is tracked. CI gets data from private storage later.
- Each vendor table carries `MeetsMinK` (at least 5 SKUs). Viewer and anonymous roles never see vendors below the threshold.

## Consequences
- The Forecasting agent forecasts at vendor and portfolio level in the public deployment. SKU-level forecasting stays local until the licence is confirmed.
- Tests that need data skip with a clear reason when the snapshot is absent.
