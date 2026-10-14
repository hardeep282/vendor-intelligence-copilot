"""copilot.sql.schema: schema linking restricts what a role is even shown.

Uses a small hand-written MANIFEST.json, not the real snapshot, so the test doesn't depend on
the snapshot's current column set.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from copilot.guardrails.policy import load_policy
from copilot.sql.schema import build_schema_card, visible_tables


@pytest.fixture
def manifest_path(tmp_path: Path) -> Path:
    manifest = {
        "tables": {
            "vendor_revenue_summary": {  # internal in disclosure.yaml
                "columns": ["VendorName", "TotalRevenue", "MeetsMinK"]
            },
            "portfolio_health_mix": {  # public in disclosure.yaml
                "columns": ["HealthStatus", "SKUs"]
            },
        }
    }
    path = tmp_path / "MANIFEST.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


@pytest.fixture
def policy():  # noqa: ANN201
    return load_policy()


def test_viewer_sees_both_public_and_internal_tables(policy, manifest_path) -> None:  # noqa: ANN001
    tables = {t.name for t in visible_tables(policy, "viewer", manifest_path)}
    assert tables == {"vendor_revenue_summary", "portfolio_health_mix"}


def test_anonymous_sees_only_public_tables(policy, manifest_path) -> None:  # noqa: ANN001
    tables = {t.name for t in visible_tables(policy, "anonymous", manifest_path)}
    assert tables == {"portfolio_health_mix"}


def test_internal_bookkeeping_column_is_never_shown(policy, manifest_path) -> None:  # noqa: ANN001
    tables = visible_tables(policy, "viewer", manifest_path)
    revenue_table = next(t for t in tables if t.name == "vendor_revenue_summary")
    assert "MeetsMinK" not in revenue_table.columns


def test_schema_card_names_the_data_class(policy, manifest_path) -> None:  # noqa: ANN001
    card = build_schema_card(policy, "viewer", manifest_path)
    assert "vendor_revenue_summary [internal]:" in card
    assert "portfolio_health_mix [public]:" in card


def test_schema_card_for_role_with_no_visible_tables_says_so(policy, manifest_path) -> None:  # noqa: ANN001
    card = build_schema_card(policy, "anonymous", manifest_path)
    assert "portfolio_health_mix" in card
    assert "vendor_revenue_summary" not in card
