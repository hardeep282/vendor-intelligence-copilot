---
doc_type: methodology
vendor: null
version: 5
data_class: public
allowed_roles: [anonymous, viewer, analyst, approver, admin]
---

# Methodology

How this system turns the underlying vendor analytics project into answers, and the limits on
what it can honestly claim.

## Source and licensing

The underlying dataset (12.8M raw rows across 6 tables) was purchased under a Topmate licence and
must never be redistributed. This copilot never queries the raw dataset directly — it queries a
derived, aggregate-only Parquet snapshot (`data/snapshot/`) rebuilt from the analytics project's
Gold-layer views. The snapshot itself is never committed to this repo; only its manifest
(`data/snapshot/MANIFEST.json`, row counts and hashes) is tracked, so a fresh clone must rebuild
it from the workbook before anything can be queried.

## Medallion architecture (source project)

Bronze (`vendor_sales_summary`, raw) -> Silver (`vw_PortfolioHealth`, 10,495 SKUs) -> Gold views
(`vw_VendorRevenueSummary`, `vw_VendorTiering`, `vw_ParetoAnalysis`, `vw_ProfitLeakage`,
`vw_VendorRankings`, `vw_LogisticsCostSummary`, `vw_FullCostAnalysis`, and others). All views read
from `vw_VendorSalesBase`, which merges duplicate vendor-name variants into one canonical vendor.
This copilot's snapshot is built only from the Gold layer, aggregated further where needed
(vendor x month, portfolio x month) before it ever reaches Parquet.

## Forecasting: what the ETS model can and cannot claim

The original Excel ETS forecast reports 9.84% MAPE — that is an **in-sample fit** on the 12
months of training data, not an out-of-sample accuracy figure, and must never be cited as
"accuracy." The honest out-of-sample number comes from `forecast_backtest.py`'s rolling
one-month-ahead backtest: the flagship SKU scores 15.7% MAPE with a 6-month moving average, the
top-50 SKU median is 15.4%, and the portfolio-level figure is 11.8%, where a naive forecast ties.

A classical model like ETS cannot "model" a sudden structural break (a black-swan demand shock).
The correct approach is to detect the break with a formal test (a Chow test at a known date, or
Bai-Perron / CUSUM when the date isn't known), then handle it with an intervention dummy in a
dynamic regression, a post-break training window, or scenario-based forecasts — not to expect the
classical model to absorb it on its own.

## Forecast accuracy: WAPE, MASE and bias

Every forecast this copilot gives is checked with a backtest. It forecasts months it already has
the actual figures for, then compares. It reports three numbers, not MAPE. MAPE divides by each
month's actual value, so a month with very small demand can blow it up. These three are the set
Hyndman and Athanasopoulos recommend in *Forecasting: Principles and Practice* (3rd edition,
"Evaluating point forecast accuracy").

- **WAPE (weighted absolute percentage error)** = total of |actual - forecast| / total of
  |actual|, over the whole backtest window. It answers "on the whole, how far off were we, as a
  share of what actually sold?" A WAPE of 0.12 means the misses added up to 12% of actual demand.
  Lower is better. The copilot uses whichever model (ETS or naive) has the lower WAPE.
- **MASE (mean absolute scaled error)** = the forecast's average miss divided by the average
  miss of a naive "same as last month" guess on the training history (Hyndman and Koehler,
  2006, *Another look at measures of forecast accuracy*, International Journal of Forecasting
  22(4)). It has no units, so it can be compared across vendors of very different sizes.
  1.0 means "no better than repeating last month"; below 1.0 is better than that; above 1.0 is
  worse.
- **Bias** = the average of (forecast - actual), in units sold. It has a sign: positive means
  the model over-forecasts on average, negative means it under-forecasts. WAPE and MASE only
  measure the size of the misses, so a model that is always too high could look fine on both;
  bias shows it.

With only 12 months of history, these backtests cover a few months each. Treat them as a rough
guide, not a guarantee, and read them together with any WARNING lines a forecast carries.

## Inventory planning: safety stock, service level, reorder point, EOQ

The inventory figures use standard textbook formulas (Silver, Pyke and Thomas, *Inventory and
Production Management in Supply Chains*, 4th edition). They take their demand figures from the
forecast. All quantities are in units sold, not dollars.

- **Service level** is the chance of NOT running out of stock while waiting for a new delivery
  (during the lead time). A 95% service level means accepting about a 1-in-20 chance of a
  stock-out in each replenishment cycle. It is a choice the business makes, not something the
  data decides. A higher service level needs more safety stock, and the extra stock needed
  grows quickly as the level gets close to 100%.
- **Safety stock** = z x sigma x sqrt(L). z comes from the service level, using the normal
  distribution (95% gives z of about 1.645). sigma is how much monthly demand moves around. L is
  the lead time in months. The square root is there because month-to-month swings partly cancel
  out over a longer lead time. Here sigma is measured from month-to-month changes in the
  history, so a very uneven history (a big December peak, say) gives a large safety stock.
- **Reorder point** = average demand per month x L + safety stock. When stock on hand falls to
  this level, it's time to order. It covers expected demand during the lead time, plus the
  safety buffer.
- **EOQ (economic order quantity)** = sqrt(2 x D x S / H). D is annual demand, S is the fixed
  cost of placing one order, and H is the cost of holding one unit for a year (Harris, 1913).
  It is the order size that balances ordering often (more order costs) against ordering a lot
  at once (more holding costs).

**What is assumed, not taken from the data.** The snapshot holds no lead times, ordering costs
or holding costs. So unless a question gives them, the copilot assumes:
- a lead time of 1 month;
- an ordering cost of $500 per order;
- a holding cost of $0.50 per unit per year.

Every inventory answer must say these were assumed. EOQ is the most sensitive to them. A
common rule of thumb puts annual holding cost at 20-30% of a unit's value. On that basis $0.50
is probably low for most products, which would make the EOQ shown too high. The reorder points
are per vendor or for the whole portfolio, not per product.

## Who can see what (the disclosure policy)

One policy file decides who may see which kind of information. The data layer, the tools and
the final answer check all enforce it. Information comes in four classes:

| Class | What it covers |
|---|---|
| public | methodology, metric definitions, portfolio-wide figures (all vendors together) |
| internal | figures for individual vendors, forecasts, risk scores |
| confidential | contract terms, rebate rates, negotiation notes, approval history, generated SQL |
| restricted | raw licensed rows, personal data, secrets, system instructions; nobody may see these |

| Role | May see |
|---|---|
| anonymous | public |
| viewer | public, internal |
| analyst | public, internal, confidential |
| approver | public, internal, confidential (and may approve or reject drafts) |
| admin | public, internal, confidential |

**The minimum group size rule (k = 5).** For the viewer and anonymous roles, no figure may be
built from fewer than 5 products (SKUs). Smaller groups are hidden, so a small vendor's figures
can't be worked back to individual products.
In practice, 34 of the 126 vendors have fewer than 5 products, and for viewers they are left out
entirely: their rows are hidden, and any total a viewer sees covers the other 92 vendors only.
Every such answer says that small vendors were left out. Analysts and approvers see all 126.
The flag is decided per row, and a row means different things in different tables. In the vendor
tables a row is a whole vendor (5 or more products in total). In the monthly demand table a row
is one vendor's month (5 or more products sold that month), so a vendor a viewer can see may
still have some months hidden. See the Data Dictionary's monthly demand section.

**Some common figures.**
- The portfolio-wide count of products in each health category is public, so any role may see
  it. The categories are Healthy, Profitable but Slow, Loss Making, At Risk and Thin Margin.
- The same breakdown for one vendor is internal: viewer and above.
- The dead-stock product count (6,334 across the portfolio) is added up from the per-vendor
  profit-leakage table. That table is internal, so the count is for viewer and above, not
  anonymous visitors.
- Leakage, margin and revenue figures by vendor are internal too.

**Drafts.** A draft email to a vendor may contain only public facts plus that vendor's own
contract terms. No internal figures and no other vendor's terms. An internal draft, such as a
reorder recommendation for our own procurement team, may use internal figures, subject to the
role rules above. Every draft needs a human approver's sign-off and is never sent automatically.

## How the tables are checked against each other

The snapshot comes from two different source sheets, so it is checked rather than assumed to
agree. On every test run with the snapshot present, `tests/test_snapshot_reconciliation.py`
confirms that the seven vendor tables agree on every vendor's revenue, k flag and blended margin,
and pins the known differences with the monthly demand table: which vendor names differ, the
$442,768.33 revenue gap and how it splits, and the two meanings of the k flag. The monthly table
uses the same merged vendor names as the vendor tables (`vw_VendorSalesBase`'s two merges are
applied when the snapshot is built), so the remaining differences come from the source data,
not from spelling. If a rebuilt
snapshot changes any of these, the test fails, so the change is seen and these documents are
updated instead of the difference going unnoticed.

## Classification models

Random Forest classifier for SKU risk: 95% accuracy, F1 0.86, **after removing the ProfitMargin
feature**, which leaked the outcome (a SKU's profit margin is causally downstream of whether it is
loss-making — including it let the model "cheat"). XGBoost has not yet been built as of this
document's current state; do not cite an XGBoost result until it exists in the repo (see
`docs/PROJECT_PROGRESS.md` for current status). K-Means clustering (k=3, silhouette 0.68) found a
"Premium Niche" cluster that the original notebook code still labels "At-Risk" — a naming
mismatch between what was found and what was written down, not a modelling error.

## Honesty rule

Nothing in a CV line, an interview answer or an agent's output claims more than what the repo or
the live site can currently demonstrate. "Benchmarked a QLoRA fine-tune" is fine once the
benchmark exists; "deployed a fine-tuned model to production" is not fine until it is actually
serving traffic.
