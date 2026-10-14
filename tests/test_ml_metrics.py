"""Tests for WAPE/MASE/bias (Day 5 step 1). Pure arithmetic -- no fakes, no network needed."""

from __future__ import annotations

import pytest

from copilot.ml.metrics import bias, mase, wape


def test_wape_zero_for_a_perfect_forecast() -> None:
    assert wape([10, 20, 30], [10, 20, 30]) == 0.0


def test_wape_is_the_ratio_of_absolute_errors_to_absolute_actuals() -> None:
    # |10-12| + |20-18| = 4, sum(actual) = 30 -> 4/30
    assert wape([10, 20], [12, 18]) == pytest.approx(4 / 30)


def test_wape_raises_on_length_mismatch() -> None:
    with pytest.raises(ValueError, match="same length"):
        wape([1, 2, 3], [1, 2])


def test_wape_raises_when_every_actual_is_zero() -> None:
    with pytest.raises(ValueError, match="undefined"):
        wape([0, 0], [1, 1])


def test_mase_is_one_when_forecast_matches_naive_in_sample_scale() -> None:
    # train diffs are all 1 (scale=1); forecast error also averages 1 -> MASE == 1
    assert mase([10], [11], train=[1, 2, 3, 4]) == pytest.approx(1.0)


def test_mase_below_one_means_better_than_naive() -> None:
    assert mase([10], [10], train=[1, 2, 3, 4]) == pytest.approx(0.0)


def test_mase_raises_with_fewer_than_two_training_points() -> None:
    with pytest.raises(ValueError, match="at least 2 points"):
        mase([10], [11], train=[5])


def test_mase_raises_on_constant_training_series() -> None:
    with pytest.raises(ValueError, match="constant"):
        mase([10], [11], train=[5, 5, 5])


def test_bias_positive_means_over_forecasting() -> None:
    assert bias([10, 10], [12, 14]) == pytest.approx(3.0)


def test_bias_negative_means_under_forecasting() -> None:
    assert bias([10, 10], [8, 9]) == pytest.approx(-1.5)


def test_bias_zero_for_a_perfect_forecast() -> None:
    assert bias([5, 5, 5], [5, 5, 5]) == 0.0
