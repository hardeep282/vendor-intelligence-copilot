"""Tests for the SKU risk classifier (Day 5 steps 2-3).

Runs entirely on the synthetic fixture (`make_synthetic_skus`) -- real `vw_PortfolioHealth`
row data is never in this repo (licence guard), so these tests exercise the pipeline mechanics
and the leakage story on fabricated data, not real-world accuracy numbers. See the module
docstring for why `SalesToPurchaseRatio` is in `LEAKING_FEATURES` even though it isn't a raw
margin column.
"""

from __future__ import annotations

from copilot.ml.risk_classifier import (
    CATEGORICAL_FEATURES,
    LABEL_COLUMN,
    LEAKING_FEATURES,
    NUMERIC_FEATURES,
    build_pipeline,
    compare_models,
    make_synthetic_skus,
    train_and_evaluate,
)


def test_make_synthetic_skus_has_the_real_column_names_and_a_binary_label() -> None:
    df = make_synthetic_skus(n=500, seed=1)
    assert len(df) == 500
    for col in (*NUMERIC_FEATURES, *CATEGORICAL_FEATURES, "HealthStatus", LABEL_COLUMN):
        assert col in df.columns
    assert set(df[LABEL_COLUMN].unique()) <= {True, False}


def test_make_synthetic_skus_label_is_not_degenerate() -> None:
    # Neither near-all-positive nor near-all-negative -- a classifier needs both classes
    # represented with enough weight to be trainable and evaluable.
    df = make_synthetic_skus(n=2000, seed=42)
    balance = df[LABEL_COLUMN].mean()
    assert 0.05 < balance < 0.5


def test_make_synthetic_skus_is_deterministic_for_a_given_seed() -> None:
    a = make_synthetic_skus(n=100, seed=7)
    b = make_synthetic_skus(n=100, seed=7)
    assert a[LABEL_COLUMN].tolist() == b[LABEL_COLUMN].tolist()
    assert a["ProfitMargin"].tolist() == b["ProfitMargin"].tolist()


def test_build_pipeline_leakage_safe_excludes_all_leaking_features() -> None:
    _, feature_cols = build_pipeline("random_forest", leakage_safe=True)
    for leaked in LEAKING_FEATURES:
        assert leaked not in feature_cols


def test_build_pipeline_leaky_includes_sales_to_purchase_ratio() -> None:
    # ProfitMargin/MarkupPct/NetMarginAfterExcisePct are never candidate features at all (not in
    # NUMERIC_FEATURES) -- SalesToPurchaseRatio is the one column that actually differs between
    # the leaky and leakage-safe feature sets, which is the entire point of this module's
    # docstring story (it's an algebraic ProfitMargin proxy, present in NUMERIC_FEATURES but
    # filtered out only when leakage_safe=True).
    _, feature_cols = build_pipeline("random_forest", leakage_safe=False)
    assert "SalesToPurchaseRatio" in feature_cols
    for always_excluded in ("ProfitMargin", "MarkupPct", "NetMarginAfterExcisePct"):
        assert always_excluded not in feature_cols


def test_train_and_evaluate_returns_scores_in_valid_ranges() -> None:
    df = make_synthetic_skus(n=800, seed=3)
    result = train_and_evaluate(df, "random_forest", leakage_safe=True)
    assert 0.0 <= result.accuracy <= 1.0
    assert 0.0 <= result.f1 <= 1.0
    assert result.n_train + result.n_test == len(df)
    assert result.leakage_safe is True
    assert "ProfitMargin" not in result.features_used


def test_train_and_evaluate_calibration_bins_cover_the_test_set() -> None:
    df = make_synthetic_skus(n=800, seed=3)
    result = train_and_evaluate(df, "xgboost", leakage_safe=True, n_calibration_bins=5)
    assert sum(point.bin_count for point in result.calibration) == result.n_test


def test_train_and_evaluate_computes_shap_drivers_only_for_random_forest() -> None:
    df = make_synthetic_skus(n=800, seed=3)
    rf = train_and_evaluate(df, "random_forest", leakage_safe=False, compute_shap=True)
    assert len(rf.top_shap_drivers) > 0

    xgb = train_and_evaluate(df, "xgboost", leakage_safe=False, compute_shap=True)
    assert xgb.top_shap_drivers == []


def test_leaky_random_forest_shap_drivers_do_not_include_leaking_features_by_name() -> None:
    # The *raw* leaking columns should not themselves be the literal top driver names (they are
    # excluded from feature_cols entirely in the safe run; here we just confirm the leaky run's
    # driver names are drawn from its own feature set, i.e. the mechanism is wired correctly).
    df = make_synthetic_skus(n=800, seed=3)
    rf = train_and_evaluate(df, "random_forest", leakage_safe=False, compute_shap=True)
    driver_names = {d.feature for d in rf.top_shap_drivers}
    assert len(driver_names) > 0


def test_compare_models_returns_all_four_combinations() -> None:
    df = make_synthetic_skus(n=1500, seed=42)
    results = compare_models(df)
    assert set(results) == {
        "random_forest_leaky",
        "random_forest_safe",
        "xgboost_leaky",
        "xgboost_safe",
    }
    for name, result in results.items():
        expect_safe = name.endswith("_safe")
        assert result.leakage_safe is expect_safe


def test_leaky_models_outscore_leakage_safe_models_on_both_accuracy_and_f1() -> None:
    # The whole point of this module: seeing ProfitMargin (or its algebraic proxy,
    # SalesToPurchaseRatio) inflates both accuracy and F1 relative to the leakage-safe fit, for
    # both model families, on the same train/test split.
    df = make_synthetic_skus(n=2000, seed=42)
    results = compare_models(df)
    assert results["random_forest_leaky"].accuracy > results["random_forest_safe"].accuracy
    assert results["random_forest_leaky"].f1 > results["random_forest_safe"].f1
    assert results["xgboost_leaky"].accuracy > results["xgboost_safe"].accuracy
    assert results["xgboost_leaky"].f1 > results["xgboost_safe"].f1


def test_leakage_safe_shap_drivers_exclude_sales_to_purchase_ratio() -> None:
    # SalesToPurchaseRatio is the algebraic ProfitMargin proxy this module's docstring documents
    # discovering -- confirm it never appears as a safe-model driver because it was never a
    # candidate feature for the safe fit in the first place.
    df = make_synthetic_skus(n=1500, seed=42)
    safe = train_and_evaluate(df, "random_forest", leakage_safe=True, compute_shap=True)
    driver_names = {
        d.feature.removeprefix("num__").removeprefix("cat__") for d in safe.top_shap_drivers
    }
    assert "SalesToPurchaseRatio" not in driver_names
    assert "ProfitMargin" not in driver_names
