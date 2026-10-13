"""Tests that the built snapshot is aggregate-only, fully catalogued and matches canonical metrics.

Skipped when the snapshot has not been built (it is git-ignored on purpose; see ADR-004).
"""

import json

import pytest

from copilot.data.guard import SKU_LEVEL_COLUMNS
from copilot.data.store import connect, snapshot_tables
from copilot.guardrails.policy import load_policy
from copilot.settings import get_settings

SNAP = get_settings().snapshot_dir
pytestmark = pytest.mark.skipif(not (SNAP / "MANIFEST.json").exists(), reason="snapshot not built")


def test_every_table_is_tagged_in_the_policy() -> None:
    policy = load_policy()
    untagged = [t for t in snapshot_tables() if t not in policy.tables]
    assert untagged == []


def test_no_sku_level_columns_anywhere() -> None:
    manifest = json.loads((SNAP / "MANIFEST.json").read_text())
    for name, info in manifest["tables"].items():
        assert not SKU_LEVEL_COLUMNS.intersection(info["columns"]), name
        assert info["rows"] <= 2000, name


def test_manifest_matches_files() -> None:
    manifest = json.loads((SNAP / "MANIFEST.json").read_text())
    con = connect()
    for name, info in manifest["tables"].items():
        n = con.execute(f"SELECT count(*) FROM {name}").fetchone()  # noqa: S608
        assert n is not None and n[0] == info["rows"], name


def test_canonical_metrics() -> None:
    con = connect()

    def one(sql: str) -> float:
        row = con.execute(sql).fetchone()
        assert row is not None
        return float(row[0])

    assert one("SELECT count(*) FROM vendor_revenue_summary") == 126
    assert one("SELECT round(sum(TotalRevenue)/1e6, 2) FROM vendor_revenue_summary") == 451.62
    assert one("SELECT round(sum(TotalLeakageAmount)/1e6, 2) FROM vendor_profit_leakage") == 24.96
    assert one("SELECT round(sum(ControllableLeakage)/1e6, 2) FROM vendor_profit_leakage") == 5.99
    assert one("SELECT round(sum(NonControllableCost)/1e6, 2) FROM vendor_profit_leakage") == 18.97
    assert (
        one("SELECT round(sum(NetProfitAfterAllCosts)/1e6, 1) FROM vendor_profit_leakage") == 109.1
    )
    assert one("SELECT sum(SKUs) FROM portfolio_health_mix") == 10495
    assert one("SELECT count(*) FROM vendor_pareto WHERE ParetoBand LIKE 'Top 80%'") == 17
