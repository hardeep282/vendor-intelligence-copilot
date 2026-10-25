"""Template-based question -> SQL pair generation for the Day 9 fine-tuning set (B7).

Purpose : Day 3's cut-first item, picked back up on Day 9: a QLoRA SFT run needs several
          hundred (question, SQL) pairs, far more than the hand-written 46-row golden set
          (golden_v1 + golden_v2). Hand-writing 300-500 pairs isn't worth the hours; templating
          them against the real schema and keeping only the ones that actually execute is.
Inputs  : a live DuckDB connection (the real snapshot via copilot.data.store.connect() when run
          for real -- scripts/generate_sql_pairs.py is the CLI entrypoint for that) and the list
          of vendor names to parameterize over. Real vendor names are never hardcoded here --
          same licence rule as everywhere else in this repo (ADR-002); the CLI reads them from
          the connected database at generation time.
Outputs : `generate_candidates()` returns pure (unexecuted) question/SQL pairs; `verify_and_
          filter()` runs them through two filters, both counted:
            1. Execution -- the SQL must run against the connected database without raising.
               This is the spec's own bar ("keeps only pairs that execute correctly") and the
               one that matters for training data: a pair the model is trained to imitate must
               be real, runnable SQL.
            2. Safety-validator pass-through (`copilot.sql.validator.validate`) -- counted
               separately from (1) because a template can execute successfully yet still be a
               query shape we don't want to teach the model to produce (e.g. one the validator
               would cap with a LIMIT). Logged rather than silently rewritten, so the training
               set only ever contains SQL exactly as a human reading it would see it run.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass

import duckdb

from copilot.guardrails.policy import Role, load_policy
from copilot.sql.validator import validate

# Vendor-grain tables with a comparable "headline" numeric column -- the set every lookup,
# ranking and comparison template below draws from. Kept as a constant (not derived from the
# manifest) so the question text ("total revenue", "blended margin", ...) stays readable;
# generate_candidates() still skips any table not actually present in the connection.
HEADLINE_COLUMN: dict[str, str] = {
    "vendor_revenue_summary": "TotalRevenue",
    "vendor_tiering": "BlendedMargin",
    "vendor_pareto": "AvgMargin",
    "vendor_profit_leakage": "TotalLeakagePct",
    "vendor_rankings": "CompositePerformanceScore",
    "vendor_logistics_cost": "FreightPctOfRevenue",
    "vendor_full_cost": "NetMarginPct",
}

HEADLINE_LABEL: dict[str, str] = {
    "TotalRevenue": "total revenue",
    "BlendedMargin": "blended margin",
    "AvgMargin": "average margin",
    "TotalLeakagePct": "total leakage percentage",
    "CompositePerformanceScore": "composite performance score",
    "FreightPctOfRevenue": "freight percentage of revenue",
    "NetMarginPct": "net margin percentage",
}


@dataclass(frozen=True)
class Pair:
    question: str
    sql: str
    category: str
    table: str
    role: Role = "viewer"


@dataclass(frozen=True)
class FilterReport:
    candidates: int
    execution_failed: int
    validator_failed: int
    kept: int


def _quote(name: str) -> str:
    return name.replace("'", "''")


def _display(name: str) -> str:
    """How a vendor name appears in question text. Title case reads naturally in English, but it
    is NOT how names are stored -- most are uppercase ('VINEYARD BRANDS INC') and a handful are
    mixed case ('Dunn Wine Brokers', 'HOOD RIVER DISTILLERS, Inc.')."""
    return name.title()


def _vendor_eq(name: str) -> str:
    """Case-insensitive vendor filter that copies the name exactly as the question shows it.

    sql_pairs_v1 wrote the stored casing into the SQL (`VendorName = 'VINEYARD BRANDS INC'`)
    while the question showed `Vineyard Brands Inc` -- so the target needed information that is
    not in the prompt, and 314 of 327 vendor-filtered pairs had a literal that did not appear in
    their own question. A model can't learn casing it never sees; a model that guesses
    "uppercase it" is still wrong for the mixed-case vendors, and a wrong-case `=` returns zero
    rows with no error (a silent wrong answer). Matching on lower() of both sides removes the
    guess. Result rows are unchanged: the SELECT still returns the stored VendorName, and no two
    vendors in the snapshot differ only by case (checked when sql_pairs_v2 was generated).
    `lower(...) = lower(...)` rather than ILIKE because ILIKE treats `%` and `_` as wildcards.
    """
    return f"lower(VendorName) = lower('{_quote(_display(name))}')"


def _vendor_in(a: str, b: str) -> str:
    """Two-vendor version of `_vendor_eq`, same reasoning."""
    return f"lower(VendorName) IN (lower('{_quote(_display(a))}'), lower('{_quote(_display(b))}'))"


def vendor_names(con: duckdb.DuckDBPyConnection, limit: int | None = None) -> list[str]:
    """Real vendor names meeting the min-k threshold, read from the connected database, in a
    stable order. Never hardcoded -- see ADR-002."""
    sql = "SELECT VendorName FROM vendor_revenue_summary WHERE MeetsMinK ORDER BY VendorName"
    rows = con.execute(sql).fetchall()
    names = [r[0] for r in rows]
    return names[:limit] if limit else names


def _tables_present(con: duckdb.DuckDBPyConnection) -> set[str]:
    rows = con.execute("SHOW TABLES").fetchall()
    return {r[0] for r in rows}


def generate_candidates(
    con: duckdb.DuckDBPyConnection, rng: random.Random, vendors: list[str]
) -> list[Pair]:
    """Build the full template x parameter grid. Nothing here is executed yet -- that's
    `verify_and_filter`'s job -- so this function is pure and cheap to unit test."""
    present = _tables_present(con)
    out: list[Pair] = []

    # 1. Single-vendor lookup -- one template per headline column, every vendor.
    for table, column in HEADLINE_COLUMN.items():
        if table not in present:
            continue
        label = HEADLINE_LABEL[column]
        for name in vendors:
            out.append(
                Pair(
                    question=f"What is {_display(name)}'s {label}?",
                    sql=(f"SELECT VendorName, {column} FROM {table} WHERE {_vendor_eq(name)}"),
                    category="lookup",
                    table=table,
                )
            )

    # 2. Pairwise comparison -- two distinct vendors, same headline column.
    for table, column in HEADLINE_COLUMN.items():
        if table not in present:
            continue
        label = HEADLINE_LABEL[column]
        pool = rng.sample(vendors, k=min(len(vendors), 40))
        for a, b in zip(pool[::2], pool[1::2], strict=False):
            out.append(
                Pair(
                    question=f"Which has the higher {label}, {_display(a)} or {_display(b)}?",
                    sql=(
                        f"SELECT VendorName, {column} FROM {table} "
                        f"WHERE {_vendor_in(a, b)} "
                        f"ORDER BY {column} DESC"
                    ),
                    category="comparison",
                    table=table,
                )
            )

    # 3. Top-N ranking, N in {3, 5, 10}, both directions.
    for table, column in HEADLINE_COLUMN.items():
        if table not in present:
            continue
        label = HEADLINE_LABEL[column]
        for n in (3, 5, 10):
            out.append(
                Pair(
                    question=f"Which {n} vendors have the highest {label}?",
                    sql=(
                        f"SELECT VendorName, {column} FROM {table} "
                        f"WHERE MeetsMinK ORDER BY {column} DESC, VendorName LIMIT {n}"
                    ),
                    category="aggregation",
                    table=table,
                )
            )
            out.append(
                Pair(
                    question=f"Which {n} vendors have the lowest {label}?",
                    sql=(
                        f"SELECT VendorName, {column} FROM {table} "
                        f"WHERE MeetsMinK ORDER BY {column} ASC, VendorName LIMIT {n}"
                    ),
                    category="aggregation",
                    table=table,
                )
            )

    # 4. Portfolio-level aggregation -- no vendor filter at all.
    if "vendor_revenue_summary" in present:
        out.append(
            Pair(
                question="What is the portfolio's total revenue across every vendor?",
                sql=(
                    "SELECT round(sum(TotalRevenue), 2) AS TotalRevenue FROM vendor_revenue_summary"
                ),
                category="aggregation",
                table="vendor_revenue_summary",
            )
        )
        out.append(
            Pair(
                question="How many vendors are in the portfolio?",
                sql="SELECT count(*) AS vendors FROM vendor_revenue_summary",
                category="aggregation",
                table="vendor_revenue_summary",
            )
        )
    if "vendor_pareto" in present:
        for band in ("Top 80%", "Bottom 20%"):
            out.append(
                Pair(
                    question=f"How many vendors fall in the '{band}' Pareto band?",
                    sql=(
                        "SELECT count(*) AS vendors FROM vendor_pareto "
                        f"WHERE ParetoBand LIKE '{_quote(band)}'"
                    ),
                    category="aggregation",
                    table="vendor_pareto",
                )
            )

    # 5. Trend -- monthly demand for one vendor, and for the whole portfolio.
    if "vendor_monthly_demand" in present:
        for name in vendors:
            out.append(
                Pair(
                    question=f"How did {_display(name)}'s monthly demand trend across the year?",
                    sql=(
                        "SELECT SalesYear, SalesMonth, MonthlyDemand FROM vendor_monthly_demand "
                        f"WHERE {_vendor_eq(name)} ORDER BY SalesYear, SalesMonth"
                    ),
                    category="trend",
                    table="vendor_monthly_demand",
                )
            )
    if "portfolio_monthly_demand" in present:
        out.append(
            Pair(
                question="What was the portfolio's monthly demand trend across the year?",
                sql=(
                    "SELECT SalesYear, SalesMonth, MonthlyDemand FROM portfolio_monthly_demand "
                    "ORDER BY SalesYear, SalesMonth"
                ),
                category="trend",
                table="portfolio_monthly_demand",
            )
        )

    # 6. Health-mix breakdown.
    if "portfolio_health_mix" in present:
        out.append(
            Pair(
                question="What share of SKUs falls into each health status across the portfolio?",
                sql=(
                    "SELECT HealthStatus, SKUs, SharePct FROM portfolio_health_mix "
                    "ORDER BY SharePct DESC"
                ),
                category="aggregation",
                table="portfolio_health_mix",
            )
        )
    if "vendor_health_mix" in present:
        for name in vendors:
            out.append(
                Pair(
                    question=f"What is {_display(name)}'s SKU health mix?",
                    sql=(
                        "SELECT HealthStatus, SKUs FROM vendor_health_mix "
                        f"WHERE {_vendor_eq(name)} ORDER BY HealthStatus"
                    ),
                    category="lookup",
                    table="vendor_health_mix",
                )
            )

    return out


def verify_and_filter(
    con: duckdb.DuckDBPyConnection, candidates: list[Pair]
) -> tuple[list[Pair], FilterReport]:
    """Filter 1 (execution) then filter 2 (safety validator), in that order, both counted."""
    policy = load_policy()
    executed: list[Pair] = []
    exec_failed = 0
    for pair in candidates:
        try:
            con.execute(pair.sql).fetchall()
        except duckdb.Error:
            exec_failed += 1
            continue
        executed.append(pair)

    kept: list[Pair] = []
    validator_failed = 0
    for pair in executed:
        result = validate(pair.sql, pair.role, policy)
        if not result.ok:
            validator_failed += 1
            continue
        kept.append(pair)

    report = FilterReport(
        candidates=len(candidates),
        execution_failed=exec_failed,
        validator_failed=validator_failed,
        kept=len(kept),
    )
    return kept, report


def category_breakdown(pairs: list[Pair]) -> dict[str, int]:
    return dict(Counter(p.category for p in pairs))


def table_breakdown(pairs: list[Pair]) -> dict[str, int]:
    return dict(Counter(p.table for p in pairs))
