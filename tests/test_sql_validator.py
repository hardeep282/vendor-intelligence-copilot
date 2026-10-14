"""Tests for the layered SQL validator (Day 3 step 5).

Each test name states the exact trap from docs/specs/text_to_sql_safety.md it covers, so a
failure points straight back at the spec row that broke.
"""

from __future__ import annotations

import pytest

from copilot.guardrails.policy import load_policy
from copilot.sql.validator import load_rules, validate


@pytest.fixture
def policy():
    return load_policy()


@pytest.fixture
def rules():
    return load_rules()


# -- Layer 1: structure --------------------------------------------------------------------


def test_allows_plain_select_on_a_catalogued_table(policy, rules):
    result = validate(
        "SELECT VendorName, TotalRevenue FROM vendor_revenue_summary", "viewer", policy, rules
    )
    assert result.ok
    assert "LIMIT 200" in result.sql
    assert result.truncated


def test_blocks_table_not_in_disclosure_policy(policy, rules):
    result = validate("SELECT * FROM system_users", "analyst", policy, rules)
    assert not result.ok
    assert result.violations[0].code == "sql_table_not_allowed"


def test_blocks_table_outside_role(policy, rules):
    # vendor_revenue_summary is internal; anonymous may only read public tables.
    result = validate("SELECT * FROM vendor_revenue_summary", "anonymous", policy, rules)
    assert not result.ok
    assert result.violations[0].code == "sql_table_not_allowed"


def test_blocks_union_select_injection(policy, rules):
    sql = "SELECT VendorName FROM vendor_revenue_summary UNION SELECT username FROM system_users"
    result = validate(sql, "analyst", policy, rules)
    assert not result.ok
    assert result.violations[0].code == "sql_table_not_allowed"


def test_allows_cte_self_reference(policy, rules):
    sql = "WITH ranked AS (SELECT * FROM vendor_revenue_summary) SELECT * FROM ranked"
    result = validate(sql, "analyst", policy, rules)
    assert result.ok


def test_blocks_file_reading_table_function(policy, rules):
    result = validate("SELECT * FROM read_csv('.env')", "analyst", policy, rules)
    assert not result.ok
    assert result.violations[0].code == "sql_function_not_allowed"


def test_blocks_duckdb_catalog_function(policy, rules):
    result = validate("SELECT * FROM duckdb_tables()", "analyst", policy, rules)
    assert not result.ok
    assert result.violations[0].code == "sql_function_not_allowed"


def test_blocks_information_schema_enumeration(policy, rules):
    result = validate("SELECT * FROM information_schema.tables", "analyst", policy, rules)
    assert not result.ok
    assert result.violations[0].code == "sql_catalog_access"


def test_blocks_stacked_statement(policy, rules):
    sql = "SELECT * FROM vendor_revenue_summary; DROP TABLE vendor_revenue_summary"
    result = validate(sql, "analyst", policy, rules)
    assert not result.ok
    assert result.violations[0].code == "sql_multi_statement"


def test_blocks_pragma(policy, rules):
    result = validate("PRAGMA database_list", "analyst", policy, rules)
    assert not result.ok
    assert result.violations[0].code == "sql_statement_not_allowed"


def test_blocks_attach(policy, rules):
    result = validate("ATTACH 'evil.db' AS evil", "analyst", policy, rules)
    assert not result.ok
    assert result.violations[0].code == "sql_statement_not_allowed"


def test_blocks_set_configuration(policy, rules):
    result = validate("SET enable_external_access = true", "analyst", policy, rules)
    assert not result.ok
    assert result.violations[0].code == "sql_statement_not_allowed"


def test_blocks_copy_to_file(policy, rules):
    result = validate("COPY vendor_revenue_summary TO 'out.csv'", "analyst", policy, rules)
    assert not result.ok
    assert result.violations[0].code == "sql_statement_not_allowed"


def test_limit_is_capped_not_just_added(policy, rules):
    result = validate("SELECT * FROM vendor_revenue_summary LIMIT 5000", "analyst", policy, rules)
    assert result.ok
    assert "LIMIT 200" in result.sql
    assert result.truncated


def test_limit_under_cap_is_left_alone(policy, rules):
    result = validate("SELECT * FROM vendor_revenue_summary LIMIT 10", "analyst", policy, rules)
    assert result.ok
    assert "LIMIT 10" in result.sql
    assert not result.truncated


# -- Layer 2: semantic traps ---------------------------------------------------------------


def test_blocks_avg_of_blended_margin_as_portfolio_figure(policy, rules):
    result = validate("SELECT AVG(BlendedMargin) FROM vendor_tiering", "analyst", policy, rules)
    assert not result.ok
    assert result.violations[0].code == "sql_ratio_misuse"


def test_allows_ratio_of_sums_for_portfolio_margin(policy, rules):
    sql = "SELECT SUM(GrossProfit) / SUM(TotalRevenue) FROM vendor_profit_leakage"
    result = validate(sql, "analyst", policy, rules)
    assert result.ok


def test_blocks_sum_after_fanout_join(policy, rules):
    sql = (
        "SELECT SUM(a.TotalFreight) FROM vendor_profit_leakage a "
        "JOIN vendor_monthly_demand b ON a.VendorName = b.VendorName"
    )
    result = validate(sql, "analyst", policy, rules)
    assert not result.ok
    assert result.violations[0].code == "sql_fanout_sum"


def test_allows_sum_of_per_vendor_total_without_fanout_join(policy, rules):
    result = validate(
        "SELECT SUM(TotalFreight) FROM vendor_profit_leakage", "analyst", policy, rules
    )
    assert result.ok


def test_blocks_adding_overlapping_sku_counts(policy, rules):
    sql = "SELECT SUM(LossMakingSKUs + DeadStockSKUs) FROM vendor_health_mix"
    result = validate(sql, "analyst", policy, rules)
    assert not result.ok
    assert result.violations[0].code == "sql_non_additive_sum"


def test_allows_overlapping_counts_reported_separately(policy, rules):
    sql = "SELECT SUM(LossMakingSKUs), SUM(DeadStockSKUs) FROM vendor_health_mix"
    result = validate(sql, "analyst", policy, rules)
    assert result.ok


# -- Error handling --------------------------------------------------------------------------


def test_unparseable_sql_is_rejected_not_raised(policy, rules):
    result = validate("SELEKT * FROM nowhere !!!", "analyst", policy, rules)
    assert not result.ok
    assert result.violations[0].code == "sql_parse_error"


def test_non_select_root_is_rejected(policy, rules):
    result = validate("INSERT INTO vendor_revenue_summary VALUES (1)", "analyst", policy, rules)
    assert not result.ok
    assert result.violations[0].code in {"sql_root_not_select", "sql_statement_not_allowed"}
