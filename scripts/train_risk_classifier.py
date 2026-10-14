"""Train/compare the SKU risk classifier against the REAL vw_PortfolioHealth sheet.

Purpose : `copilot.ml.risk_classifier` is built and tested entirely on synthetic data (the
          licence guard keeps real per-SKU rows out of this repo's own snapshot -- see the
          module's docstring and docs/RAID.md R1). This script is for you to run on your own
          machine, against your own export of the real `vw_PortfolioHealth` view, to get the
          real accuracy/F1 numbers that should replace the synthetic ones quoted in
          docs/BUILD_LOG.md and docs/PROJECT_PROGRESS.md once you have them. Nothing this script
          reads or prints is committed back to this repo.
Usage   : uv run python scripts/train_risk_classifier.py path/to/vw_PortfolioHealth.csv
          uv run python scripts/train_risk_classifier.py path/to/export.xlsx \\
              --sheet "vw_PortfolioHealth"
Input file: must have the same column names `copilot.ml.risk_classifier` expects --
          NUMERIC_FEATURES + CATEGORICAL_FEATURES + a `HealthStatus` column holding the view's
          text categories ("Loss Making", "At Risk", "Profitable but Slow", "Healthy", ...).
          `is_at_risk` is derived here from `HealthStatus`, not expected as an input column.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from copilot.ml.risk_classifier import (
    AT_RISK_STATUSES,
    CATEGORICAL_FEATURES,
    LABEL_COLUMN,
    NUMERIC_FEATURES,
    compare_models,
)
from copilot.ml.run_log import log_classifier_run


def _load(path: Path, sheet: str | None) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path, sheet_name=sheet or 0)
    return pd.read_csv(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_file", type=Path)
    parser.add_argument("--sheet", default=None, help="Excel sheet name, if data_file is .xlsx")
    parser.add_argument(
        "--run-log",
        type=Path,
        default=Path("run_log.csv"),
        help="CSV path to append results to (default: ./run_log.csv, gitignored).",
    )
    args = parser.parse_args()

    if not args.data_file.exists():
        print(f"error: {args.data_file} not found", file=sys.stderr)
        return 1

    df = _load(args.data_file, args.sheet)

    expected_cols = (*NUMERIC_FEATURES, *CATEGORICAL_FEATURES, "HealthStatus")
    missing = [c for c in expected_cols if c not in df.columns]
    if missing:
        print(f"error: input file is missing expected columns: {missing}", file=sys.stderr)
        return 1

    df[LABEL_COLUMN] = df["HealthStatus"].isin(AT_RISK_STATUSES)
    balance = df[LABEL_COLUMN].mean()
    print(f"Loaded {len(df)} rows from {args.data_file}; label balance = {balance:.3f}")
    if not 0 < balance < 1:
        print(
            "error: label column is degenerate (all one class) -- check HealthStatus values",
            file=sys.stderr,
        )
        return 1

    results = compare_models(df)

    print()
    print(f"{'combo':25s} {'accuracy':>9s} {'f1':>7s} {'n_test':>7s} {'features':>9s}")
    for name, result in results.items():
        print(
            f"{name:25s} {result.accuracy:>9.3f} {result.f1:>7.3f} "
            f"{result.n_test:>7d} {len(result.features_used):>9d}"
        )
        log_classifier_run(result, args.run_log)

    print()
    rf_leaky, rf_safe = results["random_forest_leaky"], results["random_forest_safe"]
    print(
        f"Leakage effect (random forest): "
        f"accuracy {rf_leaky.accuracy:.3f} -> {rf_safe.accuracy:.3f}, "
        f"f1 {rf_leaky.f1:.3f} -> {rf_safe.f1:.3f} (leaky -> leakage-safe)"
    )
    if rf_leaky.top_shap_drivers:
        print("\nTop SHAP drivers, leaky random forest:")
        for d in rf_leaky.top_shap_drivers[:5]:
            print(f"  {d.feature:30s} {d.mean_abs_shap:.4f}")
    if rf_safe.top_shap_drivers:
        print("\nTop SHAP drivers, leakage-safe random forest:")
        for d in rf_safe.top_shap_drivers[:5]:
            print(f"  {d.feature:30s} {d.mean_abs_shap:.4f}")

    print(f"\nRun log appended to {args.run_log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
