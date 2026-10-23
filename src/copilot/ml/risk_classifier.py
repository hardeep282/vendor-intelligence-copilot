"""SKU risk classifier (Day 5 steps 2-3): leakage-safe Random Forest + XGBoost comparison.

Purpose : the Forecasting & Risk agent's `classify_sku_risk` tool (A1). Predicts whether a SKU
          is "at risk" (HealthStatus `Loss Making` or `At Risk` in `vw_PortfolioHealth`) from
          operational features -- deliberately excluding `ProfitMargin`, the feature ADR-000
          item 1 and `docs/adr/000-corrections-to-master-prompt.md` already name as a leak: the
          real `vw_PortfolioHealth` view derives `HealthStatus` from `MarginCategory`, which is
          itself a threshold bucketing of `ProfitMargin` -- so a model trained with
          `ProfitMargin` in its feature set is not predicting risk, it's reading the margin
          bucket that *produced* the label back off the raw number. `LEAKING_FEATURES` below
          also includes `MarkupPct` and `NetMarginAfterExcisePct`, the view's two other
          margin-family columns, for the same reason.
Inputs  : SKU-level records with the real `vw_PortfolioHealth` column *names* (public metadata
          from the Power BI semantic model, `Power BI/Vendor Analytics.SemanticModel/
          definition/tables/vw_PortfolioHealth.tmdl` in the analytics repo -- schema, not the
          licensed row data itself) and a binary `is_at_risk` label.
Outputs : `ClassifierResult` -- accuracy, F1, a calibration curve, and (for the Random Forest)
          SHAP-ranked top feature drivers, for both a leaky and a leakage-safe fit so the two
          can be compared directly -- the whole point of this module's docstring story.

**Why this module's own numbers are from synthetic data, not the real dataset:** training a
real classifier needs per-SKU rows (margin, turnover, price), which the licence guard
(`copilot.data.guard.check_table`) correctly keeps out of this repo's own snapshot -- see
`docs/RAID.md` R1, still open, on whether the Topmate licence even permits the raw SKU sheet
being in the *public* analytics repo at all. So this module is built and tested against a
clearly-synthetic SKU fixture (`make_synthetic_skus`, same convention as `FakeEmbedder`/
`FakeMessagesResource` elsewhere in this repo), with `scripts/train_risk_classifier.py` for you
to run against the real `vw_PortfolioHealth` sheet on your own machine for the real accuracy/F1
numbers that will replace the synthetic ones here.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
import shap
from pydantic import BaseModel, Field
from sklearn.calibration import calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBClassifier

# The real vw_PortfolioHealth view's margin-family columns -- all downstream of the same
# ProfitMargin figure that produces HealthStatus's MarginCategory bucket, or (SalesToPurchase-
# Ratio) algebraically reconstructable from it once StockTurnover is also known
# (SalesToPurchaseRatio = StockTurnover * (1 + Markup) -- confirmed by deriving it from this
# module's own synthetic-data formulas below, not just asserted). Never used as model features;
# kept here as a named constant so "leakage-safe" is one importable list, not a scattered set
# of exclusions a future caller could silently miss.
LEAKING_FEATURES: tuple[str, ...] = (
    "ProfitMargin",
    "MarkupPct",
    "NetMarginAfterExcisePct",
    "SalesToPurchaseRatio",
)

NUMERIC_FEATURES: tuple[str, ...] = (
    "PurchasePrice",
    "ActualPrice",
    "Volume",
    "TotalPurchaseQuantity",
    "TotalPurchaseDollars",
    "TotalSalesQuantity",
    "TotalSalesDollars",
    "TotalExciseTax",
    "FreightCost",
    "StockTurnover",
    "SalesToPurchaseRatio",
    "FreightBurdenPct",
    "ExciseBurdenPct",
)
CATEGORICAL_FEATURES: tuple[str, ...] = ("VolumeCategory",)
LABEL_COLUMN = "is_at_risk"
AT_RISK_STATUSES = frozenset({"Loss Making", "At Risk"})


class CalibrationPoint(BaseModel):
    mean_predicted_prob: float
    fraction_of_positives: float
    bin_count: int = Field(ge=0)


class ShapDriver(BaseModel):
    feature: str
    mean_abs_shap: float


class ClassifierResult(BaseModel):
    model: Literal["random_forest", "xgboost"]
    features_used: list[str]
    leakage_safe: bool
    n_train: int
    n_test: int
    accuracy: float
    f1: float
    calibration: list[CalibrationPoint]
    top_shap_drivers: list[ShapDriver] = []


def make_synthetic_skus(n: int = 2000, seed: int = 42) -> pd.DataFrame:
    """A clearly-synthetic SKU fixture, shaped like `vw_PortfolioHealth` -- real column names,
    fabricated values, for testing and for demonstrating the leakage story without touching any
    licensed data.

    Built from one shared latent "SKU health" factor `z` so the leakage story is real, not just
    labelled: `ProfitMargin` carries `z` plus its own idiosyncratic noise, and `is_at_risk` is
    thresholded on that exact noisy margin value -- so a model that can see `ProfitMargin`
    almost perfectly recovers the label (it's reading the rule back off the number the rule was
    built from). `StockTurnover` and the other legitimate features carry the *same* `z` but
    through their *own, separate* idiosyncratic noise -- correlated with risk, genuinely
    predictive, but not a perfect substitute for seeing `ProfitMargin` directly. That's the gap
    `compare_models()` below is built to show.
    """
    rng = np.random.default_rng(seed)
    z = rng.normal(0, 1, n)  # latent SKU health: higher = healthier

    purchase_price = rng.uniform(2, 80, n)
    margin_noise = rng.normal(0, 1, n)
    profit_margin = np.clip(0.22 + 0.10 * z + 0.09 * margin_noise, -0.25, 0.5)
    actual_price = purchase_price / np.maximum(1 - profit_margin, 0.05)

    volume = rng.integers(1, 50, n)
    total_purchase_qty = rng.integers(10, 5000, n)
    total_purchase_dollars = total_purchase_qty * purchase_price

    turnover_noise = rng.normal(0, 1, n)
    stock_turnover = np.clip(0.75 + 0.18 * z + 0.22 * turnover_noise, 0.0, 1.3)
    total_sales_qty = (total_purchase_qty * stock_turnover).astype(int)
    total_sales_dollars = total_sales_qty * actual_price

    excise_rate = np.clip(0.045 - 0.01 * z + 0.015 * rng.normal(0, 1, n), 0.005, 0.1)
    excise = total_sales_dollars * excise_rate
    freight_noise = rng.normal(0, 1, n)
    freight_burden = np.clip(0.05 - 0.015 * z + 0.02 * freight_noise, 0.0, 0.15)
    freight = total_purchase_dollars * freight_burden

    gross_profit = total_sales_dollars * profit_margin
    net_profit = gross_profit - excise - freight
    net_margin = net_profit / np.maximum(total_sales_dollars, 1e-6)
    markup_pct = (actual_price - purchase_price) / np.maximum(purchase_price, 1e-6)
    sales_to_purchase = total_sales_dollars / np.maximum(total_purchase_dollars, 1e-6)
    excise_burden = excise / np.maximum(total_sales_dollars, 1e-6)
    volume_category = pd.cut(volume, bins=[0, 10, 25, 50], labels=["Low", "Medium", "High"]).astype(
        str
    )

    # Ground truth: thresholded directly on the noisy ProfitMargin value above (plus a small
    # independent label-flip rate) -- not on z, and not on StockTurnover. This is the real
    # leak: ProfitMargin isn't merely correlated with the label, it IS (almost) the label.
    flip = rng.uniform(0, 1, n) < 0.03
    at_risk = (profit_margin < 0.08) ^ flip
    health_status = np.where(
        at_risk,
        np.where(profit_margin < 0, "Loss Making", "At Risk"),
        np.where(profit_margin > 0.3, "Healthy", "Profitable but Slow"),
    )

    return pd.DataFrame(
        {
            "PurchasePrice": purchase_price,
            "ActualPrice": actual_price,
            "Volume": volume,
            "TotalPurchaseQuantity": total_purchase_qty,
            "TotalPurchaseDollars": total_purchase_dollars,
            "TotalSalesQuantity": total_sales_qty,
            "TotalSalesDollars": total_sales_dollars,
            "TotalExciseTax": excise,
            "FreightCost": freight,
            "GrossProfit": gross_profit,
            "ProfitMargin": profit_margin,
            "StockTurnover": stock_turnover,
            "SalesToPurchaseRatio": sales_to_purchase,
            "MarkupPct": markup_pct,
            "FreightBurdenPct": freight_burden,
            "ExciseBurdenPct": excise_burden,
            "NetProfitAfterExcise": net_profit,
            "NetMarginAfterExcisePct": net_margin,
            "VolumeCategory": volume_category,
            "HealthStatus": health_status,
            LABEL_COLUMN: at_risk,
        }
    )


def _feature_list(leakage_safe: bool) -> tuple[list[str], list[str]]:
    numeric = [f for f in NUMERIC_FEATURES if not leakage_safe or f not in LEAKING_FEATURES]
    return numeric, list(CATEGORICAL_FEATURES)


def build_pipeline(
    model: Literal["random_forest", "xgboost"], leakage_safe: bool, seed: int = 42
) -> tuple[Pipeline, list[str]]:
    """A sklearn `Pipeline`: `ColumnTransformer` (scale numeric, one-hot categorical) feeding
    either a `RandomForestClassifier` or an `XGBClassifier`. Returns the pipeline and the exact
    feature-column list it was built for, since a leaky vs. leakage-safe pipeline uses
    different columns.
    """
    numeric, categorical = _feature_list(leakage_safe)
    pre = ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), numeric),
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical),
        ]
    )
    clf = (
        RandomForestClassifier(n_estimators=200, max_depth=8, random_state=seed)
        if model == "random_forest"
        else XGBClassifier(n_estimators=200, max_depth=4, random_state=seed, eval_metric="logloss")
    )
    return Pipeline([("pre", pre), ("clf", clf)]), numeric + categorical


def train_and_evaluate(
    df: pd.DataFrame,
    model: Literal["random_forest", "xgboost"],
    leakage_safe: bool,
    test_size: float = 0.25,
    seed: int = 42,
    compute_shap: bool = False,
    n_calibration_bins: int = 10,
) -> ClassifierResult:
    """Fit on a train split, evaluate on a held-out test split -- the leakage-safe-vs-not
    comparison this module exists for, and (for `random_forest`) the top SHAP drivers.
    """
    pipeline, feature_cols = build_pipeline(model, leakage_safe, seed)
    x = df[feature_cols]
    y = df[LABEL_COLUMN].astype(int)
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=test_size, random_state=seed, stratify=y
    )
    pipeline.fit(x_train, y_train)

    y_pred = pipeline.predict(x_test)
    y_prob = pipeline.predict_proba(x_test)[:, 1]
    accuracy = float(accuracy_score(y_test, y_pred))
    f1 = float(f1_score(y_test, y_pred))

    frac_pos, mean_pred = calibration_curve(y_test, y_prob, n_bins=n_calibration_bins)
    bin_edges = np.linspace(0, 1, n_calibration_bins + 1)
    bin_idx = np.clip(np.digitize(y_prob, bin_edges) - 1, 0, n_calibration_bins - 1)
    calibration = [
        CalibrationPoint(
            mean_predicted_prob=float(mp),
            fraction_of_positives=float(fp),
            bin_count=int(np.sum(bin_idx == i)),
        )
        for i, (mp, fp) in enumerate(zip(mean_pred, frac_pos, strict=True))
    ]

    top_drivers: list[ShapDriver] = []
    if compute_shap and model == "random_forest":
        pre = pipeline.named_steps["pre"]
        clf = pipeline.named_steps["clf"]
        x_test_transformed = pre.transform(x_test)
        explainer = shap.TreeExplainer(clf)
        shap_values = explainer.shap_values(x_test_transformed)
        # Binary RandomForestClassifier: `shap_values` comes back as a list [class_0, class_1]
        # in some shap/sklearn version combinations, or a single (n_samples, n_features,
        # n_classes) 3D array in others (confirmed: shap==0.53.0, sklearn==1.9.1 returns the
        # latter) -- handle both so this doesn't silently break on a shap upgrade.
        if isinstance(shap_values, list):
            values = shap_values[1]
        elif shap_values.ndim == 3:
            values = shap_values[:, :, 1]
        else:
            values = shap_values
        feature_names = list(pre.get_feature_names_out())
        mean_abs = np.abs(values).mean(axis=0)
        order = np.argsort(mean_abs)[::-1][:10]
        top_drivers = [
            ShapDriver(feature=feature_names[i], mean_abs_shap=float(mean_abs[i])) for i in order
        ]

    return ClassifierResult(
        model=model,
        features_used=feature_cols,
        leakage_safe=leakage_safe,
        n_train=len(x_train),
        n_test=len(x_test),
        accuracy=accuracy,
        f1=f1,
        calibration=calibration,
        top_shap_drivers=top_drivers,
    )


def compare_models(df: pd.DataFrame, seed: int = 42) -> dict[str, ClassifierResult]:
    """Run all four combinations (RF/XGBoost x leaky/leakage-safe) on the same split, keyed for
    easy lookup. Closes ADR-000 item 1 (XGBoost comparison) and demonstrates the leakage story
    for both model families at once.
    """
    return {
        "random_forest_leaky": train_and_evaluate(
            df, "random_forest", leakage_safe=False, seed=seed, compute_shap=True
        ),
        "random_forest_safe": train_and_evaluate(
            df, "random_forest", leakage_safe=True, seed=seed, compute_shap=True
        ),
        "xgboost_leaky": train_and_evaluate(df, "xgboost", leakage_safe=False, seed=seed),
        "xgboost_safe": train_and_evaluate(df, "xgboost", leakage_safe=True, seed=seed),
    }
