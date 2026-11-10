"""Reconciliation tests: do the snapshot's tables agree with each other? (10 Nov 2026)

The snapshot comes from two source sheets: seven one-row-per-vendor tables from the analytics
project's Gold views, and the monthly demand tables straight from `output_monthly_demand`. The
vendor tables must agree with each other exactly. The monthly table is known not to line up with
them exactly (RAID R6 and R14), and those known differences are pinned here so that any change
fails a test and gets written down, instead of drifting silently.

Every number below is documented in knowledge/data_dictionary.md (v3) and knowledge/methodology.md
(v4). If a rebuilt snapshot legitimately changes one (for example once vendor spellings are merged
in build_snapshot.py), update those documents, RAID R6/R14 and the pinned value together.

Needs the local snapshot (`scripts/build_snapshot.py`), so it is skipped where there is none, such
as in CI.
"""

from __future__ import annotations

from typing import Any

import duckdb
import pytest

from copilot.data import store
from copilot.settings import get_settings

pytestmark = pytest.mark.skipif(
    not any(get_settings().snapshot_dir.glob("*.parquet")),
    reason="needs the local snapshot (scripts/build_snapshot.py)",
)

REFERENCE = "vendor_revenue_summary"
OTHER_VENDOR_TABLES = (
    "vendor_tiering",
    "vendor_pareto",
    "vendor_profit_leakage",
    "vendor_rankings",
    "vendor_logistics_cost",
    "vendor_full_cost",
)
BLENDED_MARGIN_TABLES = ("vendor_tiering", "vendor_pareto", "vendor_rankings")

# Known differences with the monthly table (RAID R14), measured 10 Nov 2026.
NAMES_ONLY_IN_MONTHLY = {
    "BERNIKO LLC",
    "EXCLUSIVE WINES & SPIRITS",
    "SOUTHERN GLAZERS W&S OF NE",
    "VINEYARD BRANDS LLC",
    "WHYTE & MACKAY",
}
NAMES_ONLY_IN_VENDOR_TABLES = {"AAPER ALCOHOL & CHEMICAL CO", "LAUREATE IMPORTS CO"}


@pytest.fixture(scope="module")
def con() -> duckdb.DuckDBPyConnection:
    return store.connect()


def _one(con: duckdb.DuckDBPyConnection, sql: str) -> Any:
    row = con.execute(sql).fetchone()
    assert row is not None
    return row[0]


def _names(con: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    return {r[0] for r in con.execute(f"SELECT DISTINCT VendorName FROM {table}").fetchall()}  # noqa: S608


# --- The seven vendor tables agree with each other exactly -------------------------------------


@pytest.mark.parametrize("table", OTHER_VENDOR_TABLES)
def test_vendor_tables_have_the_same_vendors(con, table: str) -> None:
    assert _names(con, table) == _names(con, REFERENCE)
    assert _one(con, f"SELECT count(*) FROM {table}") == 126  # noqa: S608  (one row per vendor)


@pytest.mark.parametrize("table", OTHER_VENDOR_TABLES)
def test_vendor_tables_agree_on_revenue_and_k_flag(con, table: str) -> None:
    disagreements = _one(
        con,
        f"SELECT count(*) FROM {table} t JOIN {REFERENCE} r USING (VendorName) "  # noqa: S608
        "WHERE abs(t.TotalRevenue - r.TotalRevenue) > 0.005 OR t.MeetsMinK <> r.MeetsMinK",
    )
    assert disagreements == 0


@pytest.mark.parametrize("table", BLENDED_MARGIN_TABLES)
def test_blended_margin_is_the_same_figure_under_two_names(con, table: str) -> None:
    """`BlendedMargin` here equals `BlendedMarginPct` in vendor_revenue_summary, 0-100 scale."""
    disagreements = _one(
        con,
        f"SELECT count(*) FROM {table} t JOIN {REFERENCE} r USING (VendorName) "  # noqa: S608
        "WHERE abs(t.BlendedMargin - r.BlendedMarginPct) > 0.005",
    )
    assert disagreements == 0


def test_vendor_k_flag_is_decided_per_vendor(con) -> None:
    k = get_settings().min_aggregation_k
    wrong = _one(con, f"SELECT count(*) FROM {REFERENCE} WHERE MeetsMinK <> (NumberOfSKUs >= {k})")  # noqa: S608
    assert wrong == 0
    assert _one(con, f"SELECT count(*) FROM {REFERENCE} WHERE NOT MeetsMinK") == 34  # noqa: S608


def test_health_mix_vendors_are_all_known_vendors(con) -> None:
    # No flag of its own: the k filter borrows vendor_revenue_summary's, so every vendor here must
    # exist there, or a viewer's filter couldn't find it.
    assert _names(con, "vendor_health_mix") <= _names(con, REFERENCE)


# --- The monthly table: known, pinned differences ----------------------------------------------


def test_monthly_vendor_names_differ_in_known_ways_only(con) -> None:
    monthly, vendors = _names(con, "vendor_monthly_demand"), _names(con, REFERENCE)
    assert len(monthly) == 129
    assert monthly - vendors == NAMES_ONLY_IN_MONTHLY
    assert vendors - monthly == NAMES_ONLY_IN_VENDOR_TABLES


def test_vendors_missing_from_monthly_have_no_revenue(con) -> None:
    """Why their absence is expected rather than a gap: they sold nothing."""
    names = ", ".join(f"'{n}'" for n in sorted(NAMES_ONLY_IN_VENDOR_TABLES))
    total = _one(con, f"SELECT sum(TotalRevenue) FROM {REFERENCE} WHERE VendorName IN ({names})")  # noqa: S608
    assert total == pytest.approx(0.0)


def test_revenue_gap_between_the_two_sources_is_pinned(con) -> None:
    """RAID R6: $442,768.33, split $44,869.03 (names only in the monthly sheet) + $397,899.30
    (66 vendors whose monthly sum differs from their vendor-table total)."""
    vendor_total = _one(con, f"SELECT sum(TotalRevenue) FROM {REFERENCE}")  # noqa: S608
    monthly_total = _one(con, "SELECT sum(MonthlyRevenue) FROM vendor_monthly_demand")
    assert vendor_total == pytest.approx(451_620_183.69, abs=0.01)
    assert monthly_total == pytest.approx(452_062_952.02, abs=0.01)

    split = con.execute(
        f"""
        WITH m AS (SELECT VendorName, sum(MonthlyRevenue) AS mr
                   FROM vendor_monthly_demand GROUP BY VendorName)
        SELECT
          sum(m.mr) FILTER (WHERE r.VendorName IS NULL),
          sum(m.mr - r.TotalRevenue) FILTER (WHERE r.VendorName IS NOT NULL),
          count(*) FILTER (WHERE r.VendorName IS NOT NULL AND abs(m.mr - r.TotalRevenue) > 1)
        FROM m LEFT JOIN {REFERENCE} r USING (VendorName)
        """  # noqa: S608
    ).fetchone()
    assert split is not None
    only_monthly, matched_diff, vendors_differing = split
    assert only_monthly == pytest.approx(44_869.03, abs=0.01)
    assert matched_diff == pytest.approx(397_899.30, abs=0.01)
    assert vendors_differing == 66


def test_portfolio_monthly_is_the_sum_of_vendor_monthly(con) -> None:
    disagreements = _one(
        con,
        """
        SELECT count(*) FROM portfolio_monthly_demand p
        JOIN (SELECT SalesYear, SalesMonth, sum(MonthlyRevenue) AS rev
              FROM vendor_monthly_demand GROUP BY SalesYear, SalesMonth) v
          USING (SalesYear, SalesMonth)
        WHERE abs(p.MonthlyRevenue - v.rev) > 0.005
        """,
    )
    assert disagreements == 0
    assert _one(con, "SELECT count(*) FROM portfolio_monthly_demand") == 12


def test_monthly_k_flag_is_decided_per_vendor_month(con) -> None:
    """The flag means "5+ products sold that month", not "5+ products in total", so some months
    of vendors a viewer can otherwise see are hidden from them (documented in methodology v4)."""
    k = get_settings().min_aggregation_k
    wrong = _one(
        con,
        f"SELECT count(*) FROM vendor_monthly_demand WHERE MeetsMinK <> (ActiveSKUs >= {k})",  # noqa: S608
    )
    assert wrong == 0
    assert _one(con, "SELECT count(*) FROM vendor_monthly_demand WHERE NOT MeetsMinK") == 428
    hidden_months_of_visible_vendors = _one(
        con,
        f"SELECT count(*) FROM vendor_monthly_demand m JOIN {REFERENCE} r "  # noqa: S608
        "USING (VendorName) WHERE r.MeetsMinK AND NOT m.MeetsMinK",
    )
    assert hidden_months_of_visible_vendors == 124
