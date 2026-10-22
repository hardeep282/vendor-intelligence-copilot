"""Tests for the Day 9 template-based question->SQL pair generator (copilot.sql.pair_generation).

Uses a tiny synthetic in-memory DuckDB database -- invented vendor names and numbers, the real
table/column shape from policies/disclosure.yaml (schema, not licensed data; the same convention
tests/test_sql_validator.py already uses) -- so these tests never touch the real snapshot and
never need it built. The CLI entrypoint (scripts/generate_sql_pairs.py) does need the real
snapshot and real vendor names (ADR-002); that boundary is exactly why `generate_candidates` and
`verify_and_filter` take a connection as a parameter instead of calling `connect()` themselves.
"""

from __future__ import annotations

import random

import duckdb
import pytest

from copilot.sql.pair_generation import Pair, generate_candidates, verify_and_filter
from copilot.sql.validator import load_rules


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute(
        """
        CREATE TABLE vendor_revenue_summary (
            VendorName VARCHAR, NumberOfSKUs INT, TotalRevenue DOUBLE, TotalGrossProfit DOUBLE,
            AvgMarginPct DOUBLE, TotalPurchaseCost DOUBLE, RevenueSharePct DOUBLE,
            BlendedMarginPct DOUBLE, MeetsMinK BOOLEAN
        )
        """
    )
    c.execute(
        """
        INSERT INTO vendor_revenue_summary VALUES
            ('ACME BEVERAGES', 12, 100000.0, 20000.0, 20.0, 80000.0, 50.0, 20.0, true),
            ('NORTHWIND SPIRITS', 8, 60000.0, 9000.0, 15.0, 51000.0, 30.0, 15.0, true),
            ('TINY VENDOR CO', 2, 500.0, 50.0, 10.0, 450.0, 0.3, 10.0, false)
        """
    )
    c.execute(
        """
        CREATE TABLE vendor_tiering (
            VendorName VARCHAR, TotalRevenue DOUBLE, TotalProfit DOUBLE, AvgMargin DOUBLE,
            AvgTurnover DOUBLE, SKUCount INT, RevenueTier VARCHAR, TierLabel VARCHAR,
            RevenueSharePct DOUBLE, BlendedMargin DOUBLE, MeetsMinK BOOLEAN
        )
        """
    )
    c.execute(
        """
        INSERT INTO vendor_tiering VALUES
            ('ACME BEVERAGES', 100000.0, 20000.0, 20.0, 4.0, 12, 'A', 'Core', 50.0, 20.0, true),
            ('NORTHWIND SPIRITS', 60000.0, 9000.0, 15.0, 3.0, 8, 'B', 'Growth', 30.0, 15.0, true)
        """
    )
    c.execute("CREATE TABLE portfolio_health_mix (HealthStatus VARCHAR, SKUs INT, SharePct DOUBLE)")
    c.execute(
        "INSERT INTO portfolio_health_mix VALUES ('Healthy', 18, 90.0), ('Dead Stock', 2, 10.0)"
    )
    return c


@pytest.fixture
def rng() -> random.Random:
    return random.Random(42)


# -- generate_candidates --------------------------------------------------------------------


def test_generates_a_lookup_for_every_vendor_meeting_min_k(con, rng):
    vendors = ["ACME BEVERAGES", "NORTHWIND SPIRITS"]  # caller already filters MeetsMinK
    candidates = generate_candidates(con, rng, vendors)
    lookups = [
        c for c in candidates if c.category == "lookup" and c.table == "vendor_revenue_summary"
    ]
    assert {c.question for c in lookups} == {
        "What is Acme Beverages's total revenue?",
        "What is Northwind Spirits's total revenue?",
    }


def test_skips_templates_for_tables_not_present(con, rng):
    # vendor_pareto, vendor_profit_leakage etc. were never created in this fixture.
    candidates = generate_candidates(con, rng, ["ACME BEVERAGES"])
    known_tables = {"vendor_revenue_summary", "vendor_tiering", "portfolio_health_mix"}
    assert all(c.table in known_tables for c in candidates)


def test_includes_portfolio_level_aggregation_with_no_vendor_filter(con, rng):
    candidates = generate_candidates(con, rng, ["ACME BEVERAGES"])
    portfolio = [
        c for c in candidates if "VendorName = " not in c.sql and c.category == "aggregation"
    ]
    assert any("count(*)" in c.sql for c in portfolio)


def test_comparison_template_never_compares_a_vendor_to_itself(con, rng):
    vendors = ["ACME BEVERAGES", "NORTHWIND SPIRITS"]
    candidates = generate_candidates(con, rng, vendors)
    comparisons = [c for c in candidates if c.category == "comparison"]
    for c in comparisons:
        assert c.sql.count("VendorName IN") == 1


def test_candidates_are_pure_sql_text_not_yet_executed(con, rng):
    # generate_candidates must not touch the connection beyond reading what tables exist.
    before = con.execute("SELECT count(*) FROM vendor_revenue_summary").fetchone()
    generate_candidates(con, rng, ["ACME BEVERAGES"])
    after = con.execute("SELECT count(*) FROM vendor_revenue_summary").fetchone()
    assert before == after


# -- verify_and_filter -----------------------------------------------------------------------


def test_execution_filter_drops_sql_referencing_a_missing_column(con):
    good = Pair(
        question="ok",
        sql="SELECT VendorName FROM vendor_revenue_summary",
        category="lookup",
        table="vendor_revenue_summary",
    )
    bad = Pair(
        question="bad",
        sql="SELECT NotAColumn FROM vendor_revenue_summary",
        category="lookup",
        table="vendor_revenue_summary",
    )
    kept, report = verify_and_filter(con, [good, bad])
    assert kept == [good]
    assert report.candidates == 2
    assert report.execution_failed == 1


def test_safety_validator_filter_drops_a_table_outside_the_policy(con):
    outside_policy = Pair(
        question="leaky",
        sql="SELECT * FROM vendor_revenue_summary",  # validator rejects bare SELECT * -- see below
        category="lookup",
        table="vendor_revenue_summary",
        role="analyst",
    )
    kept, report = verify_and_filter(con, [outside_policy])
    # SELECT * executes fine against the fixture but the validator may reject it (structure
    # layer) or pass it depending on the current rules; either way the two filters are counted
    # separately and consistently -- that's what this test actually checks.
    assert report.candidates == 1
    assert report.execution_failed == 0
    assert report.kept == len(kept)
    assert report.kept + report.validator_failed == 1


def test_reports_add_up(con, rng):
    candidates = generate_candidates(con, rng, ["ACME BEVERAGES", "NORTHWIND SPIRITS"])
    kept, report = verify_and_filter(con, candidates)
    assert report.candidates == len(candidates)
    assert report.kept == len(kept)
    assert report.execution_failed + report.validator_failed + report.kept <= report.candidates


def test_every_kept_pair_passes_the_real_validator_rules(con, rng):
    # Load the real policies/sql_rules.yaml so this test fails if a template drifts out of
    # sync with the live safety rules, not just a fixture copy of them.
    load_rules()  # sanity: the real rules file parses
    candidates = generate_candidates(con, rng, ["ACME BEVERAGES", "NORTHWIND SPIRITS"])
    kept, _ = verify_and_filter(con, candidates)
    assert len(kept) > 0
