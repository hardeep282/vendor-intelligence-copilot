---
doc_type: metric_definitions
vendor: null
version: 1
data_class: public
allowed_roles: [anonymous, viewer, analyst, approver, admin]
---

# Metric definitions

The exact definition and formula behind every number this system can produce. The Data Analyst
agent's generated SQL must match these definitions; the sqlglot semantic-rules layer
(`policies/sql_rules.yaml`) blocks SQL that visibly violates one.

## Blended margin vs. average margin

**Blended margin % = SUM(TotalGrossProfit) / SUM(TotalRevenue) x 100** — a ratio of sums, weighted
by each vendor's or SKU's revenue. This is the correct figure for any portfolio-level or
multi-vendor margin claim.

**Average margin % = AVG(margin_pct column)** — the simple mean of each row's own margin
percentage, unweighted. A vendor with many small high-margin SKUs and one huge low-margin SKU can
show a high average margin and a low blended margin at the same time.

Worked example from this portfolio: AVG(BlendedMarginPct) across all vendor rows returns 5.31%,
while the correct ratio-of-sums blended margin is 28.72% — a 23-point gap from using the wrong
formula. **Never use AVG() over a margin or percentage column to answer a portfolio-level margin
question.**

## Controllable vs. non-controllable leakage

Total cost leakage = $24.96M (5.5% of revenue), split into:
- **Controllable leakage ($5.99M):** loss-making SKUs ($4.35M) + freight overcharges ($1.64M).
  These are the figures a renegotiation or inventory action can actually move.
- **Non-controllable leakage ($18.97M):** excise tax. Set by regulation, not vendor negotiation.

A leakage question that doesn't specify controllable vs. total should be answered with both
figures stated separately, never summed into one undifferentiated number.

## Freight cost: MAX, never SUM

FreightCost is recorded once per vendor, not once per SKU. A query that joins vendor-level
freight to SKU-level rows and then sums freight will multiply it by the SKU count (a "fan-out"
join) — this is a documented failure mode (see Data Dictionary: vendor_logistics_cost). Always
aggregate FreightCost with MAX() per vendor, never SUM().

## Health classification: three independent dimensions

Loss-making, dead stock and profitable-but-slow are each their own 100%-summing classification,
not three slices of one pie. Dead stock is 60.4% of SKUs (6,334); loss-making is 20.3% (2,127).
These two percentages are not mutually exclusive and must never be added together or presented as
parts of a single 100% breakdown.

## Micro-vendor exclusion

Vendors with revenue under $10K are excluded from average-based vendor metrics (they would skew
an average) but are kept in risk-flagging views, since a tiny vendor can still carry
disproportionate risk.

## Minimum aggregation threshold (k)

No figure shown to a `viewer` or `anonymous` role may be built from fewer than k = 5 SKUs
(`policies/disclosure.yaml`, `min_aggregation.k`). Rows where `MeetsMinK` is False must be
suppressed from any output those roles see — this stops a viewer from reverse-engineering a
single SKU's figures through a narrow filter.

## Data coverage

All demand and transaction data covers **2024 only** (12 months). A question about 2025 or any
other year is out of coverage and must be answered by stating that fact, not by running a filter
that silently returns zero rows.

## StockTurnover exclusion

StockTurnover values above 10 are excluded from averages — they are near-certainly a data
artefact (e.g. a SKU sold once right after being stocked), not a genuine fast-turnover signal.
