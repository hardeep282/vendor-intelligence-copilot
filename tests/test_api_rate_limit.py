"""Tests for copilot.api.rate_limit: the per-identity (API key) / per-IP request limiter and the
per-identity daily budget tracker -- Day 8, Addendum A2 §1.6, on top of (not instead of)
InputGate's own per-role limiter (Day 7).
"""

from __future__ import annotations

from pathlib import Path

from copilot.api.rate_limit import DailyBudgetTracker, RequestRateLimiter


def test_requests_within_the_limit_are_all_allowed() -> None:
    limiter = RequestRateLimiter(max_per_minute=3)
    assert limiter.allow("key-a") is True
    assert limiter.allow("key-a") is True
    assert limiter.allow("key-a") is True


def test_the_request_over_the_limit_is_refused() -> None:
    limiter = RequestRateLimiter(max_per_minute=3)
    for _ in range(3):
        assert limiter.allow("key-a") is True
    assert limiter.allow("key-a") is False


def test_limits_are_tracked_separately_per_identity() -> None:
    """One noisy API key (or IP) must never consume another identity's budget -- the entire
    point of keying per-identity instead of the shared per-role bucket InputGate already has."""
    limiter = RequestRateLimiter(max_per_minute=1)
    assert limiter.allow("key-a") is True
    assert limiter.allow("key-b") is True  # a different identity, its own fresh window
    assert limiter.allow("key-a") is False  # key-a's own window is the one that's exhausted


def test_daily_budget_tracker_accumulates_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "daily_user_spend.json"
    tracker = DailyBudgetTracker(path)

    assert tracker.spent_today("key-a") == 0.0
    tracker.record("key-a", 0.30)
    tracker.record("key-a", 0.25)

    assert tracker.spent_today("key-a") == 0.55
    # A fresh tracker over the same file sees the same total -- it has to survive a restart.
    assert DailyBudgetTracker(path).spent_today("key-a") == 0.55


def test_daily_budget_is_tracked_separately_per_identity(tmp_path: Path) -> None:
    tracker = DailyBudgetTracker(tmp_path / "daily_user_spend.json")
    tracker.record("key-a", 0.90)

    assert tracker.spent_today("key-a") == 0.90
    assert tracker.spent_today("key-b") == 0.0
