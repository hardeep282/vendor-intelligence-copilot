"""copilot.data.units: units travel with the numbers (30 Oct 2026).

The first real UI run showed the drafter guessing "$" for a forecast in units and calling a
percent of vendor revenue "% of controllable margin". These tests pin the labels and the
conservative rules for when NOT to label.
"""

from __future__ import annotations

from copilot.data.units import COLUMN_UNITS, describe_units


def test_the_exact_query_from_the_first_ui_run_gets_both_units() -> None:
    sql = (
        "SELECT VendorName, ROUND(ControllableLeakage, 2) AS controllable_leakage, "
        "ROUND(ControllableLeakagePct, 2) AS controllable_leakage_pct FROM vendor_profit_leakage "
        "ORDER BY ControllableLeakage DESC LIMIT 200"
    )
    lines = describe_units(sql)
    assert "controllable_leakage (ControllableLeakage): US dollars" in lines
    assert (
        "controllable_leakage_pct (ControllableLeakagePct): percent of that vendor's total revenue"
        in lines
    )
    assert not any(line.startswith("VendorName") for line in lines)


def test_monthly_demand_is_labelled_as_units_not_dollars() -> None:
    lines = describe_units("SELECT SUM(MonthlyDemand) AS demand FROM portfolio_monthly_demand")
    assert lines == ["demand (MonthlyDemand): " + COLUMN_UNITS["MonthlyDemand"]]
    assert "not dollars" in lines[0]


def test_counts_ratios_and_unknown_columns_get_no_label() -> None:
    sql = (
        "SELECT COUNT(TotalSKUs) AS n, SUM(TotalGrossProfit) / SUM(TotalRevenue) * 100 AS margin, "
        "RevenueRank FROM vendor_pareto"
    )
    assert describe_units(sql) == []


def test_unparseable_sql_returns_no_labels() -> None:
    assert describe_units("this is not sql at all (") == []
