"""Day 8, Addendum A2 §1.6: per-user and per-IP request rate limiting, plus a per-user daily
token/cost budget, for the HTTP API -- on top of (not instead of) Day 7's `InputGate`, which
limits per-*role*.

Purpose : a per-role limit alone has two gaps a real multi-tenant API can't ignore: every
          `viewer`-role caller shares one bucket (one noisy API key can starve every other
          viewer), and an unauthenticated or key-less request isn't bucketed by role at all.
          This module adds two more axes, identity (API key) and network origin (client IP),
          independent of role.
Inputs  : an identity string (an `AuthStore` `Principal.key_id`, or a client IP address) per
          check.
Outputs : `RequestRateLimiter.allow(identity) -> bool`; `DailyBudgetTracker.record`/
          `.spent_today`, the same shape as `copilot.guardrails.input_gate.SpendTracker` but
          keyed by caller identity instead of role, in its own file so the two never collide.
"""

from __future__ import annotations

import time
from pathlib import Path

from copilot.guardrails.input_gate import SpendTracker
from copilot.settings import REPO_ROOT

DEFAULT_USER_SPEND_PATH = REPO_ROOT / "data" / "spend" / "daily_user_spend.json"


class RequestRateLimiter:
    """An in-memory sliding-window limiter, one window per identity -- the same mechanism
    `copilot.guardrails.input_gate.RateLimiter` already uses per-role, reused here rather than
    reimplemented, just keyed by whatever string the caller passes (a `key_id` or an IP) instead
    of a `Role`. Process-local by design, same tradeoff as the per-role limiter: a multi-process
    deployment would need a shared store (Redis, etc.) to enforce one true limit across
    processes -- out of scope for this sprint's single-process deployment, noted here rather
    than silently assumed away.
    """

    def __init__(self, max_per_minute: int) -> None:
        self._max_per_minute = max_per_minute
        self._hits: dict[str, list[float]] = {}

    def allow(self, identity: str) -> bool:
        now = time.monotonic()
        window_start = now - 60.0
        hits = [t for t in self._hits.get(identity, []) if t >= window_start]
        allowed = len(hits) < self._max_per_minute
        hits.append(now)
        self._hits[identity] = hits
        return allowed


class DailyBudgetTracker:
    """Per-caller-identity version of `copilot.guardrails.input_gate.SpendTracker` -- same
    file-backed, loaded-fresh-per-call shape, deliberately a thin wrapper around that class
    rather than a duplicate implementation: `SpendTracker`'s `role: str` parameter is really just
    a dict key, so a `key_id` fits it exactly, pointed at its own file (`daily_user_spend.json`,
    not `daily_spend.json`) so per-user and per-role totals never share rows.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._tracker = SpendTracker(path if path is not None else DEFAULT_USER_SPEND_PATH)

    def spent_today(self, identity: str) -> float:
        return self._tracker.spent_today(identity)

    def record(self, identity: str, cost_usd: float) -> bool:
        return self._tracker.record(identity, cost_usd)


__all__ = ["DailyBudgetTracker", "RequestRateLimiter"]
