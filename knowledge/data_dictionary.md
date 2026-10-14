---
doc_type: data_dictionary
vendor: null
version: 1
data_class: public
allowed_roles: [anonymous, viewer, analyst, approver, admin]
---

# Data dictionary

What each snapshot table and column means. Every table here is the licence-safe, aggregate-only
Gold snapshot (`data/snapshot/*.parquet`) built by `scripts/build_snapshot.py` from the vendor
analytics project's Gold views — never the raw purchased dataset.

## Vendor-level tables (one row per vendor, 126 rows)

### vendor_revenue_summary

| Column | Meaning |
|---|---|
| VendorName | The vendor's name as it appears in the source workbook. |
| NumberOfSKUs | Count of distinct SKUs sold by this vendor. |
| TotalRevenue | Sum of revenue across all the vendor's SKUs, in USD. |
| TotalGrossProfit | TotalRevenue minus TotalPurchaseCost. |
| AvgMarginPct | The simple average of each SKU's margin percentage. Do not use this for a
  portfolio-level margin figure — it is not weighted by revenue, so it can diverge sharply from
  BlendedMarginPct (see Metric Definitions: Blended margin vs. average margin). |
| TotalPurchaseCost | What the distributor paid the vendor for the goods. |
| RevenueSharePct | This vendor's TotalRevenue as a percentage of total portfolio revenue. |
| BlendedMarginPct | TotalGrossProfit divided by TotalRevenue, as a percentage. The correct
  figure for a portfolio-level or vendor-level margin claim. |
| MeetsMinK | Boolean. True if NumberOfSKUs >= the disclosure policy's minimum aggregation
  threshold (currently 5). A viewer-role query must suppress rows where this is False. |

### vendor_tiering

Vendor tier classification (e.g. strategic, core, long-tail) used for Pareto and prioritisation
analysis. Same 126-row grain as vendor_revenue_summary.

### vendor_pareto

Cumulative revenue share by vendor, ranked descending, used for the 80/20 (Pareto) analysis.
17 vendors account for 80% of portfolio revenue; the top 10 vendors account for 65.01%.

### vendor_profit_leakage

Controllable and non-controllable cost leakage by vendor: loss-making SKUs, freight overcharges,
excise tax. Total portfolio leakage is $24.96M, of which $5.99M is controllable (loss-making SKUs
$4.35M + freight $1.64M) and $18.97M is non-controllable excise tax.

### vendor_rankings

Vendor rank by revenue, margin and SKU count, used for comparison questions ("who are our top 5
vendors by margin").

### vendor_logistics_cost

Freight and logistics cost by vendor. **FreightCost is a vendor-level figure, not a SKU-level
one** — when aggregating across a vendor's SKUs, use MAX(FreightCost), never SUM. Summing it
produces a fan-out inflation (observed: $1.64M becomes $19.68M when freight is summed across a
join that repeats vendor rows per SKU).

### vendor_full_cost

Combined view of purchase cost, freight and excise tax per vendor, used for full-cost margin
questions.

## Demand tables

### vendor_monthly_demand (1,400 rows: vendor x month)

Monthly demand aggregated to the vendor level. Covers 12 months (2024 only — see Methodology:
Data coverage). Do not mix this table's revenue total with vendor_revenue_summary's total in the
same answer without noting the ~0.1% gap between the two source tables (RAID item R6).

### portfolio_monthly_demand (12 rows: one per month)

Demand aggregated to the whole-portfolio level, one row per month. Public class — no vendor-level
detail, so no aggregation threshold applies.

## SKU health tables

### vendor_health_mix (399 rows: vendor x health category)

Count of SKUs per vendor in each of five health categories: Healthy, Profitable but Slow, Loss
Making, At Risk, Thin Margin. **These five categories are independent classification dimensions
that each sum to 100% on their own — never add counts across them** (a SKU can be "Loss Making"
by one dimension and also appear in another dimension's count; adding the two double-counts it).

### portfolio_health_mix (5 rows: one per health category)

Portfolio-wide SKU counts per health category. Totals: Healthy 4,112; Profitable but Slow 3,181;
Loss Making 2,127; At Risk 1,048; Thin Margin 27 (10,495 SKUs total).

## What is never in this snapshot

Raw SKU-level transaction rows, customer or store identifiers, anything from the licensed
`vendor_sales_summary`, `vw_PortfolioHealth`, `vw_CleanAnalysis`, `output_monthly_demand` or
`vw_VendorSalesBase` tables — those names are Restricted (`policies/disclosure.yaml`) and must
never appear in an answer, draft, trace or log.
