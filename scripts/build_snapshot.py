"""Build the licence-safe Gold snapshot (Parquet) from the analytics workbook.

Purpose : turn the vendor project's Excel workbook into aggregate-only Parquet tables that are
          allowed to be queried by the app. SKU-level sheets are only ever aggregated, never copied.
Inputs  : path to Vendor_Summary.xlsx (local only, never committed).
Outputs : data/snapshot/<table>.parquet and data/snapshot/MANIFEST.json (row counts, sha256).
Run     : uv run python scripts/build_snapshot.py "path/to/Vendor_Summary.xlsx"
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

from copilot.data.guard import check_table
from copilot.settings import get_settings

# Vendor-level views: already one row per vendor (126 rows), safe to copy as they are.
VENDOR_VIEWS = {
    "vendor_revenue_summary": "vw_VendorRevenueSummary",
    "vendor_tiering": "vw_VendorTiering",
    "vendor_pareto": "vw_ParetoAnalysis",
    "vendor_profit_leakage": "vw_ProfitLeakage",
    "vendor_rankings": "vw_VendorRankings",
    "vendor_logistics_cost": "vw_LogisticsCostSummary",
    "vendor_full_cost": "vw_FullCostAnalysis",
}


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    """Drop the empty 'Unnamed' columns that Excel exports leave behind."""
    return df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")].copy()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(workbook: Path, out_dir: Path, k: int) -> dict[str, object]:
    out_dir.mkdir(parents=True, exist_ok=True)
    xls = pd.ExcelFile(workbook)
    sheets = {str(s).strip(): s for s in xls.sheet_names}  # one sheet name has a trailing space
    tables: dict[str, pd.DataFrame] = {}

    for table, sheet in VENDOR_VIEWS.items():
        df = _clean(xls.parse(sheets[sheet]))
        sku_col = next(
            (c for c in ("SKUCount", "NumberOfSKUs", "TotalSKUs") if c in df.columns), None
        )
        if sku_col:
            df["MeetsMinK"] = df[sku_col] >= k  # suppress thin vendors for non-analyst roles
        tables[table] = df

    # SKU-level demand -> vendor x month and portfolio x month aggregates only.
    demand = xls.parse(sheets["output_monthly_demand"])
    demand["SkuKey"] = demand["Brand"].astype(str) + "|" + demand["Description"].astype(str)
    demand["SkuKey"] += "|" + demand["Size"].astype(str)
    g = demand.groupby(["VendorName", "SalesYear", "SalesMonth"], as_index=False)
    vendor_month = g.agg(
        MonthlyDemand=("MonthlyDemand", "sum"),
        MonthlyRevenue=("MonthlyRevenue", "sum"),
        ActiveSKUs=("SkuKey", "nunique"),
    )
    vendor_month["MeetsMinK"] = vendor_month["ActiveSKUs"] >= k
    tables["vendor_monthly_demand"] = vendor_month
    g2 = demand.groupby(["SalesYear", "SalesMonth"], as_index=False)
    tables["portfolio_monthly_demand"] = g2.agg(
        MonthlyDemand=("MonthlyDemand", "sum"),
        MonthlyRevenue=("MonthlyRevenue", "sum"),
        ActiveSKUs=("SkuKey", "nunique"),
    )

    # SKU health -> counts per vendor and for the portfolio. No SKU names or prices survive.
    health = xls.parse(sheets["vw_PortfolioHealth"])
    vh = health.groupby(["VendorName", "HealthStatus"], as_index=False).agg(
        SKUs=("HealthStatus", "size")
    )
    tables["vendor_health_mix"] = vh
    ph = health.groupby("HealthStatus", as_index=False).agg(SKUs=("HealthStatus", "size"))
    ph["SharePct"] = (100 * ph["SKUs"] / ph["SKUs"].sum()).round(2)
    tables["portfolio_health_mix"] = ph

    manifest: dict[str, object] = {"min_k": k, "tables": {}}
    for name, df in tables.items():
        check_table(name, df.columns, len(df))  # raises LicenceViolation on SKU-level data
        path = out_dir / f"{name}.parquet"
        df.to_parquet(path, index=False)
        manifest["tables"][name] = {  # type: ignore[index]
            "rows": len(df),
            "columns": list(df.columns),
            "sha256": _sha256(path),
        }
    (out_dir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: build_snapshot.py <path to Vendor_Summary.xlsx>")
    s = get_settings()
    m = build(Path(sys.argv[1]), s.snapshot_dir, s.min_aggregation_k)
    for name, info in m["tables"].items():  # type: ignore[attr-defined]
        print(f"{name:28s} {info['rows']:>6} rows")


if __name__ == "__main__":
    main()
