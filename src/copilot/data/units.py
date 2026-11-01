"""What each snapshot column measures, so tool output never reaches the drafter as a bare number.

Purpose : attach units and meanings ("US dollars", "% of the vendor's total revenue", "units
          sold") to the columns a Data Analyst query returns. Added 30 Oct 2026 after the first
          real UI run: the drafter called a demand forecast in units "$3,758,005 per month" and
          called ControllableLeakagePct "% of controllable margin", and the Verifier passed both,
          because the findings it checks against carried bare numbers with no units.
Inputs  : the SQL text a query ran.
Outputs : one plain-English line per selected column whose meaning is known.

Every percentage below was checked against the snapshot on 30 Oct 2026 by recomputing it
(for example ControllableLeakage / TotalRevenue x 100 matches ControllableLeakagePct to within
0.005 on every vendor row). Columns whose meaning hasn't been verified are deliberately left
out: no label is better than a wrong label.
"""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

USD = "US dollars"
PCT_OF_VENDOR_REVENUE = "percent of that vendor's total revenue"
SKU_COUNT = "number of products (SKUs)"

COLUMN_UNITS: dict[str, str] = {
    # money
    "TotalRevenue": USD,
    "MonthlyRevenue": USD,
    "TotalGrossProfit": USD,
    "TotalProfit": USD,
    "TotalCOGS": USD,
    "TotalPurchaseCost": USD,
    "TotalFreight": USD,
    "TotalExciseTax": USD,
    "TotalAllCosts": USD,
    "NetProfitAfterAllCosts": USD,
    "PotentialProfit": USD,
    "CumulativeRevenue": USD,
    "ExciseLeakage": USD,
    "FreightLeakage": USD,
    "LossMakingLeakage": USD,
    "DeadStockRevenue": USD,
    "TotalLeakageAmount": USD,
    "ControllableLeakage": USD,
    "NonControllableCost": USD,
    # volume
    "MonthlyDemand": "units sold (individual items such as bottles), not dollars",
    # percentages of the vendor's own revenue (each recomputed and checked)
    "ExciseLeakagePct": PCT_OF_VENDOR_REVENUE,
    "FreightLeakagePct": PCT_OF_VENDOR_REVENUE,
    "LossMakingLeakagePct": PCT_OF_VENDOR_REVENUE,
    "DeadStockRevenuePct": PCT_OF_VENDOR_REVENUE,
    "TotalLeakagePct": PCT_OF_VENDOR_REVENUE,
    "ControllableLeakagePct": PCT_OF_VENDOR_REVENUE,
    "PotentialMarginPct": PCT_OF_VENDOR_REVENUE,
    "NetMarginAfterAllCostsPct": PCT_OF_VENDOR_REVENUE,
    "NetMarginPct": PCT_OF_VENDOR_REVENUE,
    "COGSRatioPct": PCT_OF_VENDOR_REVENUE,
    "FreightBurdenPct": PCT_OF_VENDOR_REVENUE,
    "ExciseBurdenPct": PCT_OF_VENDOR_REVENUE,
    "FreightPctOfRevenue": PCT_OF_VENDOR_REVENUE,
    "ExcisePctOfRevenue": PCT_OF_VENDOR_REVENUE,
    "TotalCostBurdenPct": PCT_OF_VENDOR_REVENUE,
    # margins
    "BlendedMargin": "blended margin: total gross profit / total revenue, percent",
    "BlendedMarginPct": "blended margin: total gross profit / total revenue, percent",
    "AvgMargin": "simple average of per-product margins, percent (unweighted; prefer blended)",
    "AvgMarginPct": "simple average of per-product margins, percent (unweighted; prefer blended)",
    # shares and counts
    "RevenueSharePct": "percent of the whole portfolio's revenue",
    "CumulativeRevenuePct": "cumulative percent of the whole portfolio's revenue",
    "DeadStockSKUsPct": "percent of that vendor's products (SKUs)",
    "LossMakingSKUsPct": "percent of that vendor's products (SKUs)",
    "SharePct": "percent of all products (SKUs)",
    "TotalSKUs": SKU_COUNT,
    "NumberOfSKUs": SKU_COUNT,
    "SKUCount": SKU_COUNT,
    "SKUs": SKU_COUNT,
    "ActiveSKUs": SKU_COUNT,
    "LossMakingSKUs": SKU_COUNT,
    "DeadStockSKUs": SKU_COUNT,
}

# Aggregates that keep a column's unit (a SUM of dollars is still dollars). COUNT does not.
_UNIT_PRESERVING = (exp.Sum, exp.Avg, exp.Min, exp.Max, exp.Round)


def describe_units(sql: str, dialect: str = "duckdb") -> list[str]:
    """One line per selected output column whose unit is known, e.g.
    ``controllable_leakage_pct (ControllableLeakagePct): percent of that vendor's total revenue``.

    Conservative on purpose: a select expression is labelled only when it reads exactly one
    known column, directly or through SUM/AVG/MIN/MAX/ROUND. Ratios of two columns, COUNTs and
    anything unparseable get no label rather than a guessed one.
    """
    try:
        statement = sqlglot.parse_one(sql, read=dialect)
    except Exception:  # noqa: BLE001 -- unparseable SQL just means "no labels"
        return []
    select = statement if isinstance(statement, exp.Select) else statement.find(exp.Select)
    if select is None:
        return []

    lines: list[str] = []
    for projection in select.expressions:
        columns = list(projection.find_all(exp.Column))
        if len(columns) != 1:
            continue
        name = columns[0].name
        unit = COLUMN_UNITS.get(name)
        if unit is None:
            continue
        inner = projection.this if isinstance(projection, exp.Alias) else projection
        functions = [f for f in inner.find_all(exp.Func) if not isinstance(f, exp.Column)]
        if any(not isinstance(f, _UNIT_PRESERVING) for f in functions):
            continue
        output_name = projection.alias_or_name
        label = output_name if output_name == name else f"{output_name} ({name})"
        lines.append(f"{label}: {unit}")
    return lines


def ordering_column(sql: str, dialect: str = "duckdb") -> tuple[str, bool] | None:
    """(measure the rows are sorted by, descending?) for a query's first ORDER BY key, or None
    when there's no ORDER BY or the SQL can't be parsed.

    The measure is reported as the snapshot column it was built from where there's exactly
    one: an alias (``ORDER BY total``) is mapped back through the SELECT list, and an aggregate
    of one column (``ORDER BY SUM(TotalRevenue)``) reports that column. Anything else (a ratio
    of two columns, say) is reported as its SQL text.
    """
    try:
        statement = sqlglot.parse_one(sql, read=dialect)
    except Exception:  # noqa: BLE001 -- unparseable SQL just means "unknown ordering"
        return None
    select = statement if isinstance(statement, exp.Select) else statement.find(exp.Select)
    if select is None:
        return None
    order = select.args.get("order")
    if not isinstance(order, exp.Order) or not order.expressions:
        return None
    first = order.expressions[0]
    target = first.this if isinstance(first, exp.Ordered) else first
    descending = bool(first.args.get("desc")) if isinstance(first, exp.Ordered) else False

    source: exp.Expression = target
    if isinstance(target, exp.Column) and not target.table:
        # ORDER BY an alias -> look through to the expression the alias names
        for projection in select.expressions:
            if isinstance(projection, exp.Alias) and projection.alias == target.name:
                source = projection.this
                break
    columns = list(source.find_all(exp.Column)) if not isinstance(source, exp.Column) else [source]
    name = columns[0].name if len(columns) == 1 else source.sql(dialect=dialect)
    return name, descending


def describe_ordering(sql: str, dialect: str = "duckdb") -> str | None:
    """The measure a query's rows are sorted by, in plain words, e.g.
    ``Sorted by: TotalLeakageAmount (highest first)``. None when the query has no ORDER BY.

    Added 30 Oct 2026: a real run asked for the most *controllable* leakage, the generated SQL
    sorted by *total* leakage, and the drafter, which only sees the first rows, presented the
    wrong top five as the answer. The Verifier couldn't notice, because nothing it reads said
    how the rows were ordered.
    """
    found = ordering_column(sql, dialect=dialect)
    if found is None:
        return None
    name, descending = found
    direction = "highest first" if descending else "lowest first"
    return f"Sorted by: {name} ({direction})"


#: Words that make a question a ranking ("which vendors leak the MOST ...", "TOP 5 by ...").
RANKING_WORDS = re.compile(
    r"\b(most|highest|largest|biggest|top|least|lowest|smallest|rank|ranked|ranking)\b",
    re.IGNORECASE,
)

#: (words in the question, plain-English measure, columns that answer it). Checked in order and
#: the first match wins, so specific measures ("freight leakage") come before general ones
#: ("revenue"). Only measures whose columns were verified against the snapshot are listed;
#: a question naming none of them is never second-guessed.
RANKING_MEASURES: list[tuple[re.Pattern[str], str, tuple[str, ...]]] = [
    (
        re.compile(r"\bcontrollable\b", re.IGNORECASE),
        "controllable leakage",
        ("ControllableLeakage", "ControllableLeakagePct"),
    ),
    (
        re.compile(r"\bfreight\b", re.IGNORECASE),
        "freight",
        (
            "TotalFreight",
            "FreightLeakage",
            "FreightLeakagePct",
            "FreightBurdenPct",
            "FreightPctOfRevenue",
        ),
    ),
    (
        re.compile(r"\bexcise\b", re.IGNORECASE),
        "excise tax",
        (
            "TotalExciseTax",
            "ExciseLeakage",
            "ExciseLeakagePct",
            "ExciseBurdenPct",
            "ExcisePctOfRevenue",
        ),
    ),
    (
        re.compile(r"\bloss[\s-]*making\b", re.IGNORECASE),
        "loss-making leakage",
        ("LossMakingLeakage", "LossMakingLeakagePct", "LossMakingSKUs", "LossMakingSKUsPct"),
    ),
    (
        re.compile(r"\btotal\s+leakage\b", re.IGNORECASE),
        "total leakage",
        ("TotalLeakageAmount", "TotalLeakagePct"),
    ),
    (
        re.compile(r"\bblended\s+margin\b", re.IGNORECASE),
        "blended margin",
        ("BlendedMargin", "BlendedMarginPct"),
    ),
    (
        re.compile(r"\bgross\s+profit\b", re.IGNORECASE),
        "gross profit",
        ("TotalGrossProfit",),
    ),
    (
        re.compile(r"\b(revenue|sales)\b", re.IGNORECASE),
        "revenue",
        ("TotalRevenue", "MonthlyRevenue", "RevenueSharePct"),
    ),
]


def expected_ranking(question: str) -> tuple[str, tuple[str, ...]] | None:
    """(plain-English measure, acceptable sort columns) when a question ranks by a measure this
    module knows; None otherwise (no ranking word, or no known measure named).

    Added 2 Nov 2026: in the full golden run oq-011 ("which vendors are leaking the most
    controllable margin") sorted by TotalLeakageAmount a second time, even with the v3 prompts.
    The answer honestly declined to rank, but the right query was one retry away.
    """
    if not RANKING_WORDS.search(question):
        return None
    for pattern, label, columns in RANKING_MEASURES:
        if pattern.search(question):
            return label, columns
    return None


__all__ = [
    "COLUMN_UNITS",
    "RANKING_MEASURES",
    "describe_ordering",
    "describe_units",
    "expected_ranking",
    "ordering_column",
]
