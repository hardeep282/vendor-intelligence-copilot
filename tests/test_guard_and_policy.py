"""Tests for the licence guard and the disclosure policy (no snapshot needed)."""

import pytest

from copilot.data.guard import LicenceViolation, check_table
from copilot.guardrails.policy import load_policy


def test_guard_rejects_sku_level_columns() -> None:
    with pytest.raises(LicenceViolation):
        check_table("bad", ["VendorName", "Description"], 10)


def test_guard_rejects_big_tables() -> None:
    with pytest.raises(LicenceViolation):
        check_table("bad", ["VendorName"], 94_092)


def test_guard_accepts_vendor_level() -> None:
    check_table("vendor_x", ["VendorName", "TotalRevenue"], 126)


def test_nobody_may_read_restricted() -> None:
    p = load_policy()
    for role in p.roles:
        assert not p.can_view(role, "restricted")


def test_role_ladder() -> None:
    p = load_policy()
    assert p.can_view("viewer", "internal")
    assert not p.can_view("viewer", "confidential")
    assert p.can_view("analyst", "confidential")
    assert p.can_view("anonymous", "public")
    assert not p.can_view("anonymous", "internal")


def test_untagged_table_fails_closed() -> None:
    assert load_policy().class_of("some_new_table") == "restricted"


def test_k_threshold_roles() -> None:
    p = load_policy()
    assert p.k_applies("viewer")
    assert not p.k_applies("analyst")
